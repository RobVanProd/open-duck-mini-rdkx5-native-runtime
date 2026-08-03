#!/usr/bin/env bash
set -euo pipefail

readonly expected_source_commit="655d510872d8ca08067389bd819e4354c497454e"
readonly expected_source_tree="850f013937a4ab4c9c2c9824744407e5d312b938"
readonly expected_schema_tree="55580397a2d01bd6f76417f57a92c4dddee7f642"
readonly expected_pyproject_blob="c5599cd5bbe11f7884ff663307712edb7b7b4751"
readonly expected_preregistration_sha256="a2cf248f8a83aef32f864065837c09db00975bf380634c29915584ccfb8986ad"
readonly expected_attempt2_sha256="df44adc999e578fe600d257fbef6b6f5aeaf43153b4e67e88c9db0d98b066ad8"
readonly expected_controller_mac="0C:35:26:2A:B8:0B"
readonly expected_controller_uniq="0c:35:26:2a:b8:0b"
readonly expected_controller_modalias="usb:v045Ep0B13d0515"
readonly controller_device="/dev/input/js0"
readonly controller_uniq_path="/sys/class/input/js0/device/uniq"
readonly ticks="3000"
readonly frequency_hz="50"
readonly venv_python="/home/sunrise/duck_env/bin/python"
readonly runner_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

source_root=""
output_dir=""
hardware_authorized=0
suspended_or_benched=0

