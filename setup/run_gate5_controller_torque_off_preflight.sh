#!/usr/bin/env bash
set -euo pipefail

readonly expected_source_tree="e570eaa42eb482ed58d3eb3d3a97bb22f86d14f9"
readonly expected_schema_tree="7674ece93c836eb0f9ff2ae2c3bc6203b032a5c3"
readonly expected_pyproject_blob="8bd71d3a44276bdb21755d1492a19c57f6c80fe0"
readonly expected_preregistration_sha256="c60381c51dd0921cff39a38ec4465b579ef1fc1a02b66704b0498661b4c299f9"
readonly expected_controller_pass_sha256="d04e98ffb2eca648cc7ddaa67a00c671a6816b240345794ca72d9073bb717d7f"
readonly expected_controller_mac="0C:35:26:2A:B8:0B"
readonly expected_controller_uniq="0c:35:26:2a:b8:0b"
readonly expected_controller_modalias="usb:v045Ep0B13d0515"
readonly controller_device="/dev/input/js0"
readonly controller_uniq_path="/sys/class/input/js0/device/uniq"
readonly device="/dev/ttyS1"
readonly ticks="10000"
readonly governor_policy="/sys/devices/system/cpu/cpufreq/policy0"
readonly venv_python="/home/sunrise/duck_env/bin/python"
readonly runner_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

source_root=""
output_dir=""
hardware_authorized=0
suspended_or_benched=0
probe_pid=""
governor_original=""
governor_changed=0

usage() {
  cat <<'EOF'
Usage: sudo setup/run_gate5_controller_torque_off_preflight.sh \
  --source-root /home/sunrise/open-duck-x5-controller-preflight \
  --output-dir /home/sunrise/duck-evidence/gate5-controller-torque-off-YYYYMMDD \
  --hardware-authorized --suspended-or-benched

Runs exactly one 10,000-tick controller-present serial probe on /dev/ttyS1.
Torque remains disabled, target amplitude is zero, no policy is loaded, and no
motion path exists. The accepted Xbox sysfs identity is frozen in this script.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source-root) source_root="$2"; shift 2 ;;
    --output-dir) output_dir="$2"; shift 2 ;;
    --hardware-authorized) hardware_authorized=1; shift ;;
    --suspended-or-benched) suspended_or_benched=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "result=BLOCKED reason=unknown_argument argument=$1" >&2; exit 2 ;;
  esac
done

sha256_of() { sha256sum "$1" | awk '{print $1}'; }

require_hash() {
  local path="$1" expected="$2" label="$3"
  if [[ ! -f "$path" ]]; then
    echo "result=BLOCKED reason=${label}_missing path=${path}" >&2
    exit 2
  fi
  local actual
  actual="$(sha256_of "$path")"
  if [[ "$actual" != "$expected" ]]; then
    echo "result=BLOCKED reason=${label}_hash_mismatch actual=${actual}" >&2
    exit 2
  fi
}

if [[ "$EUID" -ne 0 ]]; then
  echo "result=BLOCKED reason=root_required" >&2
  exit 2
fi
if [[ "$hardware_authorized" -ne 1 || "$suspended_or_benched" -ne 1 ]]; then
  echo "result=BLOCKED reason=missing_hardware_acknowledgements" >&2
  exit 2
fi
if [[ -z "$source_root" || ! -d "$source_root" ]]; then
  echo "result=BLOCKED reason=source_root_missing" >&2
  exit 2
fi
source_root="$(realpath "$source_root")"
if [[ "$source_root" != "$runner_root" ]]; then
  echo "result=BLOCKED reason=launcher_must_run_from_frozen_source_root" >&2
  exit 2
fi
if [[ -n "$(git -C "$source_root" status --porcelain --untracked-files=no)" ]]; then
  echo "result=BLOCKED reason=tracked_source_worktree_dirty" >&2
  exit 2
