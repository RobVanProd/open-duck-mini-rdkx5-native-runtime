#!/usr/bin/env bash
set -Eeuo pipefail

readonly staging_root_expected="/home/sunrise/open_duck_x5_preflight/t251a5"
readonly rt_cpu=7
readonly rt_priority=80
readonly governor_policy="/sys/devices/system/cpu/cpufreq/policy0"
readonly calibrator_sha256="0f3aebfd9946a6271fdb14adec3d68d556648f270984639d372c973a7d7dc576"
readonly policy_sha256="dadfb446ea7c720f274a15bc65e9171c2e74d715ccfaf58adbb408b6c1365a54"
readonly p30_sha256="a58db8ffc505d2bb64cba7f5618d0e2c65904fc9f9ac37b560a1231e090f5f4f"
readonly reference_sha256="8102d9cd139584816d807ca635bcca6d37fa6b3c455848e00395b6d565968212"

staging_root=""
python_path=""
cpu_authorized=0
no_robot_device_access=0
governor_before=""
governor_changed=0
runner_status=125
restore_status=0
evidence_dir=""

usage() {
  cat <<'EOF'
Usage: sudo bash setup/run_winner_v16_x5_reserved_screen.sh \
  --staging-root /home/sunrise/open_duck_x5_preflight/t251a5 \
  --python /home/sunrise/open_duck_x5_preflight/t251a5/venv/bin/python \
  --x5-cpu-screen-authorized --no-robot-device-access

Runs only the preregistered T251A5 synthetic-state semantic and single-host
target timing screen. It exposes no serial, sensor, controller, GPIO, I2C,
servo, torque, or motion path and restores the exact prior CPU governor.
EOF
}

while (($#)); do
  case "$1" in
    --staging-root)
      staging_root="${2:-}"
      shift 2
      ;;
    --python)
      python_path="${2:-}"
      shift 2
      ;;
    --x5-cpu-screen-authorized)
      cpu_authorized=1
      shift
      ;;
    --no-robot-device-access)
      no_robot_device_access=1
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

if ((EUID != 0)); then
  echo "result=BLOCKED reason=root_required_for_governor_and_sched_fifo" >&2
  exit 2
fi
if ((cpu_authorized != 1 || no_robot_device_access != 1)); then
  echo "result=BLOCKED reason=missing_cpu_only_acknowledgements" >&2
  exit 2
fi
if [[ "$(uname -s)" != "Linux" || "$(uname -m)" != "aarch64" ]]; then
  echo "result=BLOCKED reason=rdkx5_aarch64_linux_required" >&2
  exit 2
fi
if [[ -z "$staging_root" || -z "$python_path" ]]; then
  echo "result=BLOCKED reason=staging_root_and_python_required" >&2
  exit 2
fi

staging_root="$(realpath -e "$staging_root")"
if [[ ! -x "$python_path" ]]; then
  echo "result=BLOCKED reason=isolated_python_missing path=$python_path" >&2
  exit 2
fi
python_path="$(cd -- "$(dirname -- "$python_path")" && pwd -P)/$(basename -- "$python_path")"
if [[ "$staging_root" != "$staging_root_expected" ]]; then
  echo "result=BLOCKED reason=unpreregistered_staging_root path=$staging_root" >&2
  exit 2
fi
case "$python_path" in
  "$staging_root"/venv/bin/python*) ;;
  *)
    echo "result=BLOCKED reason=python_outside_isolated_venv path=$python_path" >&2
    exit 2
    ;;
esac

readonly source_root="$staging_root/source"
readonly assets_root="$staging_root/assets"
readonly calibrator="$assets_root/calibrator.onnx"
readonly deployment_policy="$assets_root/policy.onnx"
readonly p30_fit="$assets_root/p30.json"
readonly reference_table="$assets_root/reference.npz"
evidence_dir="$staging_root/evidence"
readonly result_path="$evidence_dir/result.json"
readonly raw_path="$evidence_dir/raw-ticks.npz"

if [[ ! -d "$source_root/.git" ]]; then
  echo "result=BLOCKED reason=isolated_source_checkout_missing" >&2
  exit 2
fi
if [[ -e "$evidence_dir" ]]; then
  echo "result=BLOCKED reason=refuse_existing_evidence path=$evidence_dir" >&2
  exit 2
fi
if [[ -n "$(git -C "$source_root" status --porcelain)" ]]; then
  echo "result=BLOCKED reason=isolated_source_checkout_dirty" >&2
  exit 2
fi

