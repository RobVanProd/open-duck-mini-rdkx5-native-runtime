#!/usr/bin/env bash
set -euo pipefail

readonly expected_source_tree="a6e19c2aca38c51ce6f3b4a09bc28efe2eedf3c7"
readonly expected_schema_tree="5598eb32d1b79271378d700da896517481f4ded5"
readonly expected_pyproject_blob="c8482e8d54bc7e0e9178094ca80354de5e01888f"
readonly expected_preregistration_sha256="c25a9383c3e7447990bbd5f008dc3e48245915ace79d8d01b284a06738dbc64d"
readonly expected_g3_o1_review_sha256="dd02e9182937a99871c8320f47c4f141972bd7a556871ec655ee56907476e6ef"
readonly expected_config_sha256="131a7b8fce1107b14f4727562f44f9e17324caf7fc22512ad7115911f050991b"
readonly expected_imu_sha256="e7518b0df8614c1d399c789fd26aa9888043ebacfccc98ef75a5010a4b8c34be"
readonly expected_policy_sha256="dadfb446ea7c720f274a15bc65e9171c2e74d715ccfaf58adbb408b6c1365a54"
readonly expected_calibrator_sha256="0f3aebfd9946a6271fdb14adec3d68d556648f270984639d372c973a7d7dc576"
readonly expected_command_manifest_sha256="5621f7c6782a8346bf25f05ce7f0bc002acbe8e98872cf658f0d44773511b4cd"
readonly expected_context_router_sha256="3b1f406fba5147a3f38ec59fc7f9c8d42dd27fa7eeb54344f447c060eb95b284"
readonly expected_p30_sha256="a58db8ffc505d2bb64cba7f5618d0e2c65904fc9f9ac37b560a1231e090f5f4f"
readonly expected_reference_sha256="8102d9cd139584816d807ca635bcca6d37fa6b3c455848e00395b6d565968212"
readonly expected_controller_uniq="0c:35:26:2a:b8:0b"
readonly device="/dev/ttyS1"
readonly controller_device="/dev/input/js0"
readonly controller_uniq_path="/sys/class/input/js0/device/uniq"
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
g3_s1_moving_authorized=0
active_runtime_pid=""
governor_original=""
governor_changed=0

usage() {
  cat <<'EOF'
Usage: sudo setup/run_g3_s1_suspended_guard_revalidation.sh \
  --source-root /home/sunrise/open-duck-x5-g3-s1 \
  --asset-root /home/sunrise/open-duck-x5-gate5-t247-assets \
  --config /home/sunrise/duck_config.json \
  --imu-calibration /home/sunrise/gate3/calibration/imu_calibration.json \
  --output-dir /home/sunrise/duck-evidence/g3-s1-YYYYMMDD \
  --hardware-authorized --suspended-or-benched --g3-s1-moving-authorized

This is only the separately authorized suspended G3-S1 revalidation. It runs
T247 at fixed x=0 with the new tilt/invalid-acceleration guard enabled. The
contact-loss cutoff is intentionally inactive because both contacts false is
the expected suspended state. There is no grounded, x=.08, or follow-on path.
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
    --g3-s1-moving-authorized) g3_s1_moving_authorized=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "result=BLOCKED reason=unknown_argument argument=$1" >&2; exit 2 ;;
  esac
done

sha256_of() { sha256sum "$1" | awk '{print $1}'; }
require_hash() {
  local path="$1" expected="$2" label="$3"
  [[ -f "$path" ]] || { echo "result=BLOCKED reason=${label}_missing" >&2; exit 2; }
  local actual
  actual="$(sha256_of "$path")"
  [[ "$actual" == "$expected" ]] || {
    echo "result=BLOCKED reason=${label}_hash_mismatch actual=${actual}" >&2
    exit 2
  }
}

if [[ "$EUID" -ne 0 ]]; then
  echo "result=BLOCKED reason=root_required" >&2
  exit 2
