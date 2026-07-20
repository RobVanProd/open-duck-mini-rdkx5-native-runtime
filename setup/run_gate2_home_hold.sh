#!/usr/bin/env bash
set -euo pipefail

readonly expected_source_commit="a5b53442012899f89c899f5c2f8f1a110c4448f2"
readonly expected_archive_sha256="730d53480de5cf3c64381c75984289994d4edb798e2b09aec31b1f8df7ff67f5"
readonly expected_config_sha256="131a7b8fce1107b14f4727562f44f9e17324caf7fc22512ad7115911f050991b"
readonly device="/dev/ttyS1"
readonly ticks="10000"
readonly home_seconds="5"
readonly policy="/sys/devices/system/cpu/cpufreq/policy0"
readonly runner_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

output_dir=""
source_archive=""
config_path=""
hardware_authorized=0
suspended_or_benched=0
moving_gate_authorized=0
active_probe_pid=""
work_dir=""
governor_original=""
governor_changed=0
restore_status=-1
preflight_probe_status=-1
preflight_validation_status=-1
home_probe_status=-1
home_validation_status=-1

usage() {
  cat <<'EOF'
Usage: sudo setup/run_gate2_home_hold.sh \
  --source-archive /home/sunrise/open-duck-x5-a5b5344.tar.gz \
  --config /home/sunrise/duck_config.json \
  --output-dir /home/sunrise/duck-evidence/gate2-home-hold-a5b5344 \
  --hardware-authorized --suspended-or-benched --moving-gate-authorized

Runs the frozen Gate 2 sequence on /dev/ttyS1. It first executes a complete
10,000-tick torque-off timing preflight. Only if every frozen preflight gate
passes does it enable torque, move from fresh measured positions to home over
five seconds, and hold home for 10,000 ticks with no policy and zero amplitude.
The CPU governor is verified as schedutil, changed to performance only for this
sequence, and restored on normal exit, failure, or signal.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source-archive)
      source_archive="$2"
      shift 2
      ;;
    --config)
      config_path="$2"
      shift 2
      ;;
    --output-dir)
      output_dir="$2"
      shift 2
      ;;
    --hardware-authorized)
      hardware_authorized=1
      shift
      ;;
    --suspended-or-benched)
      suspended_or_benched=1
      shift
      ;;
    --moving-gate-authorized)
      moving_gate_authorized=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "result=BLOCKED reason=unknown_argument argument=$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ "${EUID}" -ne 0 ]]; then
  echo "result=BLOCKED reason=root_required_for_governor_and_sched_fifo" >&2
  exit 2
fi
if [[ "${hardware_authorized}" -ne 1 || "${suspended_or_benched}" -ne 1 || \
      "${moving_gate_authorized}" -ne 1 ]]; then
  echo "result=BLOCKED reason=missing_gate2_hardware_acknowledgements" >&2
  exit 2
fi
if [[ -z "${source_archive}" || ! -f "${source_archive}" ]]; then
  echo "result=BLOCKED reason=frozen_source_archive_missing" >&2
  exit 2
fi
actual_archive_sha256="$(sha256sum "${source_archive}" | awk '{print $1}')"
if [[ "${actual_archive_sha256}" != "${expected_archive_sha256}" ]]; then
  echo "result=BLOCKED reason=frozen_source_archive_hash_mismatch" >&2
  exit 2
fi
if [[ -z "${config_path}" || ! -f "${config_path}" ]]; then
  echo "result=BLOCKED reason=frozen_config_missing" >&2
  exit 2
fi
config_path="$(realpath "${config_path}")"
actual_config_sha256="$(sha256sum "${config_path}" | awk '{print $1}')"
if [[ "${actual_config_sha256}" != "${expected_config_sha256}" ]]; then
  echo "result=BLOCKED reason=frozen_config_hash_mismatch" >&2
  exit 2
fi
if [[ -z "${output_dir}" ]]; then
  echo "result=BLOCKED reason=output_dir_required" >&2
  exit 2
fi
output_dir="$(realpath -m "${output_dir}")"
if [[ -e "${output_dir}" ]]; then
  echo "result=BLOCKED reason=refuse_existing_output_dir path=${output_dir}" >&2
  exit 2
fi
if [[ ! -c "${device}" ]]; then
  echo "result=BLOCKED reason=serial_device_missing device=${device}" >&2
  exit 2
fi
if command -v fuser >/dev/null 2>&1 && fuser "${device}" >/dev/null 2>&1; then
  echo "result=BLOCKED reason=serial_device_owned device=${device}" >&2
  exit 2
fi
if [[ "$(tr -d '[:space:]' < /sys/devices/system/cpu/isolated)" != "7" ]]; then
  echo "result=BLOCKED reason=cpu7_not_exact_isolated_cpu" >&2
  exit 2
