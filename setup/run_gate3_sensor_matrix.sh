#!/usr/bin/env bash
set -euo pipefail

readonly expected_source_commit="aac7410f241a5419af2257ba9635e6755d7b5ae8"
readonly expected_archive_sha256="d41e516ec52558ec169c0f8f017d8959aed657a999786ed5e8e7716895ced9a0"
readonly expected_config_sha256="131a7b8fce1107b14f4727562f44f9e17324caf7fc22512ad7115911f050991b"
readonly expected_calibration_profile_sha256="e7518b0df8614c1d399c789fd26aa9888043ebacfccc98ef75a5010a4b8c34be"
readonly expected_calibration_source_sha256="a3552b357dc2d0e6a876c8e8406134ab36fa6e88a7b7f444c9f9d25122a9da08"
readonly expected_capture_archive_sha256="7e8189501dbb24ecf0301b86e5c7d787e095aad24a634a3a599b7e5d8cd864cb"
readonly expected_smbus2_version="0.6.1"
readonly samples="250"
readonly frequency_hz="50"
readonly sensor_frequency_hz="100"
readonly stale_after_ms="40"
readonly initial_sample_ready_timeout_s="2.0"
readonly imu_bus="5"
readonly imu_address="0x28"
readonly -a labels=(
  upright
  nose_forward
  nose_back
  left_tilt
  right_tilt
  no_contacts
  left_contact
  right_contact
  both_contacts
)

source_archive=""
config_path=""
calibration_dir=""
output_dir=""
hardware_authorized=0
suspended_or_benched=0
work_dir=""
active_probe_pid=""
evidence_started=0
evidence_finished=0
completed_labels=""

usage() {
  cat <<'EOF'
Usage: setup/run_gate3_sensor_matrix.sh \
  --source-archive /home/sunrise/open-duck-x5-gate3-<commit>.tar.gz \
  --config /home/sunrise/duck_config.json \
  --calibration-dir /home/sunrise/gate3/calibration-20260718 \
  --output-dir /home/sunrise/gate3/sensor-matrix-20260718-readybarrier \
  --hardware-authorized --suspended-or-benched

Runs exactly nine interactive, no-servo Gate 3 sensor captures. Before each
five-second capture the operator must physically arrange the supported robot
and type the exact label. Every label's complete evidence is independently
validated before the script permits the next label. The final output remains
REVIEW_REQUIRED and cannot authorize Gate 4.
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
    --calibration-dir)
      calibration_dir="$2"
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

if [[ "${hardware_authorized}" -ne 1 || "${suspended_or_benched}" -ne 1 ]]; then
  echo "result=BLOCKED reason=missing_gate3_hardware_acknowledgements" >&2
  exit 2
fi
if [[ ! -t 0 ]]; then
  echo "result=BLOCKED reason=interactive_operator_terminal_required" >&2
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
if [[ -z "${config_path}" || ! -f "${config_path}" ]]; then
  echo "result=BLOCKED reason=frozen_config_missing" >&2
  exit 2
fi
config_path="$(realpath "${config_path}")"
actual_config_sha256="$(sha256sum "${config_path}" | awk '{print $1}')"
if [[ "${actual_config_sha256}" != "${expected_config_sha256}" ]]; then
  echo "result=BLOCKED reason=frozen_config_hash_mismatch" >&2
  exit 2
fi
if [[ -z "${calibration_dir}" || ! -d "${calibration_dir}" ]]; then
  echo "result=BLOCKED reason=calibration_capture_missing" >&2
  exit 2
fi
calibration_dir="$(realpath "${calibration_dir}")"
if [[ -z "${output_dir}" ]]; then
  echo "result=BLOCKED reason=output_dir_required" >&2
  exit 2
fi
output_dir="$(realpath -m "${output_dir}")"
if [[ -e "${output_dir}" ]]; then
  echo "result=BLOCKED reason=refuse_existing_output_dir path=${output_dir}" >&2
  exit 2
fi
if [[ ! -c /dev/i2c-5 ]]; then
  echo "result=BLOCKED reason=i2c_device_missing device=/dev/i2c-5" >&2
  exit 2
fi
if command -v fuser >/dev/null 2>&1 && fuser /dev/i2c-5 >/dev/null 2>&1; then
  echo "result=BLOCKED reason=i2c_device_owned device=/dev/i2c-5" >&2
  exit 2
fi
actual_smbus2_version="$(python3 -c 'import importlib.metadata; print(importlib.metadata.version("smbus2"))')"
if [[ "${actual_smbus2_version}" != "${expected_smbus2_version}" ]]; then
  echo "result=BLOCKED reason=smbus2_version_mismatch value=${actual_smbus2_version}" >&2
  exit 2
