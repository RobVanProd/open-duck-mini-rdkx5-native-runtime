#!/usr/bin/env bash
set -euo pipefail

readonly expected_source_tree="5b39ed62fb0eff71196a2ae90cbd36861cc54d31"
readonly expected_schema_tree="9e8adbd8973973e43a8fc6c80a2d953d090fa2ab"
readonly expected_pyproject_blob="8bd71d3a44276bdb21755d1492a19c57f6c80fe0"
readonly expected_preregistration_sha256="76e025383b50f1fd24b33bd375d85b524fbeaee45efc321b8cb2e56faa915a69"
readonly expected_config_sha256="131a7b8fce1107b14f4727562f44f9e17324caf7fc22512ad7115911f050991b"
readonly expected_imu_sha256="e7518b0df8614c1d399c789fd26aa9888043ebacfccc98ef75a5010a4b8c34be"
readonly expected_policy_sha256="dadfb446ea7c720f274a15bc65e9171c2e74d715ccfaf58adbb408b6c1365a54"
readonly expected_calibrator_sha256="0f3aebfd9946a6271fdb14adec3d68d556648f270984639d372c973a7d7dc576"
readonly expected_command_manifest_sha256="5621f7c6782a8346bf25f05ce7f0bc002acbe8e98872cf658f0d44773511b4cd"
readonly expected_context_manifest_sha256="61c54d755c2846bd811775786c6599606a7be70fbaa7c9266cd3fb613d64a536"
readonly expected_context_router_sha256="3b1f406fba5147a3f38ec59fc7f9c8d42dd27fa7eeb54344f447c060eb95b284"
readonly expected_p30_sha256="a58db8ffc505d2bb64cba7f5618d0e2c65904fc9f9ac37b560a1231e090f5f4f"
readonly expected_reference_sha256="8102d9cd139584816d807ca635bcca6d37fa6b3c455848e00395b6d565968212"
readonly device="/dev/ttyS1"
readonly active_ticks="850"
readonly maximum_total_ticks="3850"
readonly home_seconds="5"
readonly controller="xbox"
readonly governor_policy="/sys/devices/system/cpu/cpufreq/policy0"
readonly runner_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

source_root=""
asset_root=""
config_path=""
imu_calibration=""
output_dir=""
fixed_command_x=""
x0_review=""
x0_review_sha256=""
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
evidence_finished=0

usage() {
  cat <<'EOF'
Usage (one arm only):
  sudo setup/run_t247_gate5_single_arm.sh \
    --source-root /home/sunrise/open-duck-x5-gate5-t247 \
    --asset-root /home/sunrise/open-duck-x5-gate5-t247-assets \
    --config /home/sunrise/duck_config.json \
    --imu-calibration /home/sunrise/gate3/sensor-matrix-20260718-readybarrier/calibration/imu_calibration.json \
    --output-dir /home/sunrise/duck-evidence/gate5-t247-x0-YYYYMMDD \
    --fixed-command-x 0 \
    --hardware-authorized --suspended-or-benched --gate5-moving-authorized

The x=.08 arm additionally requires --x0-review and --x0-review-sha256 for a
separately reviewed PASS_REVIEWED_T247_GATE5_X0 artifact. This launcher never
starts the second arm automatically. Each invocation runs exactly 250 active
calibration ticks followed by 600 locomotion ticks, with a bounded 60-second
paused window, and then restores the original CPU governor.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source-root)
      source_root="$2"
      shift 2
      ;;
    --asset-root)
      asset_root="$2"
      shift 2
      ;;
    --config)
      config_path="$2"
      shift 2
      ;;
    --imu-calibration)
      imu_calibration="$2"
      shift 2
      ;;
    --output-dir)
      output_dir="$2"
      shift 2
      ;;
    --fixed-command-x)
      case "$2" in
        0|0.0) fixed_command_x="0" ;;
        .08|0.08) fixed_command_x="0.08" ;;
        *)
          echo "result=BLOCKED reason=fixed_command_must_be_0_or_0.08" >&2
          exit 2
          ;;
      esac
      shift 2
      ;;
    --x0-review)
      x0_review="$2"
      shift 2
      ;;
    --x0-review-sha256)
      x0_review_sha256="$2"
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
    --gate5-moving-authorized)
      gate5_moving_authorized=1
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

