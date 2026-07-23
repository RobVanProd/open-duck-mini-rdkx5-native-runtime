#!/usr/bin/env bash
set -euo pipefail

readonly expected_source_commit="de870de8cde29a3e645c73c6f6cdeaa48cd8ea46"
readonly expected_archive_sha256="9caefc209dfb85bd1ca28d998e37bcf0832c361468cec0d8d46c97cf6d7c9c17"
readonly expected_config_sha256="131a7b8fce1107b14f4727562f44f9e17324caf7fc22512ad7115911f050991b"
readonly expected_imu_calibration_sha256="e7518b0df8614c1d399c789fd26aa9888043ebacfccc98ef75a5010a4b8c34be"
readonly expected_policy_envelope_sha256="PENDING_POLICY_ENVELOPE_SHA256"
readonly device="/dev/ttyS1"
readonly policy="/sys/devices/system/cpu/cpufreq/policy0"
readonly runner_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

source_archive=""
config_path=""
imu_calibration_path=""
policy_envelope_path=""
output_dir=""
hardware_authorized=0
suspended_or_benched=0
moving_gate_authorized=0
configuration_calibration_authorized=0
active_process_pid=""
work_dir=""
governor_original=""
governor_changed=0
restore_status=-1
preflight_probe_status=-1
preflight_validation_status=-1
collector_status=-1
support_validation_status=-1

usage() {
  cat <<'EOF'
Usage: sudo setup/run_automatic_configuration.sh \
  --source-archive /home/sunrise/open-duck-x5-auto-config-<commit>.tar.gz \
  --config /home/sunrise/duck_config.json \
  --imu-calibration /home/sunrise/imu_calibration.json \
  --policy-envelope /home/sunrise/policy-supported-envelope.json \
  --output-dir /home/sunrise/duck-evidence/automatic-configuration-<date> \
  --hardware-authorized --suspended-or-benched \
  --moving-gate-authorized --configuration-calibration-authorized

This launcher is intentionally blocked while its policy-envelope SHA-256 is
the PENDING sentinel. Once that exact identity is frozen, it runs a 10,000-tick
torque-off preflight and only after an independent pass runs the fixed
2,814-tick no-policy automatic configuration excitation. Every exit path
signals an active child, relies on its redundant torque-off cleanup, and
restores the CPU governor.
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
    --imu-calibration)
      imu_calibration_path="$2"
      shift 2
      ;;
    --policy-envelope)
      policy_envelope_path="$2"
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
    --configuration-calibration-authorized)
      configuration_calibration_authorized=1
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

if [[ ! "${expected_policy_envelope_sha256}" =~ ^[0-9a-f]{64}$ ]]; then
  echo "result=BLOCKED reason=policy_envelope_identity_not_frozen" >&2
  exit 2
fi
if [[ "${EUID}" -ne 0 ]]; then
  echo "result=BLOCKED reason=root_required_for_governor_and_sched_fifo" >&2
  exit 2
fi
if [[ "${hardware_authorized}" -ne 1 || "${suspended_or_benched}" -ne 1 || \
      "${moving_gate_authorized}" -ne 1 || \
      "${configuration_calibration_authorized}" -ne 1 ]]; then
  echo "result=BLOCKED reason=missing_automatic_configuration_acknowledgements" >&2
  exit 2
fi

check_frozen_file() {
  local path="$1"
  local expected="$2"
  local label="$3"
  if [[ -z "${path}" || ! -f "${path}" ]]; then
    echo "result=BLOCKED reason=${label}_missing" >&2
    exit 2
  fi
  local actual
  actual="$(sha256sum "${path}" | awk '{print $1}')"
  if [[ "${actual}" != "${expected}" ]]; then
    echo "result=BLOCKED reason=${label}_hash_mismatch" >&2
    exit 2
  fi
}

check_frozen_file "${source_archive}" "${expected_archive_sha256}" "source_archive"
check_frozen_file "${config_path}" "${expected_config_sha256}" "config"
check_frozen_file \
  "${imu_calibration_path}" "${expected_imu_calibration_sha256}" "imu_calibration"
check_frozen_file \
  "${policy_envelope_path}" "${expected_policy_envelope_sha256}" "policy_envelope"

source_archive="$(realpath "${source_archive}")"
config_path="$(realpath "${config_path}")"
imu_calibration_path="$(realpath "${imu_calibration_path}")"
policy_envelope_path="$(realpath "${policy_envelope_path}")"
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

