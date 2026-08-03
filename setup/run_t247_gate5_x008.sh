#!/usr/bin/env bash
set -euo pipefail

readonly expected_source_tree="2aba58167a82b47bdd6942da25d4913c098cbfba"
readonly expected_schema_tree="55580397a2d01bd6f76417f57a92c4dddee7f642"
readonly expected_pyproject_blob="8bd71d3a44276bdb21755d1492a19c57f6c80fe0"
readonly expected_preregistration_sha256="00aa292f9a39445690d5ec654aadc46edde49021d6cb467a524e739d7009d457"
readonly expected_readiness_review_sha256="15c550432eb6ada9b9579c1e298a32585dd6c81091c97ad95be6fe0f9c3e61b7"
readonly expected_x0_review_sha256="9d40a3cd5c937eff84a65ea3117af9b0178eebc8af366692926fd175736fb096"
readonly expected_config_sha256="131a7b8fce1107b14f4727562f44f9e17324caf7fc22512ad7115911f050991b"
readonly expected_imu_sha256="e7518b0df8614c1d399c789fd26aa9888043ebacfccc98ef75a5010a4b8c34be"
readonly expected_policy_sha256="dadfb446ea7c720f274a15bc65e9171c2e74d715ccfaf58adbb408b6c1365a54"
readonly expected_calibrator_sha256="0f3aebfd9946a6271fdb14adec3d68d556648f270984639d372c973a7d7dc576"
readonly expected_command_manifest_sha256="5621f7c6782a8346bf25f05ce7f0bc002acbe8e98872cf658f0d44773511b4cd"
readonly expected_context_manifest_sha256="61c54d755c2846bd811775786c6599606a7be70fbaa7c9266cd3fb613d64a536"
readonly expected_context_router_sha256="3b1f406fba5147a3f38ec59fc7f9c8d42dd27fa7eeb54344f447c060eb95b284"
readonly expected_p30_sha256="a58db8ffc505d2bb64cba7f5618d0e2c65904fc9f9ac37b560a1231e090f5f4f"
readonly expected_reference_sha256="8102d9cd139584816d807ca635bcca6d37fa6b3c455848e00395b6d565968212"
readonly expected_controller_mac="0C:35:26:2A:B8:0B"
readonly expected_controller_uniq="0c:35:26:2a:b8:0b"
readonly expected_controller_modalias="usb:v045Ep0B13d0515"
readonly controller_device="/dev/input/js0"
readonly controller_uniq_path="/sys/class/input/js0/device/uniq"
readonly device="/dev/ttyS1"
readonly active_ticks="850"
readonly maximum_total_ticks="3850"
readonly home_seconds="5"
readonly governor_policy="/sys/devices/system/cpu/cpufreq/policy0"
readonly venv_python="/home/sunrise/duck_env/bin/python"
readonly runner_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

source_root=""
asset_root=""
config_path=""
imu_calibration=""
output_dir=""
hardware_authorized=0
suspended_or_benched=0
gate5_moving_authorized=0
active_runtime_pid=""
governor_original=""
governor_changed=0
runtime_status=-1
summary_status=-1
candidate_status=-1
restore_status=-1
controller_after_ok=0
serial_released=false

usage() {
  cat <<'EOF'
Usage: sudo setup/run_t247_gate5_x008.sh \
  --source-root /home/sunrise/open-duck-x5-gate5-x008 \
  --asset-root /home/sunrise/open-duck-x5-gate5-t247-assets \
  --config /home/sunrise/duck_config.json \
  --imu-calibration /home/sunrise/gate3/sensor-matrix-20260718-readybarrier/calibration/imu_calibration.json \
  --output-dir /home/sunrise/duck-evidence/gate5-t247-x008-readiness-cued-YYYYMMDD \
  --hardware-authorized --suspended-or-benched --gate5-moving-authorized

Runs exactly the frozen suspended T247 x=.08 arm: five-second home entry, one
paused startup-readiness exchange, 250 active calibration ticks, and 600 active
locomotion ticks. It requires the exact reviewed x=0 receipt. There is no
configurable command or second-command path.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source-root) source_root="$2"; shift 2 ;;
    --asset-root) asset_root="$2"; shift 2 ;;
    --config) config_path="$2"; shift 2 ;;
    --imu-calibration) imu_calibration="$2"; shift 2 ;;
    --output-dir) output_dir="$2"; shift 2 ;;
    --hardware-authorized) hardware_authorized=1; shift ;;
    --suspended-or-benched) suspended_or_benched=1; shift ;;
    --gate5-moving-authorized) gate5_moving_authorized=1; shift ;;
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
  local uniq info required
  uniq="$(tr '[:upper:]' '[:lower:]' < "$controller_uniq_path" | tr -d '[:space:]')"
  [[ "$uniq" == "$expected_controller_uniq" ]] || return 1
  info="$(bluetoothctl info "$expected_controller_mac")" || return 1
  for required in \
    "Paired: yes" \
    "Trusted: yes" \
    "Connected: yes" \
    "Modalias: ${expected_controller_modalias}"; do
    grep -Fq "$required" <<<"$info" || return 1
  done
  printf '%s\n' "$info" > "$output"
  printf '%s\n' "$uniq" > "${output%.txt}-uniq.txt"
}