sha256_of() {
  sha256sum "$1" | awk '{print $1}'
}

require_hash() {
  local path="$1"
  local expected="$2"
  local label="$3"
  if [[ ! -f "${path}" ]]; then
    echo "result=BLOCKED reason=${label}_missing path=${path}" >&2
    exit 2
  fi
  local actual
  actual="$(sha256_of "${path}")"
  if [[ "${actual}" != "${expected}" ]]; then
    echo "result=BLOCKED reason=${label}_hash_mismatch actual=${actual}" >&2
    exit 2
  fi
}

if [[ "${EUID}" -ne 0 ]]; then
  echo "result=BLOCKED reason=root_required_for_governor_and_sched_fifo" >&2
  exit 2
fi
if [[ "${hardware_authorized}" -ne 1 || "${suspended_or_benched}" -ne 1 || \
      "${gate5_moving_authorized}" -ne 1 ]]; then
  echo "result=BLOCKED reason=missing_gate5_hardware_acknowledgements" >&2
  exit 2
fi
if [[ -z "${source_root}" || ! -d "${source_root}" ]]; then
  echo "result=BLOCKED reason=source_root_missing" >&2
  exit 2
fi
source_root="$(realpath "${source_root}")"
if [[ "${source_root}" != "${runner_root}" ]]; then
  echo "result=BLOCKED reason=launcher_must_run_from_frozen_source_root" >&2
  exit 2
fi
if ! git -C "${source_root}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "result=BLOCKED reason=source_root_is_not_a_git_worktree" >&2
  exit 2
fi
if [[ -n "$(git -C "${source_root}" status --porcelain --untracked-files=no)" ]]; then
  echo "result=BLOCKED reason=tracked_source_worktree_dirty" >&2
  exit 2
fi
if [[ "$(git -C "${source_root}" rev-parse HEAD:src/open_duck_x5)" != \
      "${expected_source_tree}" || \
      "$(git -C "${source_root}" rev-parse HEAD:schemas)" != \
      "${expected_schema_tree}" || \
      "$(git -C "${source_root}" rev-parse HEAD:pyproject.toml)" != \
      "${expected_pyproject_blob}" ]]; then
  echo "result=BLOCKED reason=frozen_source_tree_mismatch" >&2
  exit 2
fi
require_hash \
  "${source_root}/artifacts/gates/phase_7_hardware/gate_5_policy/T247_LAUNCHER_PREREGISTRATION_20260801.json" \
  "${expected_preregistration_sha256}" "launcher_preregistration"

if [[ -z "${asset_root}" || ! -d "${asset_root}" ]]; then
  echo "result=BLOCKED reason=asset_root_missing" >&2
  exit 2
fi
asset_root="$(realpath "${asset_root}")"
policy_path="${asset_root}/policy.onnx"
calibrator_path="${asset_root}/calibrator.onnx"
p30_path="${asset_root}/p30.json"
reference_path="${asset_root}/reference.npz"
context_root="${asset_root}/context-routes"
command_root="${asset_root}/command-routes"
command_manifest="${command_root}/manifest.json"
require_hash "${policy_path}" "${expected_policy_sha256}" "policy"
require_hash "${calibrator_path}" "${expected_calibrator_sha256}" "calibrator"
require_hash "${p30_path}" "${expected_p30_sha256}" "p30_fit"
require_hash "${reference_path}" "${expected_reference_sha256}" "reference_table"
require_hash "${context_root}/manifest.json" \
  "${expected_context_manifest_sha256}" "context_manifest"
