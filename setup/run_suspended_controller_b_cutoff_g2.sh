#!/usr/bin/env bash
set -euo pipefail

readonly expected_source_commit="479cb4dce37ca85d6f0a4da4bf8322e7e14d4cb4"
readonly expected_source_tree="6bb064e1d15c27fb6af7301cf2fe9a6b4d7fb6d4"
readonly expected_schema_tree="55580397a2d01bd6f76417f57a92c4dddee7f642"
readonly expected_pyproject_blob="4d2b05b958aea152a16c88e094ff25fd78d31b55"
readonly expected_preregistration_sha256="414776d4792a859b27a75b7020577c5b370fc307f70a036032d250bf8f4dca83"
readonly expected_controller_review_sha256="e4fe7279b33c25a8334ff0dc8f067c9e0321b6710a39d0fc3f53016b5e3c0d13"
readonly expected_config_sha256="131a7b8fce1107b14f4727562f44f9e17324caf7fc22512ad7115911f050991b"
readonly expected_controller_mac="0C:35:26:2A:B8:0B"
readonly expected_controller_uniq="0c:35:26:2a:b8:0b"
readonly expected_controller_modalias="usb:v045Ep0B13d0515"
readonly device="/dev/ttyS1"
readonly controller_device="/dev/input/js0"
readonly controller_uniq_path="/sys/class/input/js0/device/uniq"
readonly preflight_ticks="10000"
readonly cutoff_ticks="3000"
readonly frequency_hz="50"
readonly home_seconds="5"
readonly governor_policy="/sys/devices/system/cpu/cpufreq/policy0"
readonly venv_python="/home/sunrise/duck_env/bin/python"
readonly runner_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

source_root=""
config_path=""
output_dir=""
hardware_authorized=0
suspended_or_benched=0
moving_gate_authorized=0
controller_cutoff_authorized=0
active_probe_pid=""
governor_original=""
governor_changed=0
motion_stage_started=0
readback_attempted=0
preflight_probe_status=-1
preflight_validation_status=-1
cutoff_probe_status=-1
cutoff_validation_status=-1
readback_status=-1
restore_status=-1

usage() {
  cat <<'EOF'
Usage: sudo setup/run_suspended_controller_b_cutoff_g2.sh \
  --source-root /home/sunrise/open-duck-mini-rdkx5-native-runtime \
  --config /home/sunrise/duck_config.json \
  --output-dir /home/sunrise/duck-evidence/suspended-controller-b-cutoff-g2-YYYYMMDD \
  --hardware-authorized --suspended-or-benched --moving-gate-authorized \
  --controller-cutoff-authorized

Runs exactly one frozen suspended G2 sequence. It first runs a 10,000-tick
controller-present torque-off preflight. Only if that passes, it moves to home
over five seconds with no policy, writes a durable HOME_HOLD_READY cue, and
waits for one B-button emergency stop. The expected B halt is followed by a
separate all-14 register-40 torque-off readback. There is no grounded or policy
path and no automatic follow-on.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source-root) source_root="$2"; shift 2 ;;
    --config) config_path="$2"; shift 2 ;;
    --output-dir) output_dir="$2"; shift 2 ;;
    --hardware-authorized) hardware_authorized=1; shift ;;
    --suspended-or-benched) suspended_or_benched=1; shift ;;
    --moving-gate-authorized) moving_gate_authorized=1; shift ;;
    --controller-cutoff-authorized) controller_cutoff_authorized=1; shift ;;
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

require_controller_state() {
  local output="$1"
  if [[ ! -c "$controller_device" || ! -r "$controller_uniq_path" ]]; then
    return 1
  fi
  local uniq info
  uniq="$(tr '[:upper:]' '[:lower:]' < "$controller_uniq_path" | tr -d '[:space:]')"
  [[ "$uniq" == "$expected_controller_uniq" ]] || return 1
  info="$(bluetoothctl info "$expected_controller_mac")" || return 1
  for required in "Paired: yes" "Trusted: yes" "Connected: yes" \
    "Modalias: ${expected_controller_modalias}"; do
    grep -Fq "$required" <<<"$info" || return 1
  done
  printf '%s\n' "$info" > "$output"
  printf '%s\n' "$uniq" > "${output%.txt}-uniq.txt"
}