fi
if [[ "$(git -C "$source_root" rev-parse HEAD:src/open_duck_x5)" != "$expected_source_tree" || \
      "$(git -C "$source_root" rev-parse HEAD:schemas)" != "$expected_schema_tree" || \
      "$(git -C "$source_root" rev-parse HEAD:pyproject.toml)" != "$expected_pyproject_blob" ]]; then
  echo "result=BLOCKED reason=frozen_source_tree_mismatch" >&2
  exit 2
fi
require_hash \
  "$source_root/artifacts/gates/phase_7_hardware/gate_5_policy/T247_CONTROLLER_PRESENT_TORQUE_OFF_PREREGISTRATION_20260802.json" \
  "$expected_preregistration_sha256" "preregistration"
require_hash \
  "$source_root/artifacts/gates/phase_7_hardware/gate_5_policy/T247_CONTROLLER_DIRECT_10000_PASS_20260802.json" \
  "$expected_controller_pass_sha256" "controller_direct_pass"

if [[ -z "$output_dir" ]]; then
  echo "result=BLOCKED reason=output_dir_required" >&2
  exit 2
fi
output_dir="$(realpath -m "$output_dir")"
if [[ -e "$output_dir" ]]; then
  echo "result=BLOCKED reason=refuse_existing_output_dir" >&2
  exit 2
fi
if [[ ! -c "$device" ]]; then
  echo "result=BLOCKED reason=serial_device_missing" >&2
  exit 2
fi
if command -v fuser >/dev/null 2>&1 && fuser "$device" >/dev/null 2>&1; then
  echo "result=BLOCKED reason=serial_device_owned" >&2
  exit 2
fi
if [[ ! -c "$controller_device" || ! -r "$controller_uniq_path" ]]; then
  echo "result=BLOCKED reason=controller_device_missing" >&2
  exit 2
fi
controller_uniq="$(tr '[:upper:]' '[:lower:]' < "$controller_uniq_path" | tr -d '[:space:]')"
if [[ "$controller_uniq" != "$expected_controller_uniq" ]]; then
  echo "result=BLOCKED reason=wrong_controller_identity actual=${controller_uniq}" >&2
  exit 2
fi
controller_info="$(bluetoothctl info "$expected_controller_mac")"
for required in "Paired: yes" "Trusted: yes" "Connected: yes" "Modalias: ${expected_controller_modalias}"; do
  if ! grep -Fq "$required" <<<"$controller_info"; then
    echo "result=BLOCKED reason=controller_bluetooth_state detail=${required// /_}" >&2
    exit 2
  fi
done
if [[ ! -x "$venv_python" ]]; then
  echo "result=BLOCKED reason=venv_python_missing" >&2
  exit 2
fi
if [[ "$(tr -d '[:space:]' < /sys/devices/system/cpu/isolated)" != "7" ]]; then
  echo "result=BLOCKED reason=cpu7_not_exact_isolated_cpu" >&2
  exit 2
fi
for field in scaling_governor scaling_available_governors scaling_min_freq scaling_max_freq related_cpus; do
  [[ -r "$governor_policy/$field" ]] || { echo "result=BLOCKED reason=cpufreq_field_missing field=$field" >&2; exit 2; }
done
governor_original="$(tr -d '[:space:]' < "$governor_policy/scaling_governor")"
if [[ "$governor_original" != "schedutil" ]]; then
  echo "result=BLOCKED reason=unexpected_initial_governor value=${governor_original}" >&2
  exit 2
fi
grep -qw performance "$governor_policy/scaling_available_governors" || { echo "result=BLOCKED reason=performance_governor_unavailable" >&2; exit 2; }

restore_governor() {
  if [[ "$governor_changed" -eq 1 ]]; then
    printf '%s\n' "$governor_original" > "$governor_policy/scaling_governor"
    [[ "$(tr -d '[:space:]' < "$governor_policy/scaling_governor")" == "$governor_original" ]]
    governor_changed=0
  fi
}