if [[ "$EUID" -ne 0 ]]; then
  echo "result=BLOCKED reason=root_required_for_governor_and_sched_fifo" >&2
  exit 2
fi
if [[ "$hardware_authorized" -ne 1 || "$suspended_or_benched" -ne 1 || \
      "$gate5_moving_authorized" -ne 1 ]]; then
  echo "result=BLOCKED reason=missing_gate5_hardware_acknowledgements" >&2
  exit 2
fi
if [[ ! -x "$venv_python" ]]; then
  echo "result=BLOCKED reason=venv_python_missing" >&2
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
if ! git -C "$source_root" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "result=BLOCKED reason=source_root_is_not_a_git_worktree" >&2
  exit 2
fi
if [[ -n "$(git -C "$source_root" status --porcelain --untracked-files=no)" ]]; then
  echo "result=BLOCKED reason=tracked_source_worktree_dirty" >&2
  exit 2
fi
if [[ "$(git -C "$source_root" rev-parse HEAD:src/open_duck_x5)" != \
      "$expected_source_tree" || \
      "$(git -C "$source_root" rev-parse HEAD:schemas)" != \
      "$expected_schema_tree" || \
      "$(git -C "$source_root" rev-parse HEAD:pyproject.toml)" != \
      "$expected_pyproject_blob" ]]; then
  echo "result=BLOCKED reason=frozen_source_tree_mismatch" >&2
  exit 2
fi

preregistration="$source_root/artifacts/gates/phase_7_hardware/gate_5_policy/T247_X008_READINESS_CUED_PREREGISTRATION_20260802.json"
readiness_review="$source_root/artifacts/gates/phase_7_hardware/gate_5_policy/T247_STARTUP_READINESS_REVALIDATION_PASS_20260802.json"
x0_review="$source_root/artifacts/gates/phase_7_hardware/gate_5_policy/T247_X0_READINESS_CUED_PASS_REVIEWED_20260802.json"
require_hash "$preregistration" "$expected_preregistration_sha256" "preregistration"
require_hash "$readiness_review" "$expected_readiness_review_sha256" "readiness_review"
require_hash "$x0_review" "$expected_x0_review_sha256" "x0_review"
"$venv_python" - "$preregistration" "$x0_review" <<'PY'
import json
import sys
from pathlib import Path

preregistration = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
x0_review = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
checks = {
    "preregistered": preregistration.get("status")
    == "PREREGISTERED_NOT_RUN_T247_GATE5_X008_READINESS_CUED",
    "candidate": preregistration.get("candidate_id")
    == "T247_HOME_NEGATIVE_HALF_ADAPTER_FINAL",
    "source_tree": preregistration.get("frozen_runtime", {}).get("source_tree")
    == "2aba58167a82b47bdd6942da25d4913c098cbfba",
    "schema_tree": preregistration.get("frozen_runtime", {}).get("schema_tree")
    == "55580397a2d01bd6f76417f57a92c4dddee7f642",
    "phase": preregistration.get("frozen_runtime", {}).get(
        "startup_readiness_phase"
    )
    == [0.0, 0.0],
    "command": preregistration.get("frozen_candidate", {}).get(
        "fixed_command_x_m_s"
    )
    == 0.08,
    "x0_status": x0_review.get("status")
    == "PASS_REVIEWED_T247_GATE5_X0",
    "x0_candidate": x0_review.get("candidate_id")
    == "T247_HOME_NEGATIVE_HALF_ADAPTER_FINAL",
    "x0_command": x0_review.get("scope", {}).get("fixed_command_x_m_s") == 0.0,
    "x0_ticks": x0_review.get("scope", {}).get("active_policy_ticks") == 850,
    "x0_operator": x0_review.get("operator_review", {}).get("result") == "PASS",
    "x0_torque_off": x0_review.get("safety_exit", {}).get(
        "all_14_torque_enable_registers_zero"
    )
    is True,
    "x0_decision": x0_review.get("decision", {}).get("gate5_x0")
    == "PASS_REVIEWED",
    "x008_earned": x0_review.get("decision", {}).get(
        "x008_preregistration_earned"
    )
    is True,
    "x008_not_authorized": x0_review.get("decision", {}).get(
        "x008_run_authorized"
    )
    is False,
    "no_authority": preregistration.get("authority", {}).get("gate5_run")
    is False,
}
if not all(checks.values()):
    raise SystemExit("result=BLOCKED reason=x008_preregistration_or_x0_review_mismatch")