restore_governor() {
  if [[ "$governor_changed" -eq 1 ]]; then
    printf '%s\n' "$governor_original" > "$governor_policy/scaling_governor" || return 1
    [[ "$(tr -d '[:space:]' < "$governor_policy/scaling_governor")" == \
      "$governor_original" ]] || return 1
    governor_changed=0
  fi
}

run_independent_readback() {
  local output="$output_dir/torque-off-readback.json"
  readback_attempted=1
  set +e
  (
    cd "$source_root"
    env "PYTHONPATH=$source_root/src" "$venv_python" \
      -m open_duck_x5.torque_off_readback \
      --bus serial --device "$device" --baudrate 1000000 --timeout-ms 4 \
      --repository-commit "$(git -C "$source_root" rev-parse HEAD)" \
      --output "$output" --hardware-authorized --suspended-or-benched
  ) > "$output_dir/readback-stdout.txt" 2> "$output_dir/readback-stderr.txt"
  readback_status=$?
  set -e
}

cleanup() {
  local cleanup_status=0
  set +e
  if [[ -n "$active_probe_pid" ]] && kill -0 "$active_probe_pid" 2>/dev/null; then
    kill -TERM "$active_probe_pid" 2>/dev/null
    wait "$active_probe_pid" 2>/dev/null
    active_probe_pid=""
  fi
  if [[ "$motion_stage_started" -eq 1 && "$readback_attempted" -eq 0 && \
        -n "$source_root" && -d "$source_root" && -n "$output_dir" && \
        -d "$output_dir" && -x "$venv_python" ]]; then
    run_independent_readback
    [[ "$readback_status" -eq 0 ]] || cleanup_status=1
  fi
  restore_governor || cleanup_status=1
  set -e
  return "$cleanup_status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if [[ "$EUID" -ne 0 ]]; then
  echo "result=BLOCKED reason=root_required_for_governor_and_sched_fifo" >&2
  exit 2
fi
if [[ "$hardware_authorized" -ne 1 || "$suspended_or_benched" -ne 1 || \
      "$moving_gate_authorized" -ne 1 || "$controller_cutoff_authorized" -ne 1 ]]; then
  echo "result=BLOCKED reason=missing_g2_hardware_acknowledgements" >&2
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
if [[ "$(git -C "$source_root" rev-parse HEAD:src/open_duck_x5)" != \
      "$expected_source_tree" || \
      "$(git -C "$source_root" rev-parse HEAD:schemas)" != "$expected_schema_tree" || \
      "$(git -C "$source_root" rev-parse HEAD:pyproject.toml)" != \
      "$expected_pyproject_blob" ]]; then
  echo "result=BLOCKED reason=frozen_g2_source_mismatch" >&2
  exit 2
fi
if ! git -C "$source_root" merge-base --is-ancestor "$expected_source_commit" HEAD; then
  echo "result=BLOCKED reason=g2_source_commit_not_ancestor" >&2
  exit 2
fi
require_hash \
  "$source_root/artifacts/gates/grounded_validation/SUSPENDED_CONTROLLER_B_CUTOFF_G2_PREREGISTRATION_20260802.json" \
  "$expected_preregistration_sha256" "g2_preregistration"
require_hash \
  "$source_root/artifacts/gates/grounded_validation/CONTROLLER_B_STOP_OPERATOR_RETURN_PASS_REVIEWED_20260802.json" \
  "$expected_controller_review_sha256" "controller_mapping_review"
if [[ -z "$config_path" || ! -f "$config_path" ]]; then
  echo "result=BLOCKED reason=config_missing" >&2
  exit 2
fi
config_path="$(realpath "$config_path")"
require_hash "$config_path" "$expected_config_sha256" "frozen_config"
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
if [[ ! -x "$venv_python" ]]; then
  echo "result=BLOCKED reason=venv_python_missing" >&2
  exit 2
fi
if [[ "$(tr -d '[:space:]' < /sys/devices/system/cpu/isolated)" != "7" ]]; then
  echo "result=BLOCKED reason=cpu7_not_exact_isolated_cpu" >&2
  exit 2
fi
for name in scaling_governor scaling_available_governors scaling_min_freq \
  scaling_max_freq related_cpus; do
  [[ -r "$governor_policy/$name" ]] || {
    echo "result=BLOCKED reason=cpufreq_field_missing field=$name" >&2
    exit 2
  }
done
governor_original="$(tr -d '[:space:]' < "$governor_policy/scaling_governor")"
if [[ "$governor_original" != "schedutil" ]]; then
  echo "result=BLOCKED reason=unexpected_initial_governor value=$governor_original" >&2
  exit 2
fi
grep -qw performance "$governor_policy/scaling_available_governors" || {
  echo "result=BLOCKED reason=performance_governor_unavailable" >&2
  exit 2
}
if [[ "$(xargs < "$governor_policy/related_cpus")" != "0 1 2 3 4 5 6 7" ]]; then
  echo "result=BLOCKED reason=unexpected_cpufreq_policy_membership" >&2
  exit 2
fi
if [[ "$(tr -d '[:space:]' < "$governor_policy/scaling_min_freq")" != "300000" || \
      "$(tr -d '[:space:]' < "$governor_policy/scaling_max_freq")" != "1500000" ]]; then
  echo "result=BLOCKED reason=unexpected_cpufreq_range" >&2
  exit 2
fi

mkdir -p "$output_dir/preflight" "$output_dir/cutoff"
if ! require_controller_state "$output_dir/controller-before.txt"; then
  echo "result=BLOCKED reason=controller_identity_or_bluetooth_state" >&2
  exit 2
fi
printf '%s\n' "$(git -C "$source_root" rev-parse HEAD)" > "$output_dir/source-commit.txt"
printf '%s  %s\n' "$(sha256_of "$config_path")" "$config_path" \
  > "$output_dir/config-sha256.txt"
cp "$governor_policy/scaling_governor" "$output_dir/governor-before.txt"
cp "$governor_policy/scaling_min_freq" "$output_dir/min-frequency-before.txt"
cp "$governor_policy/scaling_max_freq" "$output_dir/max-frequency-before.txt"
cp "$governor_policy/related_cpus" "$output_dir/related-cpus.txt"
printf '%s\n' performance > "$governor_policy/scaling_governor"
governor_changed=1
if [[ "$(tr -d '[:space:]' < "$governor_policy/scaling_governor")" != "performance" ]]; then
  echo "result=BLOCKED reason=performance_governor_verification_failed" >&2
  exit 2
fi
cp "$governor_policy/scaling_governor" "$output_dir/governor-during.txt"

preflight_command=(
  taskset -c 0-7 env "PYTHONPATH=$source_root/src" "$venv_python"
  -m open_duck_x5.probe
  --bus serial --device "$device" --baudrate 1000000 --timeout-ms 4
  --ticks "$preflight_ticks" --frequency-hz "$frequency_hz"
  --sine-hz 0.5 --sine-joint left_hip_yaw --amplitude-rad 0
  --config "$config_path" --home-seconds "$home_seconds" --watchdog-failures 2
  --controller xbox --require-realtime --rt-cpu 7 --rt-priority 80
  --hardware-authorized --suspended-or-benched
  --output "$output_dir/preflight/timing.jsonl"
  --summary "$output_dir/preflight/summary.json"
)
printf '%q ' "${preflight_command[@]}" > "$output_dir/preflight/command.txt"
printf '\n' >> "$output_dir/preflight/command.txt"
echo "stage=torque_off_preflight status=STARTED ticks=$preflight_ticks"
set +e
(cd "$source_root" && exec "${preflight_command[@]}") \
  > "$output_dir/preflight/stdout.txt" 2> "$output_dir/preflight/stderr.txt" &
active_probe_pid=$!
wait "$active_probe_pid"
preflight_probe_status=$?
active_probe_pid=""
set -e
if [[ "$preflight_probe_status" -eq 0 ]]; then
  set +e
  env "PYTHONPATH=$source_root/src" "$venv_python" \
    -m open_duck_x5.gate2_validation \
    --summary "$output_dir/preflight/summary.json" --stage preflight \
    --expected-config-sha256 "$expected_config_sha256" \
    > "$output_dir/preflight/validation.txt" 2>&1
  preflight_validation_status=$?
  set -e
else
  preflight_validation_status=1
fi
if [[ "$preflight_probe_status" -ne 0 || "$preflight_validation_status" -ne 0 ]]; then
  echo "result=HALTED stage=torque_off_preflight"
  restore_status=0
  restore_governor || restore_status=1
  cat "$governor_policy/scaling_governor" > "$output_dir/governor-after.txt"
  exit 3
fi
echo "stage=torque_off_preflight status=PASS"

if ! require_controller_state "$output_dir/controller-before-motion.txt"; then
  echo "result=HALTED reason=controller_not_ready_before_home_entry" >&2
  restore_status=0
  restore_governor || restore_status=1
  cat "$governor_policy/scaling_governor" > "$output_dir/governor-after.txt"
  exit 3
fi
if command -v fuser >/dev/null 2>&1 && fuser "$device" >/dev/null 2>&1; then
  echo "result=HALTED reason=serial_device_owned_before_home_entry" >&2
  exit 3
fi

cutoff_command=(
  taskset -c 0-7 env "PYTHONPATH=$source_root/src" "$venv_python"
  -m open_duck_x5.probe
  --bus serial --device "$device" --baudrate 1000000 --timeout-ms 4
  --ticks "$cutoff_ticks" --frequency-hz "$frequency_hz"
  --sine-hz 0.5 --sine-joint left_hip_yaw --amplitude-rad 0
  --config "$config_path" --home-seconds "$home_seconds" --watchdog-failures 2
  --controller xbox --require-realtime --rt-cpu 7 --rt-priority 80
  --enable-torque --moving-gate-authorized
  --emergency-stop-cutoff-audit-output "$output_dir/cutoff/cutoff-audit.json"
  --home-ready-output "$output_dir/cutoff/home-ready.json"
  --hardware-authorized --suspended-or-benched
  --output "$output_dir/cutoff/timing.jsonl"
  --summary "$output_dir/cutoff/summary.json"
)
printf '%q ' "${cutoff_command[@]}" > "$output_dir/cutoff/command.txt"
printf '\n' >> "$output_dir/cutoff/command.txt"
echo "stage=home_entry_and_hold status=STARTED do_not_press_buttons"
motion_stage_started=1
set +e
(cd "$source_root" && exec "${cutoff_command[@]}") \
  > "$output_dir/cutoff/stdout.txt" 2> "$output_dir/cutoff/stderr.txt" &
active_probe_pid=$!
set -e

home_ready=0
for _ in $(seq 1 600); do
  if [[ -f "$output_dir/cutoff/home-ready.json" ]] && \
     "$venv_python" - "$output_dir/cutoff/home-ready.json" \
       "$expected_config_sha256" >/dev/null 2>&1 <<'PY'
import json
import sys
from pathlib import Path

value = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
expected_config = sys.argv[2]
checks = (
    value.get("status") == "HOME_HOLD_READY",
    value.get("controller_connected") is True,
    value.get("torque_enabled_requested") is True,
    value.get("policy_loaded") is False,
    value.get("home_entry_seconds") == 5.0,
    value.get("config_sha256") == expected_config,
    len(value.get("target_positions_rad", [])) == 14,
)
raise SystemExit(0 if all(checks) else 1)
PY
  then
    home_ready=1
    break
  fi
  if ! kill -0 "$active_probe_pid" 2>/dev/null; then
    break
  fi
  sleep 0.1
done

if [[ "$home_ready" -eq 1 ]]; then
  printf '%s\n' "GO — press B exactly once now; do not press A" \
    | tee "$output_dir/operator-cue.txt"
else
  echo "result=HALTED reason=home_ready_cue_not_reached" >&2
  if kill -0 "$active_probe_pid" 2>/dev/null; then
    kill -TERM "$active_probe_pid" 2>/dev/null || true
  fi
fi

set +e
wait "$active_probe_pid"
cutoff_probe_status=$?
set -e
active_probe_pid=""

if command -v fuser >/dev/null 2>&1; then
  for _ in $(seq 1 20); do
    if ! fuser "$device" >/dev/null 2>&1; then break; fi
    sleep 0.05
  done
fi
run_independent_readback

controller_after_ok=0
if require_controller_state "$output_dir/controller-after.txt"; then
  controller_after_ok=1
else
  bluetoothctl info "$expected_controller_mac" > "$output_dir/controller-after.txt" 2>&1 || true
  if [[ -r "$controller_uniq_path" ]]; then
    tr '[:upper:]' '[:lower:]' < "$controller_uniq_path" | tr -d '[:space:]' \
      > "$output_dir/controller-after-uniq.txt"
  fi
fi
serial_released=0
if ! command -v fuser >/dev/null 2>&1 || ! fuser "$device" >/dev/null 2>&1; then
  serial_released=1
fi
restore_status=0
restore_governor || restore_status=1
cat "$governor_policy/scaling_governor" > "$output_dir/governor-after.txt"

if [[ -f "$output_dir/cutoff/summary.json" && \
      -f "$output_dir/cutoff/cutoff-audit.json" && \
      -f "$output_dir/cutoff/home-ready.json" && \
      -f "$output_dir/torque-off-readback.json" ]]; then
  set +e
  "$venv_python" - \
    "$output_dir/cutoff/summary.json" \
    "$output_dir/cutoff/cutoff-audit.json" \
    "$output_dir/cutoff/home-ready.json" \
    "$output_dir/torque-off-readback.json" \
    "$output_dir/cutoff/validation.json" \
    "$cutoff_probe_status" "$readback_status" "$controller_after_ok" \
    "$serial_released" "$restore_status" "$expected_config_sha256" <<'PY'
import json
import math
import sys
from pathlib import Path

summary_path, audit_path, ready_path, readback_path, output_path = map(
    Path, sys.argv[1:6]
)
probe_status, readback_status, controller_ok, serial_released, restore_status = map(
    int, sys.argv[6:11]
)
expected_config = sys.argv[11]
summary = json.loads(summary_path.read_text(encoding="utf-8"))
audit = json.loads(audit_path.read_text(encoding="utf-8"))
ready = json.loads(ready_path.read_text(encoding="utf-8"))
readback = json.loads(readback_path.read_text(encoding="utf-8"))
latency = audit.get("detection_to_torque_disable_complete_ms")
checks = {
    "expected_probe_exit_2": probe_status == 2,
    "exact_halt": summary.get("run_status") == "HALTED"
    and summary.get("halt_reason") == "physical controller emergency stop requested",
    "no_policy_home_hold": summary.get("environment", {}).get("torque_enabled") is True
    and summary.get("environment", {}).get("amplitude_rad") == 0.0
    and summary.get("environment", {}).get("controller") == "xbox",
    "frozen_config": summary.get("environment", {}).get("config_sha256")
    == expected_config,
    "runtime_torque_off": summary.get("environment", {}).get("torque_off_status")
    == "ok"
    and summary.get("gates", {}).get("torque_off_confirmed") is True,
    "home_ready": ready.get("status") == "HOME_HOLD_READY"
    and ready.get("controller_connected") is True
    and ready.get("policy_loaded") is False
    and ready.get("torque_enabled_requested") is True
    and ready.get("home_entry_seconds") == 5.0
    and ready.get("config_sha256") == expected_config,
    "cutoff_pass_candidate": audit.get("status") == "PASS_CANDIDATE"
    and audit.get("policy_loaded") is False
    and audit.get("halt_reason") == "physical controller emergency stop requested"
    and audit.get("cutoff_limit_ms") == 20.0
    and isinstance(latency, (int, float))
    and not isinstance(latency, bool)
    and math.isfinite(float(latency))
    and 0.0 <= float(latency) <= 20.0
    and audit.get("control_exchanges_at_detection")
    == audit.get("control_exchanges_completed")
    and bool(audit.get("checks"))
    and all(value is True for value in audit["checks"].values()),
    "independent_readback_process": readback_status == 0,
    "all_14_register_40_zero": readback.get("status") == "PASS"
    and readback.get("register_address") == 40
    and len(readback.get("records", [])) == 14
    and readback.get("checks", {}).get("all_14_torque_enable_registers_zero")
    is True
    and all(record.get("torque_enable_raw") == 0 for record in readback["records"]),
    "controller_after": controller_ok == 1,
    "serial_released": serial_released == 1,
    "governor_restored": restore_status == 0,
}
payload = {
    "schema_version": "open_duck_x5.suspended_controller_b_cutoff_g2_validation.v1",
    "status": "PASS_CANDIDATE" if all(checks.values()) else "FAIL",
    "checks": checks,
    "checks_passed": sum(checks.values()),
    "checks_total": len(checks),
    "failed_checks": [name for name, passed in checks.items() if not passed],
    "automatic_follow_on": False,
    "grounded_motion_authorized": False,
}
output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
raise SystemExit(0 if all(checks.values()) else 3)
PY
  cutoff_validation_status=$?
  set -e
else
  cutoff_validation_status=1
fi

"$venv_python" - "$output_dir/metadata.json" \
  "$preflight_probe_status" "$preflight_validation_status" \
  "$cutoff_probe_status" "$cutoff_validation_status" "$readback_status" \
  "$restore_status" <<'PY'
import json
import sys
from pathlib import Path

output, preflight, preflight_validation, cutoff, cutoff_validation, readback, restore = (
    sys.argv[1:]
)
value = {
    "schema_version": "open_duck_x5.suspended_controller_b_cutoff_g2_run.v1",
    "preflight_ticks_requested": 10_000,
    "home_entry_seconds": 5.0,
    "cutoff_ticks_maximum": 3_000,
    "policy_loaded": False,
    "fixed_command": None,
    "preflight_probe_status": int(preflight),
    "preflight_validation_status": int(preflight_validation),
    "cutoff_probe_status": int(cutoff),
    "cutoff_validation_status": int(cutoff_validation),
    "independent_readback_status": int(readback),
    "governor_restore_status": int(restore),
    "automatic_follow_on": False,
    "grounded_motion_authorized": False,
}
Path(output).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
PY

find "$output_dir" -type f ! -name sha256sums.txt -print0 \
  | sort -z | xargs -0 sha256sum > "$output_dir/sha256sums.txt"
if [[ -n "${SUDO_USER:-}" && "$SUDO_USER" != "root" ]]; then
  chown -R "$SUDO_USER:$(id -gn "$SUDO_USER")" "$output_dir"
fi

final_status=0
if [[ "$preflight_probe_status" -ne 0 || "$preflight_validation_status" -ne 0 || \
      "$cutoff_probe_status" -ne 2 || "$cutoff_validation_status" -ne 0 || \
      "$readback_status" -ne 0 || "$restore_status" -ne 0 ]]; then
  final_status=3
fi
echo "result=$([[ "$final_status" -eq 0 ]] && echo REVIEW_CANDIDATE || echo HALTED)"
echo "preflight_probe_status=$preflight_probe_status"
echo "preflight_validation_status=$preflight_validation_status"
echo "cutoff_probe_status=$cutoff_probe_status"
echo "cutoff_validation_status=$cutoff_validation_status"
echo "independent_readback_status=$readback_status"
echo "governor_restore_status=$restore_status"
echo "grounded_motion_authorized=false"
echo "output_dir=$output_dir"
exit "$final_status"