fi
if [[ "$hardware_authorized" -ne 1 || "$suspended_or_benched" -ne 1 || \
      "$g3_s1_moving_authorized" -ne 1 ]]; then
  echo "result=BLOCKED reason=missing_exact_g3_s1_acknowledgements" >&2
  exit 2
fi
[[ -x "$venv_python" ]] || { echo "result=BLOCKED reason=venv_missing" >&2; exit 2; }
[[ -n "$source_root" && -d "$source_root" ]] || {
  echo "result=BLOCKED reason=source_root_missing" >&2; exit 2;
}
source_root="$(realpath "$source_root")"
[[ "$source_root" == "$runner_root" ]] || {
  echo "result=BLOCKED reason=launcher_source_root_mismatch" >&2; exit 2;
}
[[ -z "$(git -C "$source_root" status --porcelain --untracked-files=no)" ]] || {
  echo "result=BLOCKED reason=tracked_source_worktree_dirty" >&2; exit 2;
}
[[ "$(git -C "$source_root" rev-parse HEAD:src/open_duck_x5)" == "$expected_source_tree" && \
   "$(git -C "$source_root" rev-parse HEAD:schemas)" == "$expected_schema_tree" && \
   "$(git -C "$source_root" rev-parse HEAD:pyproject.toml)" == "$expected_pyproject_blob" ]] || {
  echo "result=BLOCKED reason=frozen_source_mismatch" >&2; exit 2;
}

preregistration="$source_root/artifacts/gates/grounded_validation/G3_S1_SUSPENDED_GUARD_REVALIDATION_PREREGISTRATION_20260803.json"
g3_o1_review="$source_root/artifacts/gates/grounded_validation/G3_O1_OFFLINE_IMPLEMENTATION_PASS_REVIEWED_20260803.json"
require_hash "$preregistration" "$expected_preregistration_sha256" preregistration
require_hash "$g3_o1_review" "$expected_g3_o1_review_sha256" g3_o1_review
"$venv_python" - "$preregistration" "$g3_o1_review" <<'PY'
import json
import sys
from pathlib import Path

prereg = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
review = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
checks = {
    "preregistered": prereg.get("status") == "PREREGISTERED_NOT_RUN",
    "suspended": prereg.get("scope", {}).get("grounded") is False,
    "x0": prereg.get("scope", {}).get("fixed_command_x_m_s") == 0.0,
    "ticks": prereg.get("scope", {}).get("active_policy_ticks") == 850,
    "no_authority": prereg.get("authority", {}).get("suspended_motion_authorized") is False,
    "o1": review.get("status") == "PASS_REVIEWED_G3_O1_OFFLINE",
    "o1_no_robot": review.get("authority", {}).get("robot_access_authorized") is False,
}
if not all(checks.values()):
    raise SystemExit("result=BLOCKED reason=g3_s1_evidence_contract")
PY

[[ -n "$asset_root" && -d "$asset_root" ]] || {
  echo "result=BLOCKED reason=asset_root_missing" >&2; exit 2;
}
asset_root="$(realpath "$asset_root")"
policy_path="$asset_root/policy.onnx"
calibrator_path="$asset_root/calibrator.onnx"
context_root="$asset_root/context-routes"
command_root="$asset_root/command-routes"
command_manifest="$command_root/manifest.json"
p30_path="$asset_root/p30.json"
reference_path="$asset_root/reference.npz"
require_hash "$policy_path" "$expected_policy_sha256" policy
require_hash "$calibrator_path" "$expected_calibrator_sha256" calibrator
require_hash "$context_root/policy.context-router.onnx" "$expected_context_router_sha256" context_router
require_hash "$command_manifest" "$expected_command_manifest_sha256" command_manifest
require_hash "$p30_path" "$expected_p30_sha256" p30_fit
require_hash "$reference_path" "$expected_reference_sha256" reference
config_path="$(realpath "$config_path")"
imu_calibration="$(realpath "$imu_calibration")"
require_hash "$config_path" "$expected_config_sha256" config
require_hash "$imu_calibration" "$expected_imu_sha256" imu_calibration