PY
"$venv_python" - "$readiness_review" <<'PY'
import json
import sys
from pathlib import Path

value = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
checks = {
    "status": value.get("status") == "PASS_REVIEWED_NO_MOTION",
    "candidate": value.get("candidate_id") == "T247_HOME_NEGATIVE_HALF_ADAPTER_FINAL",
    "device": value.get("scope", {}).get("serial_device") == "/dev/ttyS1",
    "controller": value.get("scope", {}).get("controller_sysfs_uniq")
    == "0c:35:26:2a:b8:0b",
    "readiness": value.get("startup_readiness", {}).get("status") == "PASS",
    "ticks": value.get("measured_population", {}).get("ticks_completed") == 10_000,
    "failures": value.get("measured_population", {}).get("transactions_failed") == 0,
    "bursts": value.get("measured_population", {}).get("read_bursts") == 0,
    "review": value.get("independent_review", {}).get("status") == "PASS",
    "no_prior_motion": value.get("scope", {}).get("motion") is False,
    "no_prior_policy": value.get("scope", {}).get("policy_loaded") is False,
    "no_authority": value.get("authority", {}).get("x0_motion") is False,
}
if not all(checks.values()):
    raise SystemExit("result=BLOCKED reason=readiness_review_contract_mismatch")
PY

if [[ -z "$asset_root" || ! -d "$asset_root" ]]; then
  echo "result=BLOCKED reason=asset_root_missing" >&2
  exit 2
fi
asset_root="$(realpath "$asset_root")"
policy_path="$asset_root/policy.onnx"
calibrator_path="$asset_root/calibrator.onnx"
p30_path="$asset_root/p30.json"
reference_path="$asset_root/reference.npz"
context_root="$asset_root/context-routes"
command_root="$asset_root/command-routes"
command_manifest="$command_root/manifest.json"
require_hash "$policy_path" "$expected_policy_sha256" "policy"
require_hash "$calibrator_path" "$expected_calibrator_sha256" "calibrator"
require_hash "$p30_path" "$expected_p30_sha256" "p30_fit"
require_hash "$reference_path" "$expected_reference_sha256" "reference_table"
require_hash "$context_root/manifest.json" "$expected_context_manifest_sha256" \
  "context_manifest"
require_hash "$context_root/policy.context-router.onnx" \
  "$expected_context_router_sha256" "context_router"
require_hash "$command_manifest" "$expected_command_manifest_sha256" \
  "command_manifest"

if [[ -z "$config_path" ]]; then
  echo "result=BLOCKED reason=config_required" >&2
  exit 2
fi
config_path="$(realpath "$config_path")"
require_hash "$config_path" "$expected_config_sha256" "config"
"$venv_python" - "$config_path" <<'PY'
import json
import sys
from pathlib import Path

value = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if value.get("start_paused") is not True:
    raise SystemExit("result=BLOCKED reason=config_start_paused_not_true")
PY

if [[ -z "$imu_calibration" ]]; then
  echo "result=BLOCKED reason=imu_calibration_required" >&2
  exit 2
fi
imu_calibration="$(realpath "$imu_calibration")"
require_hash "$imu_calibration" "$expected_imu_sha256" "imu_calibration"

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
if [[ "$(tr -d '[:space:]' < /sys/devices/system/cpu/isolated)" != "7" ]]; then
  echo "result=BLOCKED reason=cpu7_not_exact_isolated_cpu" >&2
  exit 2
