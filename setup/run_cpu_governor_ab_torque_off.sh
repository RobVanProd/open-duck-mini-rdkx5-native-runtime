#!/usr/bin/env bash
set -euo pipefail

readonly expected_source_commit="8c73aae2110f10a294e1dcf333c41bfc9d2f3a88"
readonly expected_archive_sha256="a90070d00e8f0eca704005aa241c36e7ab4aa782ca7f8af41253d3d4be41de77"
readonly device="/dev/ttyS1"
readonly ticks="10000"
readonly policy="/sys/devices/system/cpu/cpufreq/policy0"

output_dir=""
source_archive=""
hardware_authorized=0
suspended_or_benched=0
probe_pid=""
work_dir=""
governor_original=""
governor_changed=0

usage() {
  cat <<'EOF'
Usage: sudo setup/run_cpu_governor_ab_torque_off.sh \
  --source-archive /home/sunrise/open-duck-x5-8c73aae-trace-analysis.tar.gz \
  --output-dir /home/sunrise/duck-evidence/cpu-governor-ab-8c73aae \
  --hardware-authorized --suspended-or-benched

Runs only the preregistered 10,000-tick, torque-off CPU-governor arm B on
/dev/ttyS1. The source archive and source commit are frozen in this script.
There is no torque-enable, motion, config, or policy option. The original CPU
governor is restored on normal exit, signal, probe failure, or validation error.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source-archive)
      source_archive="$2"
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
if [[ "${hardware_authorized}" -ne 1 || "${suspended_or_benched}" -ne 1 ]]; then
  echo "result=BLOCKED reason=missing_hardware_acknowledgements" >&2
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

mkdir -p "${output_dir}"
work_dir="$(mktemp -d /tmp/open-duck-governor-ab.XXXXXX)"

restore_governor() {
  if [[ "${governor_changed}" -eq 1 ]]; then
    printf '%s\n' "${governor_original}" > "${policy}/scaling_governor" || return 1
    if [[ "$(tr -d '[:space:]' < "${policy}/scaling_governor")" != "${governor_original}" ]]; then
      return 1
    fi
    governor_changed=0
  fi
}

cleanup() {
  local cleanup_status=0
  if [[ -n "${probe_pid}" ]] && kill -0 "${probe_pid}" 2>/dev/null; then
    kill -TERM "${probe_pid}" 2>/dev/null || true
    wait "${probe_pid}" 2>/dev/null || true
    probe_pid=""
  fi
  restore_governor || cleanup_status=1
  if [[ -n "${work_dir}" && -d "${work_dir}" ]]; then
    rm -rf -- "${work_dir}"
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

probe_command=(
  taskset -c 0-7
  env "PYTHONPATH=${work_dir}/src"
  python3 -m open_duck_x5.probe
  --bus serial
  --device "${device}"
  --baudrate 1000000
  --timeout-ms 4
  --ticks "${ticks}"
  --frequency-hz 50
  --amplitude-rad 0
  --watchdog-failures 2
  --require-realtime
  --rt-cpu 7
  --rt-priority 80
  --instrument-transactions
  --instrumentation-output "${output_dir}/transaction-trace.jsonl"
  --hardware-authorized
  --suspended-or-benched
  --output "${output_dir}/timing.jsonl"
  --summary "${output_dir}/summary.json"
)

(cd "${work_dir}" && exec "${probe_command[@]}") \
  > "${output_dir}/probe-stdout.txt" \
  2> "${output_dir}/probe-stderr.txt" &
probe_pid=$!
set +e
wait "${probe_pid}"
probe_status=$?
set -e
probe_pid=""

restore_status=0
restore_governor || restore_status=1
cat "${policy}/scaling_governor" > "${output_dir}/governor-after.txt"

validation_status=0
if [[ "${probe_status}" -eq 0 && "${restore_status}" -eq 0 ]]; then
  python3 - "${output_dir}/summary.json" <<'PY' || validation_status=$?
import json
import sys
from pathlib import Path

summary = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
environment = summary["environment"]
realtime = environment["realtime"]
checks = {
    "run complete": summary["run_status"] == "COMPLETE",
    "10,000 ticks": summary["ticks"] == summary["ticks_requested"] == 10_000,
    "torque disabled": environment["torque_enabled"] is False,
    "final torque off": environment["torque_off_status"] == "ok",
    "hardware authorized": environment["hardware_authorized"] is True,
    "supported": environment["suspended_or_benched"] is True,
    "no moving authorization": environment["moving_gate_authorized"] is False,
    "zero amplitude": environment["amplitude_rad"] == 0.0,
    "UART endpoint": environment["device"] == "/dev/ttyS1",
    "one megabaud": environment["baudrate"] == 1_000_000,
    "50 Hz": environment["frequency_hz"] == 50.0,
    "RT CPU": realtime["cpu"] == 7 and realtime["affinity"] == [7],
    "RT scheduler": realtime["scheduler"] == "SCHED_FIFO"
    and realtime["priority"] >= 80,
    "isolated": realtime["isolated"] is True,
    "initial affinity": realtime["initial_affinity"] == list(range(8)),
    "housekeeping": realtime["housekeeping_affinity"] == list(range(7)),
    "zero drops": environment["telemetry_records_dropped"] == 0,
}
failed = [name for name, passed in checks.items() if not passed]
if failed:
    raise SystemExit("summary validation failed: " + ", ".join(failed))
PY
else
  validation_status=1
fi

python3 - "${output_dir}/metadata.json" \
  "${expected_source_commit}" "${actual_archive_sha256}" "${probe_status}" \
  "${restore_status}" "${validation_status}" <<'PY'
import json
import sys
from pathlib import Path

output, commit, archive_sha, probe, restore, validation = sys.argv[1:]
payload = {
    "schema_version": "open_duck_x5.cpu_governor_ab.v1",
    "source_commit": commit,
    "source_archive_sha256": archive_sha,
    "arm": "B_performance",
    "matched_arm_a": "sync_read_collector_ab/RESULT.md",
    "serial_device": "/dev/ttyS1",
    "ticks_requested": 10_000,
    "torque_enable_requested": False,
    "moving_gate_authorized": False,
    "policy_or_config_loaded": False,
    "probe_exit_status": int(probe),
    "governor_restore_status": int(restore),
    "summary_validation_status": int(validation),
}
Path(output).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
PY

sha256sum "${output_dir}"/* > "${output_dir}/sha256sums.txt"
if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
  chown -R "${SUDO_USER}:$(id -gn "${SUDO_USER}")" "${output_dir}"
fi

final_status="${probe_status}"
if [[ "${restore_status}" -ne 0 || "${validation_status}" -ne 0 ]]; then
  final_status=3
fi
echo "result=$([[ "${final_status}" -eq 0 ]] && echo COMPLETE || echo HALTED)"
echo "probe_exit_status=${probe_status}"
echo "governor_restore_status=${restore_status}"
echo "summary_validation_status=${validation_status}"
echo "output_dir=${output_dir}"
exit "${final_status}"