fi
for name in scaling_governor scaling_available_governors scaling_min_freq \
  scaling_max_freq related_cpus; do
  if [[ ! -r "${policy}/${name}" ]]; then
    echo "result=BLOCKED reason=cpufreq_field_missing field=${name}" >&2
    exit 2
  fi
done
governor_original="$(tr -d '[:space:]' < "${policy}/scaling_governor")"
if [[ "${governor_original}" != "schedutil" ]]; then
  echo "result=BLOCKED reason=unexpected_initial_governor value=${governor_original}" >&2
  exit 2
fi
if ! grep -qw performance "${policy}/scaling_available_governors"; then
  echo "result=BLOCKED reason=performance_governor_unavailable" >&2
  exit 2
fi
if [[ "$(xargs < "${policy}/related_cpus")" != "0 1 2 3 4 5 6 7" ]]; then
  echo "result=BLOCKED reason=unexpected_cpufreq_policy_membership" >&2
  exit 2
fi
if [[ "$(tr -d '[:space:]' < "${policy}/scaling_min_freq")" != "300000" || \
      "$(tr -d '[:space:]' < "${policy}/scaling_max_freq")" != "1500000" ]]; then
  echo "result=BLOCKED reason=unexpected_cpufreq_range" >&2
  exit 2
fi

mkdir -p "${output_dir}/preflight" "${output_dir}/home_hold"
work_dir="$(mktemp -d /tmp/open-duck-gate2.XXXXXX)"

restore_governor() {
  if [[ "${governor_changed}" -eq 1 ]]; then
    printf '%s\n' "${governor_original}" > "${policy}/scaling_governor" || return 1
    if [[ "$(tr -d '[:space:]' < "${policy}/scaling_governor")" != \
          "${governor_original}" ]]; then
      return 1
    fi
    governor_changed=0
  fi
}

cleanup() {
  local cleanup_status=0
  if [[ -n "${active_probe_pid}" ]] && kill -0 "${active_probe_pid}" 2>/dev/null; then
    kill -TERM "${active_probe_pid}" 2>/dev/null || true
    wait "${active_probe_pid}" 2>/dev/null || true
    active_probe_pid=""
  fi
  restore_governor || cleanup_status=1
  if [[ -n "${work_dir}" && -d "${work_dir}" ]]; then
    case "${work_dir}" in
      /tmp/open-duck-gate2.*)
        rm -rf -- "${work_dir}"
        ;;
      *)
        echo "result=HALTED reason=unsafe_work_dir path=${work_dir}" >&2
        cleanup_status=1
        ;;
    esac
    work_dir=""
  fi
  return "${cleanup_status}"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

tar -xzf "${source_archive}" -C "${work_dir}"
printf '%s\n' "${expected_source_commit}" > "${output_dir}/source-commit.txt"
printf '%s  %s\n' "${actual_archive_sha256}" "${source_archive}" \
  > "${output_dir}/source-archive-sha256.txt"
printf '%s  %s\n' "${actual_config_sha256}" "${config_path}" \
  > "${output_dir}/config-sha256.txt"
cp "${policy}/scaling_governor" "${output_dir}/governor-before.txt"
cp "${policy}/scaling_min_freq" "${output_dir}/min-frequency-before.txt"
cp "${policy}/scaling_max_freq" "${output_dir}/max-frequency-before.txt"
cp "${policy}/related_cpus" "${output_dir}/related-cpus.txt"

printf '%s\n' performance > "${policy}/scaling_governor"
governor_changed=1
if [[ "$(tr -d '[:space:]' < "${policy}/scaling_governor")" != "performance" ]]; then
  echo "result=BLOCKED reason=performance_governor_verification_failed" >&2
  exit 2
fi
cp "${policy}/scaling_governor" "${output_dir}/governor-during.txt"

run_probe_stage() {
  local stage="$1"
  local moving="$2"
  local stage_dir="${output_dir}/${stage}"
  local -a probe_command=(
    taskset -c 0-7
    env "PYTHONPATH=${work_dir}/src"
    python3 -m open_duck_x5.probe
    --bus serial
    --device "${device}"
    --baudrate 1000000
    --timeout-ms 4
    --ticks "${ticks}"
    --frequency-hz 50
    --sine-hz 0.5
    --sine-joint left_hip_yaw
    --amplitude-rad 0
    --config "${config_path}"
    --home-seconds "${home_seconds}"
    --watchdog-failures 2
    --require-realtime
    --rt-cpu 7
    --rt-priority 80
    --hardware-authorized
    --suspended-or-benched
    --output "${stage_dir}/timing.jsonl"
    --summary "${stage_dir}/summary.json"
  )
  if [[ "${moving}" -eq 1 ]]; then
    probe_command+=(--enable-torque --moving-gate-authorized)
  fi
  (cd "${work_dir}" && exec "${probe_command[@]}") \
    > "${stage_dir}/probe-stdout.txt" \
    2> "${stage_dir}/probe-stderr.txt" &
  active_probe_pid=$!
  set +e
  wait "${active_probe_pid}"
  local status=$?
  set -e
  active_probe_pid=""
  return "${status}"
}