fi
for field in scaling_governor scaling_available_governors scaling_min_freq \
  scaling_max_freq related_cpus; do
  if [[ ! -r "$governor_policy/$field" ]]; then
    echo "result=BLOCKED reason=cpufreq_field_missing field=$field" >&2
    exit 2
  fi
done
governor_original="$(tr -d '[:space:]' < "$governor_policy/scaling_governor")"
if [[ "$governor_original" != "schedutil" ]]; then
  echo "result=BLOCKED reason=unexpected_initial_governor value=$governor_original" >&2
  exit 2
fi
if ! grep -qw performance "$governor_policy/scaling_available_governors"; then
  echo "result=BLOCKED reason=performance_governor_unavailable" >&2
  exit 2
fi
if [[ "$(xargs < "$governor_policy/related_cpus")" != "0 1 2 3 4 5 6 7" ]]; then
  echo "result=BLOCKED reason=unexpected_cpufreq_policy_membership" >&2
  exit 2
fi
if [[ "$(tr -d '[:space:]' < "$governor_policy/scaling_min_freq")" != "300000" || \
      "$(tr -d '[:space:]' < "$governor_policy/scaling_max_freq")" != "1500000" ]]; then
  echo "result=BLOCKED reason=unexpected_cpufreq_range" >&2
  exit 2
fi

mkdir -p "$output_dir"
if ! require_controller_state "$output_dir/controller-before.txt"; then
  echo "result=BLOCKED reason=controller_identity_or_bluetooth_state" >&2
  exit 2
fi
git -C "$source_root" rev-parse HEAD > "$output_dir/source-commit.txt"
printf '%s\n' "$expected_source_tree" > "$output_dir/source-tree.txt"
printf '%s\n' "$expected_schema_tree" > "$output_dir/schema-tree.txt"
printf '%s  %s\n' "$expected_preregistration_sha256" "$preregistration" \
  > "$output_dir/preregistration-sha256.txt"
printf '%s  %s\n' "$expected_readiness_review_sha256" "$readiness_review" \
  > "$output_dir/readiness-review-sha256.txt"
printf '%s  %s\n' "$expected_x0_review_sha256" "$x0_review" \
  > "$output_dir/x0-review-sha256.txt"
printf '%s  %s\n' "$expected_config_sha256" "$config_path" \
  > "$output_dir/config-sha256.txt"
printf '%s  %s\n' "$expected_imu_sha256" "$imu_calibration" \
  > "$output_dir/imu-calibration-sha256.txt"
cp "$governor_policy/scaling_governor" "$output_dir/governor-before.txt"
cp "$governor_policy/scaling_min_freq" "$output_dir/min-frequency-before.txt"
cp "$governor_policy/scaling_max_freq" "$output_dir/max-frequency-before.txt"
cp "$governor_policy/related_cpus" "$output_dir/related-cpus.txt"

restore_governor() {
  if [[ "$governor_changed" -eq 1 ]]; then
    printf '%s\n' "$governor_original" > "$governor_policy/scaling_governor" || return 1
    [[ "$(tr -d '[:space:]' < "$governor_policy/scaling_governor")" == \
      "$governor_original" ]] || return 1
    governor_changed=0
  fi
}