mkdir -p "${output_dir}/preflight" "${output_dir}/calibration"
work_dir="$(mktemp -d /tmp/open-duck-auto-config.XXXXXX)"

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
  if [[ -n "${active_process_pid}" ]] && kill -0 "${active_process_pid}" 2>/dev/null; then
    kill -TERM "${active_process_pid}" 2>/dev/null || true
    wait "${active_process_pid}" 2>/dev/null || true
    active_process_pid=""
  fi
  restore_governor || cleanup_status=1
  if [[ -n "${work_dir}" && -d "${work_dir}" ]]; then
    case "${work_dir}" in
      /tmp/open-duck-auto-config.*)
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
printf '%s  %s\n' "${expected_archive_sha256}" "${source_archive}" \
  > "${output_dir}/source-archive-sha256.txt"
printf '%s  %s\n' "${expected_config_sha256}" "${config_path}" \
  > "${output_dir}/config-sha256.txt"
printf '%s  %s\n' "${expected_imu_calibration_sha256}" "${imu_calibration_path}" \
  > "${output_dir}/imu-calibration-sha256.txt"
printf '%s  %s\n' "${expected_policy_envelope_sha256}" "${policy_envelope_path}" \
  > "${output_dir}/policy-envelope-sha256.txt"
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

run_preflight() {
  local -a command=(
    taskset -c 0-7
    env "PYTHONPATH=${work_dir}/src"
    python3 -m open_duck_x5.probe
    --bus serial
    --device "${device}"
    --baudrate 1000000
    --timeout-ms 4
    --ticks 10000
    --frequency-hz 50
    --amplitude-rad 0
    --config "${config_path}"
    --home-seconds 5
    --watchdog-failures 2
    --require-realtime
    --rt-cpu 7
    --rt-priority 80
    --hardware-authorized
    --suspended-or-benched
    --output "${output_dir}/preflight/timing.jsonl"
    --summary "${output_dir}/preflight/summary.json"
  )
  (cd "${work_dir}" && exec "${command[@]}") \
    > "${output_dir}/preflight/probe-stdout.txt" \
    2> "${output_dir}/preflight/probe-stderr.txt" &
  active_process_pid=$!
  set +e
  wait "${active_process_pid}"
  local status=$?
  set -e
  active_process_pid=""
  return "${status}"
}

validate_preflight() {
  PYTHONPATH="${work_dir}/src" python3 -m open_duck_x5.gate4_validation \
    --stage preflight \
    --timing "${output_dir}/preflight/timing.jsonl" \
    --summary "${output_dir}/preflight/summary.json" \
    --config "${config_path}" \
    --output "${output_dir}/preflight/validation.json"
}

run_collector() {
  local -a command=(
    taskset -c 0-7
    env "PYTHONPATH=${work_dir}/src"
    python3 -m open_duck_x5.configuration_collector
    --bus serial
    --device "${device}"
    --baudrate 1000000
    --timeout-ms 4
    --config "${config_path}"
    --imu-calibration "${imu_calibration_path}"
    --policy-envelope "${policy_envelope_path}"
    --i2c-bus 5
    --require-realtime
    --rt-cpu 7
    --rt-priority 80
    --hardware-authorized
    --suspended-or-benched
    --moving-gate-authorized
    --configuration-calibration-authorized
    --trace "${output_dir}/calibration/trace.jsonl"
    --metadata "${output_dir}/calibration/metadata.json"
    --profile "${output_dir}/calibration/profile.json"
  )
  (cd "${work_dir}" && exec "${command[@]}") \
    > "${output_dir}/calibration/collector-stdout.txt" \
    2> "${output_dir}/calibration/collector-stderr.txt" &
  active_process_pid=$!
  set +e
  wait "${active_process_pid}"
  local status=$?
  set -e
  active_process_pid=""
  return "${status}"
}

validate_support() {
  PYTHONPATH="${work_dir}/src" python3 -m open_duck_x5.configuration_support \
    --profile "${output_dir}/calibration/profile.json" \
    --envelope "${policy_envelope_path}" \
    --trace "${output_dir}/calibration/trace.jsonl" \
    --metadata "${output_dir}/calibration/metadata.json" \
    --configuration "${config_path}" \
    --output "${output_dir}/configuration-support-result.json"
}