validate_stage() {
  local stage="$1"
  local moving="$2"
  local stage_name="preflight"
  if [[ "${moving}" -eq 1 ]]; then
    stage_name="home_hold"
  fi
  PYTHONPATH="${runner_root}/src" python3 -m open_duck_x5.gate2_validation \
    --summary "${output_dir}/${stage}/summary.json" \
    --stage "${stage_name}" \
    --expected-config-sha256 "${expected_config_sha256}"
}

write_metadata() {
  python3 - "${output_dir}/metadata.json" \
    "${expected_source_commit}" "${actual_archive_sha256}" \
    "${actual_config_sha256}" "${preflight_probe_status}" \
    "${preflight_validation_status}" "${home_probe_status}" \
    "${home_validation_status}" "${restore_status}" <<'PY'
import json
import sys
from pathlib import Path

(
    output,
    commit,
    archive_sha,
    config_sha,
    preflight_probe,
    preflight_validation,
    home_probe,
    home_validation,
    restore,
) = sys.argv[1:]
payload = {
    "schema_version": "open_duck_x5.gate2_home_hold_runner.v1",
    "source_commit": commit,
    "source_archive_sha256": archive_sha,
    "config_sha256": config_sha,
    "serial_device": "/dev/ttyS1",
    "preflight_ticks_requested": 10_000,
    "home_hold_ticks_requested": 10_000,
    "home_seconds": 5.0,
    "amplitude_rad": 0.0,
    "policy_loaded": False,
    "preflight_torque_enable_requested": False,
    "home_hold_torque_enable_requested": True,
    "preflight_probe_status": int(preflight_probe),
    "preflight_validation_status": int(preflight_validation),
    "home_hold_probe_status": int(home_probe),
    "home_hold_validation_status": int(home_validation),
    "governor_restore_status": int(restore),
}
Path(output).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
PY
}

finish_evidence() {
  restore_status=0
  restore_governor || restore_status=1
  cat "${policy}/scaling_governor" > "${output_dir}/governor-after.txt"
  write_metadata
  (
    cd "${output_dir}"
    find . -type f ! -name sha256sums.txt -print0 \
      | sort -z \
      | xargs -0 sha256sum
  ) > "${output_dir}/sha256sums.txt"
  if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
    chown -R "${SUDO_USER}:$(id -gn "${SUDO_USER}")" "${output_dir}"
  fi
}

set +e
run_probe_stage preflight 0
preflight_probe_status=$?
set -e
if [[ "${preflight_probe_status}" -eq 0 ]]; then
  set +e
  validate_stage preflight 0
  preflight_validation_status=$?
  set -e
else
  preflight_validation_status=1
fi
if [[ "${preflight_probe_status}" -ne 0 || \
      "${preflight_validation_status}" -ne 0 ]]; then
  finish_evidence
  echo "result=HALTED stage=torque_off_preflight"
  echo "preflight_probe_status=${preflight_probe_status}"
  echo "preflight_validation_status=${preflight_validation_status}"
  echo "governor_restore_status=${restore_status}"
  echo "output_dir=${output_dir}"
  exit 3
fi

if [[ "$(tr -d '[:space:]' < "${policy}/scaling_governor")" != "performance" ]]; then
  echo "result=HALTED reason=performance_governor_lost_before_home_hold" >&2
  finish_evidence
  exit 3
fi
if command -v fuser >/dev/null 2>&1 && fuser "${device}" >/dev/null 2>&1; then
  echo "result=HALTED reason=serial_device_owned_before_home_hold" >&2
  finish_evidence
  exit 3
fi

set +e
run_probe_stage home_hold 1
home_probe_status=$?
set -e
if [[ "${home_probe_status}" -eq 0 ]]; then
  set +e
  validate_stage home_hold 1
  home_validation_status=$?
  set -e
else
  home_validation_status=1
fi

finish_evidence
final_status=0
if [[ "${home_probe_status}" -ne 0 || "${home_validation_status}" -ne 0 || \
      "${restore_status}" -ne 0 ]]; then
  final_status=3
fi
echo "result=$([[ "${final_status}" -eq 0 ]] && echo REVIEW_CANDIDATE || echo HALTED)"
echo "preflight_probe_status=${preflight_probe_status}"
echo "preflight_validation_status=${preflight_validation_status}"
echo "home_hold_probe_status=${home_probe_status}"
echo "home_hold_validation_status=${home_validation_status}"
echo "governor_restore_status=${restore_status}"
echo "output_dir=${output_dir}"
exit "${final_status}"