cleanup() {
  local cleanup_status=0
  if [[ -n "$active_runtime_pid" ]] && kill -0 "$active_runtime_pid" 2>/dev/null; then
    kill -TERM "$active_runtime_pid" 2>/dev/null || true
    wait "$active_runtime_pid" 2>/dev/null || true
    active_runtime_pid=""
  fi
  restore_governor || cleanup_status=1
  return "$cleanup_status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

printf '%s\n' performance > "$governor_policy/scaling_governor"
governor_changed=1
if [[ "$(tr -d '[:space:]' < "$governor_policy/scaling_governor")" != \
      "performance" ]]; then
  echo "result=BLOCKED reason=performance_governor_verification_failed" >&2
  exit 2
fi
cp "$governor_policy/scaling_governor" "$output_dir/governor-during.txt"

runtime_command=(
  taskset -c 0-7 env "PYTHONPATH=$source_root/src" "$venv_python"
  -m open_duck_x5.runtime
  --bus serial --device "$device" --baudrate 1000000 --timeout-ms 4
  --config "$config_path"
  --policy "$policy_path" --policy-contract t247-command-routed-115
  --calibrator "$calibrator_path"
  --context-route-root "$context_root"
  --command-route-root "$command_root"
  --command-route-manifest "$command_manifest"
  --p30-fit "$p30_path" --reference-table "$reference_path"
  --controller xbox --fixed-command-x 0.08
  --telemetry "$output_dir/control.jsonl"
  --max-active-ticks "$active_ticks" --max-ticks "$maximum_total_ticks"
  --home-seconds "$home_seconds" --watchdog-failures 3
  --imu-calibration "$imu_calibration"
  --require-realtime --rt-cpu 7 --rt-priority 80
  --gate5-authorized --hardware-authorized --suspended-or-benched
)
printf '%q ' "${runtime_command[@]}" > "$output_dir/runtime-command.txt"
printf '\n' >> "$output_dir/runtime-command.txt"

(cd "$source_root" && exec "${runtime_command[@]}") \
  > "$output_dir/runtime-stdout.txt" \
  2> "$output_dir/runtime-stderr.txt" &
active_runtime_pid=$!
set +e
wait "$active_runtime_pid"
runtime_status=$?
set -e
active_runtime_pid=""

restore_status=0
restore_governor || restore_status=1
cat "$governor_policy/scaling_governor" > "$output_dir/governor-after.txt"
if require_controller_state "$output_dir/controller-after.txt"; then
  controller_after_ok=1
else
  controller_after_ok=0
  bluetoothctl info "$expected_controller_mac" \
    > "$output_dir/controller-after.txt" 2>&1 || true
  if [[ -r "$controller_uniq_path" ]]; then
    tr '[:upper:]' '[:lower:]' < "$controller_uniq_path" | tr -d '[:space:]' \
      > "$output_dir/controller-after-uniq.txt"
  else
    printf 'missing\n' > "$output_dir/controller-after-uniq.txt"
  fi
fi
if ! command -v fuser >/dev/null 2>&1 || ! fuser "$device" >/dev/null 2>&1; then
  serial_released=true
fi

if [[ -f "$output_dir/control.jsonl" ]]; then
  set +e
  PYTHONPATH="$source_root/src" "$venv_python" -m open_duck_x5.control_summary \
    --input "$output_dir/control.jsonl" --output "$output_dir/summary.json" \
    > "$output_dir/summary-stdout.txt" 2> "$output_dir/summary-stderr.txt"
  summary_status=$?
  set -e
else
  summary_status=1
  printf '%s\n' "control telemetry was not created" > "$output_dir/summary-stderr.txt"
fi

if [[ "$summary_status" -eq 0 ]]; then
  set +e
  "$venv_python" - "$output_dir/control.jsonl" "$output_dir/summary.json" \
    "$output_dir/candidate-review.json" "$controller_after_ok" \
    "$serial_released" <<'PY'
import json
import math
import sys
from pathlib import Path

control_path, summary_path, output_path, controller_ok, serial_released = sys.argv[1:]
event_counts = {}
with Path(control_path).open(encoding="utf-8") as handle:
    for line_number, line in enumerate(handle, 1):
        record = json.loads(line)
        schema_version = record.get("schema_version")
        if schema_version == "open_duck_x5.runtime_event.v1":
            event = record["event"]
            event_counts[event] = event_counts.get(event, 0) + 1
        elif schema_version == "open_duck_x5.control_tick.v1":
            continue
        else:
            raise ValueError(f"unknown telemetry schema at line {line_number}")

summary = json.loads(Path(summary_path).read_text(encoding="utf-8"))
gates = summary["gates"]
readiness = summary.get("startup_readiness") or {}
tick_stats = summary.get("timing", {}).get("tick_period_ms", {})
bus = summary.get("bus", {})
bus_stats = bus.get("bus_total_ms", {})


def at_most(value, limit):
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
        and float(value) <= limit
    )


def below(value, limit):
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
        and float(value) < limit
    )