verify_asset() {
  local path="$1"
  local expected="$2"
  local label="$3"
  if [[ ! -f "$path" ]]; then
    echo "result=BLOCKED reason=asset_missing asset=$label path=$path" >&2
    exit 2
  fi
  local actual
  actual="$(sha256sum "$path" | awk '{print $1}')"
  if [[ "$actual" != "$expected" ]]; then
    echo "result=BLOCKED reason=asset_hash_mismatch asset=$label actual=$actual" >&2
    exit 2
  fi
}

verify_asset "$calibrator" "$calibrator_sha256" calibrator
verify_asset "$deployment_policy" "$policy_sha256" deployment_policy
verify_asset "$p30_fit" "$p30_sha256" p30_fit
verify_asset "$reference_table" "$reference_sha256" reference_table

if [[ "$(tr -d '[:space:]' < /sys/devices/system/cpu/isolated)" != "7" ]]; then
  echo "result=BLOCKED reason=cpu7_not_exact_isolated_cpu" >&2
  exit 2
fi
for name in scaling_governor scaling_available_governors related_cpus; do
  if [[ ! -r "$governor_policy/$name" ]]; then
    echo "result=BLOCKED reason=cpufreq_field_missing field=$name" >&2
    exit 2
  fi
done
if [[ "$(xargs < "$governor_policy/related_cpus")" != "0 1 2 3 4 5 6 7" ]]; then
  echo "result=BLOCKED reason=unexpected_cpufreq_policy_membership" >&2
  exit 2
fi
if ! grep -qw performance "$governor_policy/scaling_available_governors"; then
  echo "result=BLOCKED reason=performance_governor_unavailable" >&2
  exit 2
fi

mkdir "$evidence_dir"
governor_before="$(tr -d '[:space:]' < "$governor_policy/scaling_governor")"
printf '%s\n' "$governor_before" > "$evidence_dir/governor-before.txt"
cat /sys/devices/system/cpu/isolated > "$evidence_dir/isolated-cpus.txt"
cat "$governor_policy/related_cpus" > "$evidence_dir/related-cpus.txt"
git -C "$source_root" rev-parse HEAD > "$evidence_dir/source-commit.txt"
sha256sum "$calibrator" "$deployment_policy" "$p30_fit" "$reference_table" \
  > "$evidence_dir/asset-sha256sums.txt"

restore_governor() {
  if ((governor_changed == 1)); then
    if ! printf '%s\n' "$governor_before" > "$governor_policy/scaling_governor"; then
      restore_status=1
      return
    fi
    if [[ "$(tr -d '[:space:]' < "$governor_policy/scaling_governor")" != "$governor_before" ]]; then
      restore_status=1
      return
    fi
    governor_changed=0
  fi
}

cleanup() {
  local incoming_status=$?
  trap - EXIT INT TERM
  restore_governor
  if [[ -n "$evidence_dir" && -d "$evidence_dir" ]]; then
    cat "$governor_policy/scaling_governor" > "$evidence_dir/governor-after.txt" || true
    printf '%s\n' "$runner_status" > "$evidence_dir/runner-exit-status.txt"
    printf '%s\n' "$restore_status" > "$evidence_dir/governor-restore-status.txt"
    (
      cd "$evidence_dir"
      find . -maxdepth 1 -type f ! -name sha256sums.txt -printf '%P\0' \
        | sort -z | xargs -0 -r sha256sum > sha256sums.txt
    )
  fi
  if ((incoming_status != 0)); then
    exit "$incoming_status"
  fi
  if ((runner_status != 0 || restore_status != 0)); then
    exit 2
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

printf '%s\n' performance > "$governor_policy/scaling_governor"
governor_changed=1
if [[ "$(tr -d '[:space:]' < "$governor_policy/scaling_governor")" != "performance" ]]; then
  echo "result=BLOCKED reason=performance_governor_verification_failed" >&2
  exit 2
fi
cat "$governor_policy/scaling_governor" > "$evidence_dir/governor-during.txt"

set +e
taskset -c "$rt_cpu" chrt -f "$rt_priority" \
  "$python_path" "$source_root/tools/run_winner_v16_x5_reserved_screen.py" \
  --staging-root "$staging_root" \
  --calibrator "$calibrator" \
  --policy "$deployment_policy" \
  --p30-fit "$p30_fit" \
  --reference-table "$reference_table" \
  --output "$result_path" \
  --raw-output "$raw_path" \
  > "$evidence_dir/runner-stdout.txt" \
  2> "$evidence_dir/runner-stderr.txt"
runner_status=$?
set -e

if ((runner_status != 0)); then
  echo "result=HOLD reason=t251a5_runner_failed status=$runner_status" >&2
  exit "$runner_status"
fi
echo "result=COMPLETE evidence=$evidence_dir"