fi

work_dir="$(mktemp -d /tmp/open-duck-gate3.XXXXXX)"

cleanup() {
  if [[ -n "${active_probe_pid}" ]] && kill -0 "${active_probe_pid}" 2>/dev/null; then
    kill -TERM "${active_probe_pid}" 2>/dev/null || true
    wait "${active_probe_pid}" 2>/dev/null || true
    active_probe_pid=""
  fi
  if [[ -n "${work_dir}" && -d "${work_dir}" ]]; then
    case "${work_dir}" in
      /tmp/open-duck-gate3.*)
        rm -rf -- "${work_dir}"
        ;;
      *)
        echo "result=HALTED reason=unsafe_work_dir path=${work_dir}" >&2
        return 1
        ;;
    esac
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

tar -xzf "${source_archive}" -C "${work_dir}"

PYTHONPATH="${work_dir}/src" python3 -m open_duck_x5.imu_calibration_review \
  --capture-dir "${calibration_dir}" \
  --expected-config-sha256 "${expected_config_sha256}" \
  --output "${work_dir}/calibration-review.json" \
  > "${work_dir}/calibration-review-stdout.txt"

actual_profile_sha256="$(sha256sum "${calibration_dir}/imu_calibration.json" | awk '{print $1}')"
actual_source_sha256="$(sha256sum "${calibration_dir}/imu_calib_data.pkl" | awk '{print $1}')"
if [[ "${actual_profile_sha256}" != "${expected_calibration_profile_sha256}" || \
      "${actual_source_sha256}" != "${expected_calibration_source_sha256}" ]]; then
  echo "result=BLOCKED reason=calibration_identity_mismatch" >&2
  exit 2
fi
review_capture_archive="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["capture_archive_sha256"])' "${work_dir}/calibration-review.json")"
if [[ "${review_capture_archive}" != "${expected_capture_archive_sha256}" ]]; then
  echo "result=BLOCKED reason=calibration_capture_archive_mismatch" >&2
  exit 2
fi

mkdir -p "${output_dir}"
evidence_started=1
cp -a -- "${calibration_dir}" "${output_dir}/calibration"
cp -- "${work_dir}/calibration-review.json" "${output_dir}/calibration-review.json"
printf '%s\n' "${expected_source_commit}" > "${output_dir}/source-commit.txt"
printf '%s  %s\n' "${actual_archive_sha256}" "${source_archive}" \
  > "${output_dir}/source-archive-sha256.txt"
printf '%s  %s\n' "${actual_config_sha256}" "${config_path}" \
  > "${output_dir}/config-sha256.txt"
printf '%s\n' "${actual_smbus2_version}" > "${output_dir}/smbus2-version.txt"

label_instruction() {
  case "$1" in
    upright) echo "Place the supported robot upright and motionless." ;;
    nose_forward) echo "Tilt the supported robot nose-forward and hold it motionless." ;;
    nose_back) echo "Tilt the supported robot nose-back and hold it motionless." ;;
    left_tilt) echo "Tilt the supported robot to its left and hold it motionless." ;;
    right_tilt) echo "Tilt the supported robot to its right and hold it motionless." ;;
    no_contacts) echo "Release both foot-contact switches." ;;
    left_contact) echo "Press only the physical left foot-contact switch." ;;
    right_contact) echo "Press only the physical right foot-contact switch." ;;
    both_contacts) echo "Press both foot-contact switches." ;;
  esac
}

write_metadata() {
  local status="$1"
  python3 - "${output_dir}/runner-metadata.json" "${status}" \
    "${expected_source_commit}" "${actual_archive_sha256}" \
    "${actual_config_sha256}" "${actual_profile_sha256}" \
    "${actual_source_sha256}" "${actual_smbus2_version}" \
    "${initial_sample_ready_timeout_s}" "${completed_labels}" <<'PY'
import json
import sys
from pathlib import Path

(
    output,
    status,
    source_commit,
    archive_sha256,
    config_sha256,
    profile_sha256,
    calibration_source_sha256,
    smbus2_version,
    initial_sample_ready_timeout_s,
    completed_labels,
) = sys.argv[1:]
payload = {
    "schema_version": "open_duck_x5.gate3_sensor_matrix_runner.v1",
    "status": status,
    "source_commit": source_commit,
    "source_archive_sha256": archive_sha256,
    "config_sha256": config_sha256,
    "calibration_profile_sha256": profile_sha256,
    "calibration_source_sha256": calibration_source_sha256,
    "smbus2_version": smbus2_version,
    "required_labels": [
        "upright",
        "nose_forward",
        "nose_back",
        "left_tilt",
        "right_tilt",
        "no_contacts",
        "left_contact",
        "right_contact",
        "both_contacts",
    ],
    "completed_labels": [label for label in completed_labels.split(",") if label],
    "samples_per_label": 250,
    "frequency_hz": 50.0,
    "sensor_frequency_hz": 100.0,
    "stale_after_ms": 40.0,
    "initial_sample_ready_timeout_s": float(initial_sample_ready_timeout_s),
    "servo_bus_accessed": False,
    "torque_enabled": False,
    "goal_position_writes": 0,
    "policy_loaded": False,
    "policy_inference_count": 0,
}
Path(output).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
PY
}