usage() {
  cat <<'EOF'
Usage: setup/run_grounded_controller_stop_operator_return.sh \
  --source-root /home/sunrise/open-duck-x5-controller-stop-operator-return \
  --output-dir /home/sunrise/duck-evidence/controller-b-stop-operator-return-YYYYMMDD \
  --hardware-authorized --suspended-or-benched

One-shot controller-only B-button mapping attempt after the operator returned.
It opens /dev/input/js0 only and has no serial, servo, torque, policy, or motion
path.
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

if [[ "$hardware_authorized" -ne 1 || "$suspended_or_benched" -ne 1 ]]; then
  echo "result=BLOCKED reason=missing_operator_return_hardware_acknowledgements" >&2
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
  echo "result=BLOCKED reason=frozen_operator_return_source_mismatch" >&2
  exit 2
fi
if ! git -C "$source_root" merge-base --is-ancestor "$expected_source_commit" HEAD; then
  echo "result=BLOCKED reason=operator_return_source_commit_not_ancestor" >&2
  exit 2
fi
require_hash \
  "$source_root/artifacts/gates/grounded_validation/CONTROLLER_B_STOP_OPERATOR_RETURN_PREREGISTRATION_20260802.json" \
  "$expected_preregistration_sha256" "operator_return_preregistration"
require_hash \
  "$source_root/artifacts/gates/grounded_validation/CONTROLLER_B_STOP_NO_SERVO_ATTEMPT2_OPERATOR_UNAVAILABLE_20260802.json" \
  "$expected_attempt2_sha256" "attempt2_operator_unavailable_receipt"

if [[ -z "$output_dir" ]]; then
  echo "result=BLOCKED reason=output_dir_required" >&2
  exit 2
fi
output_dir="$(realpath -m "$output_dir")"
if [[ -e "$output_dir" ]]; then
  echo "result=BLOCKED reason=refuse_existing_output_dir" >&2
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

mkdir -p "$output_dir"
printf '%s\n' "$(git -C "$source_root" rev-parse HEAD)" > "$output_dir/source-commit.txt"
printf '%s\n' "$controller_info" > "$output_dir/controller-before.txt"
printf '%s\n' "$controller_uniq" > "$output_dir/controller-uniq-before.txt"
printf '%s\n' "cue=GO_PRESS_B_ONCE do_not_press_A" | tee "$output_dir/operator-cue.txt"

set +e
(
  cd "$source_root"
  env "PYTHONPATH=$source_root/src" "$venv_python" \
    -m open_duck_x5.controller_stop_probe \
    --controller xbox --ticks "$ticks" --frequency-hz "$frequency_hz" \
    --output "$output_dir/controller.jsonl" --summary "$output_dir/summary.json" \
    --hardware-authorized --suspended-or-benched
) > >(tee "$output_dir/probe-stdout.txt") 2> >(tee "$output_dir/probe-stderr.txt" >&2)
probe_status=$?
set -e

bluetoothctl info "$expected_controller_mac" > "$output_dir/controller-after.txt" 2>&1 || true
if [[ -r "$controller_uniq_path" ]]; then
  tr '[:upper:]' '[:lower:]' < "$controller_uniq_path" | tr -d '[:space:]' > "$output_dir/controller-uniq-after.txt"
else
  printf 'missing\n' > "$output_dir/controller-uniq-after.txt"
fi

validation_status=1
if [[ "$probe_status" -eq 0 ]]; then
  set +e
  "$venv_python" - \
    "$output_dir/summary.json" "$output_dir/controller.jsonl" \
    "$output_dir/validation.json" "$output_dir/controller-uniq-after.txt" \
    "$expected_controller_uniq" <<'PY'
import json
import sys
from pathlib import Path

summary_path, trace_path, output_path, uniq_path = map(Path, sys.argv[1:5])
expected_uniq = sys.argv[5]
summary = json.loads(summary_path.read_text(encoding="utf-8"))
records = [
    json.loads(line)
    for line in trace_path.read_text(encoding="utf-8").splitlines()
    if line
]
ages = [float(record["sample_age_ms"]) for record in records]
uniq_after = uniq_path.read_text(encoding="utf-8").strip()
checks = {
    "summary_pass": summary.get("status") == "PASS" and summary.get("failure") is None,
    "trace_count": len(records) == summary.get("ticks_recorded"),
    "tick_cap": 1 <= len(records) <= 3000,
    "sample_check_field_complete": all(
        "sample_checked_monotonic_ns" in record for record in records
    ),
    "sample_age_nonnegative": bool(ages) and min(ages) >= 0.0,
    "sample_age_at_most_250_ms": bool(ages) and max(ages) <= 250.0,
    "one_b_edge": summary.get("emergency_stop_events") == 1,
    "zero_a_edges": summary.get("pause_toggle_events") == 0,
    "zero_disconnect_or_stale": summary.get("disconnect_or_stale_events") == 0,
    "controller_identity_after": uniq_after == expected_uniq,
    "hardware_acknowledgements": summary.get("hardware_authorized") is True
    and summary.get("suspended_or_benched") is True,
    "serial_access_false": summary.get("serial_access") is False,
    "servo_access_false": summary.get("servo_access") is False,
    "torque_enabled_false": summary.get("torque_enabled") is False,
    "policy_loaded_false": summary.get("policy_loaded") is False,
    "motion_false": summary.get("motion") is False,
}
payload = {
    "schema_version": "open_duck_x5.controller_b_stop_operator_return_validation.v1",
    "status": "PASS" if all(checks.values()) else "FAIL",
    "checks": checks,
    "sample_age_ms": {"min": min(ages), "max": max(ages)} if ages else None,
    "controller_uniq_after": uniq_after,
    "automatic_follow_on": False,
    "suspended_cutoff_test_authorized": False,
    "grounded_motion_authorized": False,
}
output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
raise SystemExit(0 if all(checks.values()) else 3)
PY
  validation_status=$?
  set -e
fi

"$venv_python" - "$output_dir/metadata.json" "$probe_status" "$validation_status" <<'PY'
import json
import sys
from pathlib import Path

output, probe, validation = sys.argv[1:]
payload = {
    "schema_version": "open_duck_x5.controller_b_stop_operator_return_run.v1",
    "probe_exit_status": int(probe),
    "validation_status": int(validation),
    "serial_access": False,
    "servo_access": False,
    "torque_enabled": False,
    "policy_loaded": False,
    "motion": False,
    "automatic_follow_on": False,
    "suspended_cutoff_test_authorized": False,
    "grounded_motion_authorized": False,
}
Path(output).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

find "$output_dir" -maxdepth 1 -type f ! -name sha256sums.txt -print0 | sort -z | xargs -0 sha256sum > "$output_dir/sha256sums.txt"

final_status="$probe_status"
if [[ "$validation_status" -ne 0 ]]; then final_status=3; fi
echo "result=$([[ "$final_status" -eq 0 ]] && echo COMPLETE || echo HALTED)"
echo "probe_exit_status=$probe_status"
echo "validation_status=$validation_status"
echo "output_dir=$output_dir"
exit "$final_status"