[[ -c "$device" ]] || { echo "result=BLOCKED reason=serial_device_missing" >&2; exit 2; }
[[ -c "$controller_device" && -r "$controller_uniq_path" ]] || {
  echo "result=BLOCKED reason=controller_missing" >&2; exit 2;
}
controller_uniq="$(tr '[:upper:]' '[:lower:]' < "$controller_uniq_path" | tr -d '[:space:]')"
[[ "$controller_uniq" == "$expected_controller_uniq" ]] || {
  echo "result=BLOCKED reason=wrong_controller" >&2; exit 2;
}
[[ "$(tr -d '[:space:]' < /sys/devices/system/cpu/isolated)" == "7" ]] || {
  echo "result=BLOCKED reason=cpu7_not_isolated" >&2; exit 2;
}
if command -v fuser >/dev/null 2>&1 && fuser "$device" >/dev/null 2>&1; then
  echo "result=BLOCKED reason=serial_device_owned" >&2
  exit 2
fi
[[ -n "$output_dir" ]] || { echo "result=BLOCKED reason=output_dir_required" >&2; exit 2; }
output_dir="$(realpath -m "$output_dir")"
[[ ! -e "$output_dir" ]] || { echo "result=BLOCKED reason=output_exists" >&2; exit 2; }
mkdir -p "$output_dir"