require_hash "${context_root}/policy.context-router.onnx" \
  "${expected_context_router_sha256}" "context_router"
require_hash "${command_manifest}" \
  "${expected_command_manifest_sha256}" "command_manifest"

if [[ -z "${config_path}" ]]; then
  echo "result=BLOCKED reason=config_required" >&2
  exit 2
fi
config_path="$(realpath "${config_path}")"
require_hash "${config_path}" "${expected_config_sha256}" "config"
PYTHONPATH="${source_root}/src" python3 - "${config_path}" <<'PY'
import json
import sys
from pathlib import Path

value = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if value.get("start_paused") is not True:
    raise SystemExit("result=BLOCKED reason=config_start_paused_not_true")
PY

if [[ -z "${imu_calibration}" ]]; then
  echo "result=BLOCKED reason=imu_calibration_required" >&2
  exit 2
fi
imu_calibration="$(realpath "${imu_calibration}")"
require_hash "${imu_calibration}" "${expected_imu_sha256}" "imu_calibration"

if [[ -z "${fixed_command_x}" ]]; then
  echo "result=BLOCKED reason=fixed_command_required" >&2
  exit 2
fi
if [[ "${fixed_command_x}" == "0.08" ]]; then
  if [[ -z "${x0_review}" || -z "${x0_review_sha256}" ]]; then
    echo "result=BLOCKED reason=x008_requires_reviewed_x0_receipt" >&2
    exit 2
  fi
  if [[ ! "${x0_review_sha256}" =~ ^[0-9a-f]{64}$ ]]; then
    echo "result=BLOCKED reason=x0_review_sha256_invalid" >&2
    exit 2
  fi
  x0_review="$(realpath "${x0_review}")"
  require_hash "${x0_review}" "${x0_review_sha256}" "x0_review"
  python3 - "${x0_review}" <<'PY'
import json
import sys
from pathlib import Path

value = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
required = {
    "status": "PASS_REVIEWED_T247_GATE5_X0",
    "candidate_id": "T247_HOME_NEGATIVE_HALF_ADAPTER_FINAL",
    "fixed_command_x_m_s": 0.0,
    "policy_sha256": "dadfb446ea7c720f274a15bc65e9171c2e74d715ccfaf58adbb408b6c1365a54",
}
for key, expected in required.items():
    if value.get(key) != expected:
        raise SystemExit(f"result=BLOCKED reason=x0_review_{key}_mismatch")
if value.get("all_gate5_acceptance_checks_pass") is not True:
    raise SystemExit("result=BLOCKED reason=x0_review_acceptance_not_green")
PY
elif [[ -n "${x0_review}" || -n "${x0_review_sha256}" ]]; then
  echo "result=BLOCKED reason=x0_arm_must_not_consume_prior_review" >&2
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
  if [[ ! -r "${governor_policy}/${name}" ]]; then
    echo "result=BLOCKED reason=cpufreq_field_missing field=${name}" >&2
    exit 2
  fi
done
governor_original="$(tr -d '[:space:]' < "${governor_policy}/scaling_governor")"
if [[ "${governor_original}" != "schedutil" ]]; then
  echo "result=BLOCKED reason=unexpected_initial_governor value=${governor_original}" >&2
  exit 2
fi
if ! grep -qw performance "${governor_policy}/scaling_available_governors"; then
  echo "result=BLOCKED reason=performance_governor_unavailable" >&2
  exit 2
fi
if [[ "$(xargs < "${governor_policy}/related_cpus")" != "0 1 2 3 4 5 6 7" ]]; then
  echo "result=BLOCKED reason=unexpected_cpufreq_policy_membership" >&2
  exit 2
fi
if [[ "$(tr -d '[:space:]' < "${governor_policy}/scaling_min_freq")" != "300000" || \
      "$(tr -d '[:space:]' < "${governor_policy}/scaling_max_freq")" != "1500000" ]]; then
  echo "result=BLOCKED reason=unexpected_cpufreq_range" >&2
  exit 2