checks = {
    "serial_backend": summary.get("backend") == "serial",
    "complete": summary.get("run_status") == "COMPLETE",
    "review_required": summary.get("review_status") == "REVIEW_REQUIRED",
    "active_ticks_exact": summary.get("active_policy_ticks") == 850
    and summary.get("active_ticks_requested") == 850,
    "maximum_ticks_exact": summary.get("ticks_requested") == 3850,
    "fixed_command_exact": summary.get("command", {}).get("fixed_x") == 0.08
    and summary.get("command", {}).get("matches_fixed_x") is True,
    "startup_readiness_exact": event_counts.get("startup_readiness") == 1
    and readiness.get("status") == "PASS"
    and readiness.get("failures") == []
    and readiness.get("paused") is True
    and readiness.get("policy_staged") is False
    and readiness.get("policy_committed_ticks") == 0
    and readiness.get("phase") == [0.0, 0.0]
    and readiness.get("all_fresh") is True
    and readiness.get("imu_stale") is False
    and readiness.get("contacts_stale") is False
    and readiness.get("bus_total_ms", 5.0) < 5.0,
    "event_cardinality": event_counts == {
        "runtime_start": 1,
        "realtime_verified": 1,
        "startup_readiness": 1,
        "runtime_halt": 1,
    },
    "all_summary_gates_true": bool(gates)
    and all(value is True for value in gates.values()),
    "timing": at_most(tick_stats.get("p99"), 21.0)
    and at_most(tick_stats.get("p99_9"), 22.0),
    "bus": below(bus_stats.get("max"), 5.0)
    and below(bus.get("transaction_failure_rate"), 0.001)
    and bus.get("read_burst_count") == 0
    and bus.get("stale_servo_sample_count") == 0
    and bus.get("device_alarm_reply_count") == 0,
    "telemetry_complete": summary.get("telemetry_records_dropped") == 0,
    "torque_off": summary.get("safety", {}).get("torque_off_confirmed") is True,
    "controller_after": controller_ok == "1",
    "serial_released": serial_released == "true",
}
payload = {
    "schema_version": "open_duck_x5.t247_gate5_x008_readiness_cued_candidate_review.v1",
    "status": (
        "COMPLETE_T247_GATE5_X008_REVIEW_REQUIRED"
        if all(checks.values())
        else "HOLD_T247_GATE5_X008"
    ),
    "candidate_id": "T247_HOME_NEGATIVE_HALF_ADAPTER_FINAL",
    "fixed_command_x_m_s": 0.08,
    "checks": checks,
    "checks_passed": sum(checks.values()),
    "checks_total": len(checks),
    "failed_checks": [name for name, passed in checks.items() if not passed],
    "automatic_gate_promotion": False,
    "operator_observation_required": True,
}
Path(output_path).write_text(
    json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
raise SystemExit(0 if all(checks.values()) else 3)
PY
  candidate_status=$?
  set -e
else
  candidate_status=1
fi

"$venv_python" - "$output_dir/runner-metadata.json" \
  "$runtime_status" "$summary_status" "$candidate_status" "$restore_status" \
  "$controller_after_ok" "$serial_released" <<'PY'
import json
import sys
from pathlib import Path

output, runtime, summary, candidate, restore, controller, serial = sys.argv[1:]
value = {
    "schema_version": "open_duck_x5.t247_gate5_x008_readiness_cued_runner.v1",
    "fixed_command_x_m_s": 0.08,
    "active_ticks": 850,
    "calibration_ticks": 250,
    "locomotion_ticks": 600,
    "maximum_total_ticks": 3850,
    "startup_readiness_attempts": 1,
    "runtime_status": int(runtime),
    "summary_status": int(summary),
    "candidate_status": int(candidate),
    "governor_restore_status": int(restore),
    "controller_after_ok": controller == "1",
    "serial_released": serial == "true",
    "automatic_gate_promotion": False,
    "second_command_path": False,
}
Path(output).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
PY

(
  cd "$output_dir"
  find . -type f ! -name sha256sums.txt -print0 | sort -z | xargs -0 sha256sum
) > "$output_dir/sha256sums.txt"
if [[ -n "${SUDO_USER:-}" && "$SUDO_USER" != "root" ]]; then
  chown -R "$SUDO_USER:$(id -gn "$SUDO_USER")" "$output_dir"
fi

if [[ "$runtime_status" -eq 0 && "$summary_status" -eq 0 && \
      "$candidate_status" -eq 0 && "$restore_status" -eq 0 && \
      "$controller_after_ok" -eq 1 && "$serial_released" == true ]]; then
  echo "result=COMPLETE_REVIEW_REQUIRED"
  echo "fixed_command_x=0.08"
  echo "output_dir=$output_dir"
  exit 0
fi
echo "result=HALTED_REVIEW_REQUIRED"
echo "runtime_status=$runtime_status"
echo "summary_status=$summary_status"
echo "candidate_status=$candidate_status"
echo "governor_restore_status=$restore_status"
echo "controller_after_ok=$controller_after_ok"
echo "serial_released=$serial_released"
echo "output_dir=$output_dir"
exit 3