write_runner_metadata() {
  python3 - "${output_dir}/runner-metadata.json" \
    "${expected_source_commit}" "${expected_archive_sha256}" \
    "${expected_config_sha256}" "${expected_imu_calibration_sha256}" \
    "${expected_policy_envelope_sha256}" "${preflight_probe_status}" \
    "${preflight_validation_status}" "${collector_status}" \
    "${support_validation_status}" "${restore_status}" <<'PY'
import json
import sys
from pathlib import Path

(
    output,
    source_commit,
    archive_sha,
    config_sha,
    imu_sha,
    envelope_sha,
    preflight_probe,
    preflight_validation,
    collector,
    support_validation,
    restore,
) = sys.argv[1:]
payload = {
    "schema_version": "open_duck_x5.automatic_configuration_runner.v1",
    "source_commit": source_commit,
    "source_archive_sha256": archive_sha,
    "config_sha256": config_sha,
    "imu_calibration_sha256": imu_sha,
    "policy_envelope_sha256": envelope_sha,
    "serial_device": "/dev/ttyS1",
    "preflight_ticks": 10_000,
    "calibration_ticks": 2_814,
    "home_seconds": 5.0,
    "policy_loaded": False,
    "preflight_torque_enable_requested": False,
    "calibration_motion_requested": True,
    "preflight_probe_status": int(preflight_probe),
    "preflight_validation_status": int(preflight_validation),
    "collector_status": int(collector),
    "support_validation_status": int(support_validation),
    "governor_restore_status": int(restore),
    "review_status": "REVIEW_REQUIRED",
    "robot_clearance": False,
    "gate5": False,
    "runtime_deployment": False,
}
Path(output).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
PY
}

finish_evidence() {
  restore_status=0
  restore_governor || restore_status=1
  cat "${policy}/scaling_governor" > "${output_dir}/governor-after.txt"
  write_runner_metadata
  (
    cd "${output_dir}"
    find . -type f ! -name sha256sums.txt -print0 | sort -z | xargs -0 sha256sum
  ) > "${output_dir}/sha256sums.txt"
  if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
    chown -R "${SUDO_USER}:$(id -gn "${SUDO_USER}")" "${output_dir}"
  fi
}

halt_stage() {
  local stage="$1"
  finish_evidence
  echo "result=HALTED stage=${stage}"
  echo "preflight_probe_status=${preflight_probe_status}"
  echo "preflight_validation_status=${preflight_validation_status}"
  echo "collector_status=${collector_status}"
  echo "support_validation_status=${support_validation_status}"
  echo "governor_restore_status=${restore_status}"
  echo "output_dir=${output_dir}"
  exit 3
}

set +e
run_preflight
preflight_probe_status=$?
set -e
if [[ "${preflight_probe_status}" -eq 0 ]]; then
  set +e
  validate_preflight
  preflight_validation_status=$?
  set -e
else
  preflight_validation_status=1
fi
if [[ "${preflight_probe_status}" -ne 0 || \
      "${preflight_validation_status}" -ne 0 ]]; then
  halt_stage torque_off_preflight
fi
if [[ "$(tr -d '[:space:]' < "${policy}/scaling_governor")" != "performance" ]]; then
  halt_stage performance_governor_lost
fi
if command -v fuser >/dev/null 2>&1 && fuser "${device}" >/dev/null 2>&1; then
  halt_stage serial_device_owned_before_calibration
fi

set +e
run_collector
collector_status=$?
set -e
if [[ "${collector_status}" -ne 0 ]]; then
  halt_stage automatic_configuration_collection
fi

set +e
validate_support
support_validation_status=$?
set -e
if [[ "${support_validation_status}" -ne 0 ]]; then
  halt_stage automatic_configuration_support
fi

finish_evidence
final_status=0
if [[ "${restore_status}" -ne 0 ]]; then
  final_status=3
fi
echo "result=$([[ "${final_status}" -eq 0 ]] && echo REVIEW_CANDIDATE || echo HALTED)"
echo "preflight_probe_status=${preflight_probe_status}"
echo "preflight_validation_status=${preflight_validation_status}"
echo "collector_status=${collector_status}"
echo "support_validation_status=${support_validation_status}"
echo "governor_restore_status=${restore_status}"
echo "output_dir=${output_dir}"
exit "${final_status}"
