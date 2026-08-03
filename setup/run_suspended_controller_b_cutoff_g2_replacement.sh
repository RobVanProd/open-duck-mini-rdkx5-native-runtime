#!/usr/bin/env bash
set -euo pipefail

readonly expected_original_launcher_sha256="63eb293fda095a0be977447de3b81e0e3a56de162ebed7cecda9093e802920ce"
readonly expected_replacement_preregistration_sha256="89291c53af4a56e3a12f08ec83df7e5ee392eb307f63abee09b65f6d9f4a50e4"
readonly expected_attempt1_sha256="b1dd37afe181271f0bd2f6e1945b2d9bea363bb10b4832cee2d7cd145099aea1"
readonly keep_awake_interval_s="25"
readonly runner_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

source_root=""
config_path=""
output_dir=""
hardware_authorized=0
suspended_or_benched=0
moving_gate_authorized=0
controller_cutoff_authorized=0
controller_keep_awake_authorized=0
active_launcher_pid=""
keep_awake_cues=0

usage() {
  cat <<'EOF'
Usage: sudo bash setup/run_suspended_controller_b_cutoff_g2_replacement.sh \
  --source-root /home/sunrise/open-duck-x5-controller-cutoff-g2-replacement \
  --config /home/sunrise/duck_config.json \
  --output-dir /home/sunrise/duck-evidence/suspended-controller-b-cutoff-g2-replacement-YYYYMMDD \
  --hardware-authorized --suspended-or-benched --moving-gate-authorized \
  --controller-cutoff-authorized --controller-keep-awake-authorized

Replacement wrapper for the unchanged frozen G2 launcher. The only change is
an operator keep-awake cue every 25 seconds during the torque-off preflight.
At each KEEP AWAKE cue, gently move either stick once and release it to center.
Do not press A. Do not press B until the underlying launcher prints GO.
Controller axes cannot command the robot: this probe loads no policy and sends
only the frozen zero-amplitude home target. There is no grounded path or
automatic retry/follow-on.
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
    --controller-keep-awake-authorized) controller_keep_awake_authorized=1; shift ;;
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

cleanup() {
  if [[ -n "$active_launcher_pid" ]] && kill -0 "$active_launcher_pid" 2>/dev/null; then
    kill -TERM "$active_launcher_pid" 2>/dev/null || true
    wait "$active_launcher_pid" 2>/dev/null || true
    active_launcher_pid=""
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if [[ "$EUID" -ne 0 ]]; then
  echo "result=BLOCKED reason=root_required" >&2
  exit 2
fi
if [[ "$hardware_authorized" -ne 1 || "$suspended_or_benched" -ne 1 || \
      "$moving_gate_authorized" -ne 1 || "$controller_cutoff_authorized" -ne 1 || \
      "$controller_keep_awake_authorized" -ne 1 ]]; then
  echo "result=BLOCKED reason=missing_replacement_hardware_acknowledgements" >&2
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
if [[ -z "$config_path" || ! -f "$config_path" ]]; then
  echo "result=BLOCKED reason=config_missing" >&2
  exit 2
fi
if [[ -z "$output_dir" ]]; then
  echo "result=BLOCKED reason=output_dir_required" >&2
  exit 2
fi
output_dir="$(realpath -m "$output_dir")"
if [[ -e "$output_dir" ]]; then
  echo "result=BLOCKED reason=refuse_existing_output_dir" >&2
  exit 2
fi

require_hash "$source_root/setup/run_suspended_controller_b_cutoff_g2.sh" \
  "$expected_original_launcher_sha256" "original_g2_launcher"
require_hash \
  "$source_root/artifacts/gates/grounded_validation/SUSPENDED_CONTROLLER_B_CUTOFF_G2_REPLACEMENT_PREREGISTRATION_20260802.json" \
  "$expected_replacement_preregistration_sha256" "replacement_preregistration"
require_hash \
  "$source_root/artifacts/gates/grounded_validation/SUSPENDED_CONTROLLER_B_CUTOFF_G2_ATTEMPT1_CONTROLLER_SLEEP_20260802.json" \
  "$expected_attempt1_sha256" "attempt1_review"

original_command=(
  bash "$source_root/setup/run_suspended_controller_b_cutoff_g2.sh"
  --source-root "$source_root"
  --config "$config_path"
  --output-dir "$output_dir"
  --hardware-authorized
  --suspended-or-benched
  --moving-gate-authorized
  --controller-cutoff-authorized
)

echo "operator_action=KEEP_AWAKE_PRELAUNCH move_either_stick_once_then_release"
set +e
"${original_command[@]}" &
active_launcher_pid=$!
set -e
next_cue=$(( $(date +%s) + keep_awake_interval_s ))
while kill -0 "$active_launcher_pid" 2>/dev/null; do
  if [[ -f "$output_dir/cutoff/home-ready.json" ]]; then
    break
  fi
  now="$(date +%s)"
  if [[ "$now" -ge "$next_cue" ]]; then
    keep_awake_cues=$((keep_awake_cues + 1))
    message="operator_action=KEEP_AWAKE cue=${keep_awake_cues} move_either_stick_once_then_release do_not_press_A_or_B"
    echo "$message"
    if [[ -d "$output_dir" ]]; then
      printf '%s\n' "$message" >> "$output_dir/keep-awake-cues.txt"
    fi
    next_cue=$(( now + keep_awake_interval_s ))
  fi
  sleep 0.25
done

set +e
wait "$active_launcher_pid"
launcher_status=$?
set -e
active_launcher_pid=""

if [[ -d "$output_dir" ]]; then
  python3 - "$output_dir/replacement-wrapper-metadata.json" \
    "$launcher_status" "$keep_awake_cues" <<'PY'
import json
import sys
from pathlib import Path

output, launcher_status, keep_awake_cues = sys.argv[1:]
value = {
    "schema_version": "open_duck_x5.suspended_controller_b_cutoff_g2_replacement_wrapper.v1",
    "underlying_launcher_status": int(launcher_status),
    "keep_awake_interval_s": 25,
    "keep_awake_cues_emitted": int(keep_awake_cues),
    "runtime_or_probe_changed": False,
    "policy_loaded": False,
    "grounded_motion_authorized": False,
    "automatic_retry": False,
    "automatic_follow_on": False,
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
fi

echo "replacement_wrapper_status=$launcher_status"
echo "keep_awake_cues_emitted=$keep_awake_cues"
echo "automatic_retry=false"
echo "grounded_motion_authorized=false"
exit "$launcher_status"