finish_evidence() {
  local status="$1"
  if [[ "${evidence_started}" -ne 1 || "${evidence_finished}" -eq 1 ]]; then
    return
  fi
  write_metadata "${status}"
  (
    cd "${output_dir}"
    find . -type f ! -name sha256sums.txt -print0 | sort -z | xargs -0 sha256sum
  ) > "${output_dir}/sha256sums.txt"
  evidence_finished=1
}

for label in "${labels[@]}"; do
  printf '\n%s\n' "$(label_instruction "${label}")"
  printf 'Type exactly "%s" when the physical state is ready: ' "${label}"
  IFS= read -r confirmed_label
  if [[ "${confirmed_label}" != "${label}" ]]; then
    finish_evidence "HALTED_OPERATOR_LABEL_MISMATCH"
    echo "result=HALTED reason=operator_label_mismatch expected=${label}" >&2
    exit 3
  fi

  label_dir="${output_dir}/${label}"
  mkdir "${label_dir}"
  PYTHONPATH="${work_dir}/src" python3 -m open_duck_x5.sensor_probe \
    --backend x5 \
    --label "${label}" \
    --operator-confirmed-label "${label}" \
    --config "${config_path}" \
    --imu-calibration "${output_dir}/calibration/imu_calibration.json" \
    --samples "${samples}" \
    --frequency-hz "${frequency_hz}" \
    --sensor-frequency-hz "${sensor_frequency_hz}" \
    --stale-after-ms "${stale_after_ms}" \
    --imu-bus "${imu_bus}" \
    --imu-address "${imu_address}" \
    --hardware-authorized \
    --suspended-or-benched \
    --output "${label_dir}/sensor.jsonl" \
    --summary "${label_dir}/summary.json" \
    > "${label_dir}/probe-stdout.txt" \
    2> "${label_dir}/probe-stderr.txt" &
  active_probe_pid=$!
  set +e
  wait "${active_probe_pid}"
  probe_status=$?
  set -e
  active_probe_pid=""
  if [[ "${probe_status}" -ne 0 ]]; then
    finish_evidence "HALTED_SENSOR_PROBE"
    echo "result=HALTED stage=${label} probe_status=${probe_status}" >&2
    exit 3
  fi

  set +e
  PYTHONPATH="${work_dir}/src" python3 -m open_duck_x5.gate3_label_validation \
    --run-root "${output_dir}" \
    --label "${label}" \
    > "${label_dir}/integrity-review.json" \
    2> "${label_dir}/integrity-review-stderr.txt"
  validation_status=$?
  set -e
  if [[ "${validation_status}" -ne 0 ]]; then
    finish_evidence "HALTED_LABEL_VALIDATION"
    echo "result=HALTED stage=${label} validation_status=${validation_status}" >&2
    exit 3
  fi
  if [[ -z "${completed_labels}" ]]; then
    completed_labels="${label}"
  else
    completed_labels="${completed_labels},${label}"
  fi
  echo "label=${label} result=DATA_INTEGRITY_ACCEPTED physical_review=REQUIRED"
done

set +e
PYTHONPATH="${work_dir}/src" python3 -m open_duck_x5.gate3_validation \
  --run-root "${output_dir}" \
  --output "${output_dir}/gate3-review.json" \
  > "${output_dir}/gate3-validator-stdout.txt" \
  2> "${output_dir}/gate3-validator-stderr.txt"
final_validation_status=$?
set -e
if [[ "${final_validation_status}" -ne 0 ]]; then
  finish_evidence "HALTED_MATRIX_VALIDATION"
  echo "result=HALTED stage=matrix_validation status=${final_validation_status}" >&2
  exit 3
fi

finish_evidence "REVIEW_REQUIRED"
echo "result=REVIEW_REQUIRED"
echo "output_dir=${output_dir}"
echo "gate3_passed=false"
exit 0