cleanup() {
  local status=0
  if [[ -n "$probe_pid" ]] && kill -0 "$probe_pid" 2>/dev/null; then
    kill -TERM "$probe_pid" 2>/dev/null || true
    wait "$probe_pid" 2>/dev/null || true
    probe_pid=""
  fi
  restore_governor || status=1
  return "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

mkdir -p "$output_dir"
printf '%s\n' "$(git -C "$source_root" rev-parse HEAD)" > "$output_dir/source-commit.txt"
printf '%s\n' "$controller_info" > "$output_dir/controller-before.txt"
printf '%s\n' "$controller_uniq" > "$output_dir/controller-uniq-before.txt"
cp "$governor_policy/scaling_governor" "$output_dir/governor-before.txt"
printf '%s\n' performance > "$governor_policy/scaling_governor"
governor_changed=1
[[ "$(tr -d '[:space:]' < "$governor_policy/scaling_governor")" == "performance" ]] || { echo "result=BLOCKED reason=performance_governor_verification_failed" >&2; exit 2; }
cp "$governor_policy/scaling_governor" "$output_dir/governor-during.txt"

probe_command=(
  taskset -c 0-7 env "PYTHONPATH=$source_root/src" "$venv_python"
  -m open_duck_x5.probe
  --bus serial --device "$device" --baudrate 1000000 --timeout-ms 4
  --ticks "$ticks" --frequency-hz 50 --amplitude-rad 0
  --watchdog-failures 2 --require-realtime --rt-cpu 7 --rt-priority 80
  --controller xbox
  --instrument-transactions --instrumentation-output "$output_dir/transaction-trace.jsonl"
  --hardware-authorized --suspended-or-benched
  --output "$output_dir/timing.jsonl" --summary "$output_dir/summary.json"
)

(cd "$source_root" && exec "${probe_command[@]}") > "$output_dir/probe-stdout.txt" 2> "$output_dir/probe-stderr.txt" &
probe_pid=$!
set +e
wait "$probe_pid"
probe_status=$?
set -e
probe_pid=""

restore_status=0
restore_governor || restore_status=1
cat "$governor_policy/scaling_governor" > "$output_dir/governor-after.txt"
bluetoothctl info "$expected_controller_mac" > "$output_dir/controller-after.txt" 2>&1 || true
if [[ -r "$controller_uniq_path" ]]; then
  tr '[:upper:]' '[:lower:]' < "$controller_uniq_path" | tr -d '[:space:]' > "$output_dir/controller-uniq-after.txt"
else
  printf 'missing\n' > "$output_dir/controller-uniq-after.txt"
fi

validation_status=1
if [[ "$probe_status" -eq 0 && "$restore_status" -eq 0 ]]; then
  set +e
  "$venv_python" - "$output_dir/summary.json" "$output_dir/transaction-trace.jsonl" "$output_dir/validation.json" "$expected_controller_uniq" "$output_dir/controller-uniq-after.txt" <<'PY'
import json
import sys
from pathlib import Path

summary_path = Path(sys.argv[1])
trace_path = Path(sys.argv[2])
output_path = Path(sys.argv[3])
expected_uniq = sys.argv[4]
uniq_after_path = Path(sys.argv[5])
summary = json.loads(summary_path.read_text(encoding="utf-8"))
environment = summary["environment"]
realtime = environment["realtime"]
gates = summary["gates"]
late_markers = 0
trace_rows = 0
deadline_ns = 4_000_000
with trace_path.open(encoding="utf-8") as handle:
    for line in handle:
        row = json.loads(line)
        trace_rows += 1
        stamps = row["timestamps_ns"]
        group_deadline = stamps["group_write_end_ns"] + deadline_ns
        late_markers += sum(
            int(value >= group_deadline)
            for value in row["group_response_complete_ns_logical_order"]
            if value > 0
        )
        extended_last = stamps["extended_last_rx_ns"]
        if extended_last > 0:
            late_markers += int(
                extended_last >= stamps["extended_write_end_ns"] + deadline_ns
            )

uniq_after = uniq_after_path.read_text(encoding="utf-8").strip()
checks = {
    "run_complete": summary["run_status"] == "COMPLETE" and summary["halt_reason"] is None,
    "ticks_complete": summary["ticks"] == summary["ticks_requested"] == 10_000,
    "tick_p99": summary["tick_period_ms"]["p99"] <= 21.0,
    "tick_p99_9": summary["tick_period_ms"]["p99_9"] <= 22.0,
    "bus_max": summary["bus_total_ms"]["max"] < 5.0,
    "zero_bursts": summary["read_burst_count"] == 0,
    "failure_rate": summary["transaction_failure_rate"] < 0.001,
    "late_response_markers": late_markers == 0,
    "trace_complete": trace_rows == 10_000,
    "controller_backend": environment["controller"] == "xbox"
    and environment["controller_backend"] == "LinuxJoystickController",
    "controller_identity": uniq_after == expected_uniq,
    "torque_disabled": environment["torque_enabled"] is False,
    "torque_off": environment["torque_off_status"] == "ok" and gates["torque_off_confirmed"],
    "authorization": environment["hardware_authorized"] is True
    and environment["suspended_or_benched"] is True
    and environment["moving_gate_authorized"] is False,
    "zero_amplitude": environment["amplitude_rad"] == 0.0,
    "realtime": realtime["cpu"] == 7
    and realtime["affinity"] == [7]
    and realtime["scheduler"] == "SCHED_FIFO"
    and realtime["priority"] >= 80
    and realtime["isolated"] is True,
    "summary_gates": gates["complete_record_stream"]
    and gates["tick_p99_at_most_21_ms"]
    and gates["tick_p99_9_at_most_22_ms"]
    and gates["bus_max_under_5_ms"]
    and gates["zero_read_bursts"]
    and gates["transaction_failure_below_0_1_percent"],
}
payload = {
    "schema_version": "open_duck_x5.t247_controller_torque_off_validation.v1",
    "status": "PASS" if all(checks.values()) else "FAIL",
    "checks": checks,
    "late_accepted_response_markers": late_markers,
    "transaction_trace_rows": trace_rows,
    "controller_uniq_after": uniq_after,
}
output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
if not all(checks.values()):
    raise SystemExit(3)
PY
  validation_status=$?
  set -e
fi

serial_released=true
if command -v fuser >/dev/null 2>&1 && fuser "$device" >/dev/null 2>&1; then serial_released=false; fi
"$venv_python" - "$output_dir/metadata.json" "$probe_status" "$restore_status" "$validation_status" "$serial_released" <<'PY'
import json
import sys
from pathlib import Path

output, probe, restore, validation, serial_released = sys.argv[1:]
payload = {
    "schema_version": "open_duck_x5.t247_controller_torque_off_run.v1",
    "probe_exit_status": int(probe),
    "governor_restore_status": int(restore),
    "validation_status": int(validation),
    "serial_released": serial_released == "true",
    "torque_enable_requested": False,
    "motion": False,
    "policy_loaded": False,
}
Path(output).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

find "$output_dir" -maxdepth 1 -type f ! -name sha256sums.txt -print0 | sort -z | xargs -0 sha256sum > "$output_dir/sha256sums.txt"
if [[ -n "${SUDO_USER:-}" && "$SUDO_USER" != "root" ]]; then
  chown -R "$SUDO_USER:$(id -gn "$SUDO_USER")" "$output_dir"
fi

final_status="$probe_status"
if [[ "$restore_status" -ne 0 || "$validation_status" -ne 0 || "$serial_released" != true ]]; then final_status=3; fi
echo "result=$([[ "$final_status" -eq 0 ]] && echo COMPLETE || echo HALTED)"
echo "probe_exit_status=$probe_status"
echo "governor_restore_status=$restore_status"
echo "validation_status=$validation_status"
echo "serial_released=$serial_released"
echo "output_dir=$output_dir"
exit "$final_status"