governor_original="$(tr -d '[:space:]' < "$governor_policy/scaling_governor")"
cleanup() {
  if [[ -n "$active_runtime_pid" ]] && kill -0 "$active_runtime_pid" 2>/dev/null; then
    kill -TERM "$active_runtime_pid" 2>/dev/null || true
    wait "$active_runtime_pid" 2>/dev/null || true
  fi
  if [[ "$governor_changed" -eq 1 ]]; then
    printf '%s\n' "$governor_original" > "$governor_policy/scaling_governor" || true
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
printf '%s\n' performance > "$governor_policy/scaling_governor"
governor_changed=1
[[ "$(tr -d '[:space:]' < "$governor_policy/scaling_governor")" == performance ]] || {
  echo "result=BLOCKED reason=performance_governor_failed" >&2; exit 2;
}

runtime_command=(
  taskset -c 0-7 env "PYTHONPATH=$source_root/src" "$venv_python"
  -m open_duck_x5.runtime
  --bus serial --device "$device" --baudrate 1000000 --timeout-ms 4
  --config "$config_path" --imu-calibration "$imu_calibration"
  --policy "$policy_path" --policy-contract t247-command-routed-115
  --calibrator "$calibrator_path" --context-route-root "$context_root"
  --command-route-root "$command_root" --command-route-manifest "$command_manifest"
  --p30-fit "$p30_path" --reference-table "$reference_path"
  --controller xbox --fixed-command-x 0
  --telemetry "$output_dir/control.jsonl"
  --max-active-ticks 850 --max-ticks 3850 --home-seconds 5 --watchdog-failures 3
  --require-realtime --rt-cpu 7 --rt-priority 80
  --grounded-guard-suspended-revalidation
  --gate5-authorized --hardware-authorized --suspended-or-benched
)
printf '%q ' "${runtime_command[@]}" > "$output_dir/runtime-command.txt"
printf '\n' >> "$output_dir/runtime-command.txt"
set +e
(cd "$source_root" && exec "${runtime_command[@]}") > "$output_dir/runtime-stdout.txt" \
  2> "$output_dir/runtime-stderr.txt" &
active_runtime_pid=$!
wait "$active_runtime_pid"
runtime_status=$?
active_runtime_pid=""
set -e

set +e
PYTHONPATH="$source_root/src" "$venv_python" -m open_duck_x5.torque_off_readback \
  --bus serial --device "$device" --repository-commit "$(git -C "$source_root" rev-parse HEAD)" \
  --output "$output_dir/torque-off-readback.json" \
  --hardware-authorized --suspended-or-benched \
  > "$output_dir/readback-stdout.txt" 2> "$output_dir/readback-stderr.txt"
readback_status=$?
PYTHONPATH="$source_root/src" "$venv_python" -m open_duck_x5.control_summary \
  --input "$output_dir/control.jsonl" --output "$output_dir/summary.json" \
  > "$output_dir/summary-stdout.txt" 2> "$output_dir/summary-stderr.txt"
summary_status=$?
set -e

"$venv_python" - "$output_dir/control.jsonl" "$output_dir/summary.json" \
  "$output_dir/torque-off-readback.json" "$output_dir/candidate-review.json" <<'PY'
import json
import math
import sys
from pathlib import Path

control, summary_path, readback_path, output = map(Path, sys.argv[1:])
events = {}
guard_ticks = 0
for line in control.read_text(encoding="utf-8").splitlines():
    record = json.loads(line)
    if record.get("schema_version") == "open_duck_x5.runtime_event.v1":
        events.setdefault(record["event"], []).append(record)
    elif record.get("schema_version") == "open_duck_x5.control_tick.v1":
        guard = record.get("grounded_safety")
        if guard and guard.get("mode") == "suspended-revalidation":
            guard_ticks += 1
summary = json.loads(summary_path.read_text(encoding="utf-8"))
readback = json.loads(readback_path.read_text(encoding="utf-8"))
grounded = events.get("grounded_readiness", [{}])[0].get("details", {})
timing = summary.get("timing", {}).get("tick_period_ms", {})
bus = summary.get("bus", {})
checks = {
    "runtime_complete": summary.get("run_status") == "COMPLETE",
    "grounded_readiness_exact": len(events.get("grounded_readiness", [])) == 1
    and grounded.get("status") == "PASS"
    and grounded.get("goal_position_writes") == 0
    and grounded.get("torque_enabled") is False,
    "startup_readiness_exact": len(events.get("startup_readiness", [])) == 1,
    "no_guard_trip": not events.get("grounded_safety_trip"),
    "guard_all_ticks": guard_ticks == summary.get("ticks"),
    "active_ticks": summary.get("active_policy_ticks") == 850,
    "timing": timing.get("p99", math.inf) <= 21.0
    and timing.get("p99_9", math.inf) <= 22.0,
    "bus": bus.get("bus_total_ms", {}).get("max", math.inf) < 5.0
    and bus.get("transaction_failure_rate", 1.0) < 0.001
    and bus.get("read_burst_count") == 0,
    "telemetry": summary.get("telemetry_records_dropped") == 0,
    "torque_off": readback.get("status") == "PASS"
    and readback.get("checks", {}).get("all_14_torque_enable_registers_zero") is True,
}
value = {
    "schema_version": "open_duck_x5.g3_s1_candidate_review.v1",
    "status": "COMPLETE_REVIEW_REQUIRED" if all(checks.values()) else "HOLD",
    "checks": checks,
    "operator_observation_required": True,
    "automatic_grounded_follow_on": False,
}
output.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
raise SystemExit(0 if all(checks.values()) else 3)
PY
candidate_status=$?

printf '%s\n' "$governor_original" > "$governor_policy/scaling_governor"
governor_changed=0
(
  cd "$output_dir"
  find . -type f ! -name sha256sums.txt -print0 | sort -z | xargs -0 sha256sum
) > "$output_dir/sha256sums.txt"
if [[ -n "${SUDO_USER:-}" && "$SUDO_USER" != root ]]; then
  chown -R "$SUDO_USER:$(id -gn "$SUDO_USER")" "$output_dir"
fi

if [[ "$runtime_status" -eq 0 && "$readback_status" -eq 0 && \
      "$summary_status" -eq 0 && "$candidate_status" -eq 0 ]]; then
  echo "result=COMPLETE_REVIEW_REQUIRED output_dir=$output_dir"
  exit 0
fi
echo "result=HALTED_REVIEW_REQUIRED runtime=$runtime_status readback=$readback_status summary=$summary_status candidate=$candidate_status output_dir=$output_dir"
exit 3
