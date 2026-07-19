#!/usr/bin/env bash
set -Eeuo pipefail

readonly expected_source_commit="c6b03ce318f8d427813bef4cc93134f954b102d6"
readonly expected_source_archive_sha256="782cdf283c7557b11f6267b6c0d110d035bb7b1851700736cb85af25313519df"
readonly expected_preflight_module_sha256="473e4b9ff34e2d6d03350a59d8fc2b19749ffb29cba8023bd7dd8516e3a7f9b6"
readonly expected_config_sha256="131a7b8fce1107b14f4727562f44f9e17324caf7fc22512ad7115911f050991b"
readonly expected_policy_envelope_sha256="PENDING_POLICY_ENVELOPE_SHA256"
readonly expected_handoff_manifest_sha256="d771d188218152c782c7d688440e2dd2083b47fd9b883749123f89226c6827c5"
readonly expected_selected_onnx_sha256="99d3afce0dfac127816c6327665c35b3c403e005f25cd0a505dfcb37f01304de"
readonly ticks_per_command=10000
readonly rt_cpu=7
readonly rt_priority=80

handoff_root=""
envelope_path=""
config_path=""
output_dir=""
cpu_authorized=0
no_servo_ack=0

usage() {
  cat <<'EOF'
Usage: sudo setup/run_winner_v2_cpu_preflight.sh \
  --handoff-root PATH --envelope PATH --config PATH --output-dir PATH \
  --x5-cpu-preflight-authorized --no-servo-access

This launcher performs CPU/ONNX work only. It has no serial-device argument and
does not enable torque or communicate with a servo bus.
EOF
}

while (($#)); do
  case "$1" in
    --handoff-root)
      handoff_root="${2:-}"
      shift 2
      ;;
    --envelope)
      envelope_path="${2:-}"
      shift 2
      ;;
    --config)
      config_path="${2:-}"
      shift 2
      ;;
    --output-dir)
      output_dir="${2:-}"
      shift 2
      ;;
    --x5-cpu-preflight-authorized)
      cpu_authorized=1
      shift
      ;;
    --no-servo-access)
      no_servo_ack=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ ! "$expected_policy_envelope_sha256" =~ ^[0-9a-f]{64}$ ]]; then
  echo "blocked: policy envelope SHA-256 is still pending" >&2
  exit 2
fi
if [[ -z "$handoff_root" || -z "$envelope_path" || -z "$config_path" || -z "$output_dir" ]]; then
  echo "blocked: all four paths are required" >&2
  exit 2
fi
if ((cpu_authorized != 1 || no_servo_ack != 1)); then
  echo "blocked: exact CPU-only/no-servo acknowledgements are required" >&2
  exit 2
fi
if ((EUID != 0)); then
  echo "blocked: root is required for SCHED_FIFO and temporary governor control" >&2
  exit 2
fi
if [[ "$(uname -s)" != "Linux" ]]; then
  echo "blocked: the reviewed preflight is Linux/X5-only" >&2
  exit 2
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
handoff_root="$(realpath -e "$handoff_root")"
envelope_path="$(realpath -e "$envelope_path")"
config_path="$(realpath -e "$config_path")"
output_dir="$(realpath -m "$output_dir")"

if [[ "$output_dir" == "$repo_root" || "$output_dir" == "$handoff_root" || "$output_dir" == "$handoff_root/"* ]]; then
  echo "blocked: output directory may not overwrite an input root" >&2
  exit 2
fi

sha256_file() {
  sha256sum "$1" | awk '{print $1}'
}

if ! git -C "$repo_root" cat-file -e "${expected_source_commit}^{commit}"; then
  echo "blocked: frozen preflight source commit is unavailable" >&2
  exit 2
fi
if [[ "$(sha256_file "$repo_root/src/open_duck_x5/winner_v2_cpu_preflight.py")" != "$expected_preflight_module_sha256" ]]; then
  echo "blocked: winner-v2 CPU preflight module identity changed" >&2
  exit 2
fi
if [[ "$(sha256_file "$config_path")" != "$expected_config_sha256" ]]; then
  echo "blocked: duck_config.json identity changed" >&2
  exit 2
fi
if [[ "$(sha256_file "$envelope_path")" != "$expected_policy_envelope_sha256" ]]; then
  echo "blocked: policy envelope identity changed" >&2
  exit 2
fi
if [[ "$(sha256_file "$handoff_root/manifest.json")" != "$expected_handoff_manifest_sha256" ]]; then
  echo "blocked: winner-v2 handoff manifest identity changed" >&2
  exit 2
fi
if [[ "$(sha256_file "$handoff_root/policies/T2_EQUAL_512000.onnx")" != "$expected_selected_onnx_sha256" ]]; then
  echo "blocked: selected winner-v2 ONNX identity changed" >&2
  exit 2
fi

temporary_archive="$(mktemp --suffix=.tar.gz)"
governor_path="/sys/devices/system/cpu/cpufreq/policy0/scaling_governor"
isolated_path="/sys/devices/system/cpu/isolated"
governor_before=""
python_status=125
restore_status=0