fi

mkdir -p "${output_dir}"
git -C "${source_root}" rev-parse HEAD > "${output_dir}/source-commit.txt"
printf '%s\n' "${expected_source_tree}" > "${output_dir}/source-tree.txt"
printf '%s  %s\n' "${expected_config_sha256}" "${config_path}" \
  > "${output_dir}/config-sha256.txt"
printf '%s  %s\n' "${expected_imu_sha256}" "${imu_calibration}" \
  > "${output_dir}/imu-calibration-sha256.txt"
cp "${governor_policy}/scaling_governor" "${output_dir}/governor-before.txt"
cp "${governor_policy}/scaling_min_freq" "${output_dir}/min-frequency-before.txt"
cp "${governor_policy}/scaling_max_freq" "${output_dir}/max-frequency-before.txt"
cp "${governor_policy}/related_cpus" "${output_dir}/related-cpus.txt"

restore_governor() {
  if [[ "${governor_changed}" -eq 1 ]]; then
    printf '%s\n' "${governor_original}" > "${governor_policy}/scaling_governor" || return 1
    if [[ "$(tr -d '[:space:]' < "${governor_policy}/scaling_governor")" != \
          "${governor_original}" ]]; then
      return 1
    fi
    governor_changed=0
  fi
}

cleanup() {
  local cleanup_status=0
  if [[ -n "${active_runtime_pid}" ]] && \
      kill -0 "${active_runtime_pid}" 2>/dev/null; then
    kill -TERM "${active_runtime_pid}" 2>/dev/null || true
    wait "${active_runtime_pid}" 2>/dev/null || true
    active_runtime_pid=""
  fi
  restore_governor || cleanup_status=1
  return "${cleanup_status}"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

printf '%s\n' performance > "${governor_policy}/scaling_governor"
governor_changed=1
if [[ "$(tr -d '[:space:]' < "${governor_policy}/scaling_governor")" != \
      "performance" ]]; then
  echo "result=BLOCKED reason=performance_governor_verification_failed" >&2
  exit 2
fi
cp "${governor_policy}/scaling_governor" "${output_dir}/governor-during.txt"

runtime_command=(
  taskset -c 0-7
  env "PYTHONPATH=${source_root}/src"
  python3 -m open_duck_x5.runtime
  --bus serial
  --device "${device}"
  --baudrate 1000000
  --timeout-ms 4
  --config "${config_path}"
  --policy "${policy_path}"
  --policy-contract t247-command-routed-115
  --calibrator "${calibrator_path}"
  --context-route-root "${context_root}"
  --command-route-root "${command_root}"
  --command-route-manifest "${command_manifest}"
  --p30-fit "${p30_path}"
  --reference-table "${reference_path}"
  --controller "${controller}"
  --fixed-command-x "${fixed_command_x}"
  --telemetry "${output_dir}/control.jsonl"
  --max-active-ticks "${active_ticks}"
  --max-ticks "${maximum_total_ticks}"
  --home-seconds "${home_seconds}"
  --watchdog-failures 3
  --imu-calibration "${imu_calibration}"
  --require-realtime
  --rt-cpu 7
  --rt-priority 80
  --gate5-authorized
  --hardware-authorized
  --suspended-or-benched
)
printf '%q ' "${runtime_command[@]}" > "${output_dir}/runtime-command.txt"
printf '\n' >> "${output_dir}/runtime-command.txt"

(cd "${source_root}" && exec "${runtime_command[@]}") \
  > "${output_dir}/runtime-stdout.txt" \
  2> "${output_dir}/runtime-stderr.txt" &
active_runtime_pid=$!
set +e
wait "${active_runtime_pid}"
runtime_status=$?
set -e
active_runtime_pid=""

restore_status=0
restore_governor || restore_status=1
cat "${governor_policy}/scaling_governor" > "${output_dir}/governor-after.txt"

if [[ -f "${output_dir}/control.jsonl" ]]; then
  set +e
  PYTHONPATH="${source_root}/src" python3 -m open_duck_x5.control_summary \
    --input "${output_dir}/control.jsonl" \
    --output "${output_dir}/summary.json" \
    > "${output_dir}/summary-stdout.txt" \
    2> "${output_dir}/summary-stderr.txt"
  summary_status=$?
  set -e
else
  summary_status=1
  printf '%s\n' "control telemetry was not created" \
    > "${output_dir}/summary-stderr.txt"
fi

if [[ "${summary_status}" -eq 0 ]]; then
  set +e
  python3 - "${output_dir}/summary.json" \
    "${output_dir}/candidate-review.json" "${fixed_command_x}" <<'PY'
import json
import sys
from pathlib import Path

source, output, fixed_x = sys.argv[1:]
summary = json.loads(Path(source).read_text(encoding="utf-8"))
gates = summary.get("gates", {})
checks = {
    "serial_backend": summary.get("backend") == "serial",
    "complete": summary.get("run_status") == "COMPLETE",
    "review_required": summary.get("review_status") == "REVIEW_REQUIRED",
    "active_ticks_exact": summary.get("active_policy_ticks") == 850,
    "fixed_command_exact": summary.get("command", {}).get("fixed_x") == float(fixed_x),
    "all_summary_gates_true": bool(gates) and all(value is True for value in gates.values()),
}
payload = {
    "schema_version": "open_duck_x5.t247_gate5_candidate_review.v1",
    "status": (
        "COMPLETE_T247_GATE5_ARM_REVIEW_REQUIRED"
        if all(checks.values())
        else "HOLD_T247_GATE5_ARM"
    ),
    "fixed_command_x_m_s": float(fixed_x),
    "checks": checks,
    "checks_passed": sum(checks.values()),
    "checks_total": len(checks),
    "failed_checks": [name for name, passed in checks.items() if not passed],
    "automatic_gate_promotion": False,
}
Path(output).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
raise SystemExit(0 if all(checks.values()) else 3)
PY
  candidate_status=$?
  set -e
else
  candidate_status=1
fi

python3 - "${output_dir}/runner-metadata.json" \
  "${runtime_status}" "${summary_status}" "${candidate_status}" \
  "${restore_status}" "${fixed_command_x}" <<'PY'
import json
import sys
from pathlib import Path

output, runtime, summary, candidate, restore, fixed_x = sys.argv[1:]
value = {
    "schema_version": "open_duck_x5.t247_gate5_runner.v1",
    "fixed_command_x_m_s": float(fixed_x),
    "active_ticks": 850,
    "calibration_ticks": 250,
    "locomotion_ticks": 600,
    "maximum_total_ticks": 3850,
    "runtime_status": int(runtime),
    "summary_status": int(summary),
    "candidate_status": int(candidate),
    "governor_restore_status": int(restore),
    "automatic_gate_promotion": False,
    "automatic_x008_advance": False,
}
Path(output).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
PY

(
  cd "${output_dir}"
  find . -type f ! -name sha256sums.txt -print0 | sort -z | xargs -0 sha256sum
) > "${output_dir}/sha256sums.txt"
evidence_finished=1
if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
  chown -R "${SUDO_USER}:$(id -gn "${SUDO_USER}")" "${output_dir}"
fi

if [[ "${runtime_status}" -eq 0 && "${summary_status}" -eq 0 && \
      "${candidate_status}" -eq 0 && "${restore_status}" -eq 0 ]]; then
  echo "result=COMPLETE_REVIEW_REQUIRED"
  echo "fixed_command_x=${fixed_command_x}"
  echo "output_dir=${output_dir}"
  exit 0
fi
echo "result=HALTED_REVIEW_REQUIRED"
echo "runtime_status=${runtime_status}"
echo "summary_status=${summary_status}"
echo "candidate_status=${candidate_status}"
echo "governor_restore_status=${restore_status}"
echo "output_dir=${output_dir}"
exit 3