cleanup() {
  local incoming_status=$?
  trap - EXIT INT TERM
  rm -f -- "$temporary_archive"
  if [[ -n "$governor_before" && -w "$governor_path" ]]; then
    if ! printf '%s\n' "$governor_before" >"$governor_path"; then
      restore_status=1
    fi
  fi
  if [[ -n "$output_dir" && -d "$output_dir" ]]; then
    if [[ -r "$governor_path" ]]; then
      cat "$governor_path" >"$output_dir/governor-after.txt"
    fi
    python3 - "$output_dir/runner-metadata.json" \
      "$expected_source_commit" "$expected_source_archive_sha256" \
      "$expected_preflight_module_sha256" "$expected_policy_envelope_sha256" \
      "$expected_config_sha256" "$expected_handoff_manifest_sha256" \
      "$expected_selected_onnx_sha256" "$python_status" "$restore_status" <<'PY'
import json
import sys
from pathlib import Path

(
    output,
    source_commit,
    source_archive,
    module_sha,
    envelope_sha,
    config_sha,
    manifest_sha,
    onnx_sha,
    preflight_status,
    restore_status,
) = sys.argv[1:]
payload = {
    "schema_version": "open_duck_x5.winner_v2_cpu_preflight_runner.v1",
    "source_commit": source_commit,
    "source_archive_sha256": source_archive,
    "preflight_module_sha256": module_sha,
    "policy_envelope_sha256": envelope_sha,
    "config_sha256": config_sha,
    "handoff_manifest_sha256": manifest_sha,
    "selected_onnx_sha256": onnx_sha,
    "ticks_per_command": 10000,
    "commands": [0.0, 0.08],
    "rt_cpu": 7,
    "rt_priority": 80,
    "preflight_exit_status": int(preflight_status),
    "governor_restore_status": int(restore_status),
    "review_status": "REVIEW_REQUIRED",
    "no_servo_access": True,
    "robot_clearance": False,
    "gate5": False,
    "motion": False,
    "torque": False,
}
Path(output).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
PY
    (
      cd "$output_dir"
      find . -maxdepth 1 -type f ! -name sha256sums.txt -printf '%P\0' \
        | sort -z \
        | xargs -0 -r sha256sum >sha256sums.txt
    )
  fi
  if ((incoming_status != 0)); then
    exit "$incoming_status"
  fi
  if ((python_status != 0 || restore_status != 0)); then
    exit 2
  fi
}
trap cleanup EXIT INT TERM

git -C "$repo_root" archive --format=tar.gz --output="$temporary_archive" "$expected_source_commit"
if [[ "$(sha256_file "$temporary_archive")" != "$expected_source_archive_sha256" ]]; then
  echo "blocked: deterministic source archive identity changed" >&2
  exit 2
fi
if [[ ! -r "$governor_path" || ! -w "$governor_path" ]]; then
  echo "blocked: policy0 governor is not readable/writable" >&2
  exit 2
fi
if [[ ! -r "$isolated_path" ]] || ! grep -Eq '(^|,|-)7($|,|-)' "$isolated_path"; then
  echo "blocked: CPU 7 is not reported isolated" >&2
  exit 2
fi

mkdir -p "$output_dir"
if find "$output_dir" -mindepth 1 -maxdepth 1 -print -quit | grep -q .; then
  echo "blocked: output directory must be empty" >&2
  exit 2
fi

governor_before="$(tr -d '\n' <"$governor_path")"
printf '%s\n' "$governor_before" >"$output_dir/governor-before.txt"
printf '%s\n' performance >"$governor_path"
cat "$governor_path" >"$output_dir/governor-during.txt"
if [[ "$(tr -d '\n' <"$governor_path")" != "performance" ]]; then
  echo "blocked: performance governor did not verify" >&2
  exit 2
fi
printf '%s\n' "$expected_source_commit" >"$output_dir/source-commit.txt"
printf '%s  %s\n' "$expected_source_archive_sha256" "source.tar.gz" \
  >"$output_dir/source-archive-sha256.txt"

set +e
(
  cd "$repo_root"
  taskset -c "$rt_cpu" chrt -f "$rt_priority" \
    python3 -m open_duck_x5.winner_v2_cpu_preflight \
      --handoff-root "$handoff_root" \
      --envelope "$envelope_path" \
      --expected-envelope-sha256 "$expected_policy_envelope_sha256" \
      --config "$config_path" \
      --expected-config-sha256 "$expected_config_sha256" \
      --ticks-per-command "$ticks_per_command" \
      --samples-output "$output_dir/timing.jsonl" \
      --summary-output "$output_dir/summary.json"
) >"$output_dir/preflight-stdout.txt" 2>"$output_dir/preflight-stderr.txt"
python_status=$?
set -e

if ((python_status != 0)); then
  echo "winner-v2 CPU preflight did not pass; review $output_dir" >&2
  exit 2
fi
echo "winner-v2 CPU preflight candidate complete; independent review required"
