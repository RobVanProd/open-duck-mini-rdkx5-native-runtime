#!/usr/bin/env bash
set -euo pipefail

device="/dev/ttyACM0"
ticks=50
output_dir=""
config=""
hardware_authorized=0
suspended_or_benched=0

usage() {
  cat <<'EOF'
Usage: sudo setup/capture_usbmon_torque_off.sh \
  --output-dir DIR [--device /dev/ttyACM0] [--ticks 50] [--config FILE] \
  --hardware-authorized --suspended-or-benched

Captures usbmon and preallocated application transaction timestamps around the
all-14 torque-off timing probe. This script has no torque-enable or motion path.
Start the external logic analyzer before invoking it; correlate captures with
the round-robin extended-read servo ID recorded for every tick.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --device)
      device="$2"
      shift 2
      ;;
    --ticks)
      ticks="$2"
      shift 2
      ;;
    --output-dir)
      output_dir="$2"
      shift 2
      ;;
    --config)
      config="$2"
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
      echo "unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ "${EUID}" -ne 0 ]]; then
  echo "result=BLOCKED reason=root_required_for_usbmon_and_sched_fifo" >&2
  exit 2
fi
if [[ "${hardware_authorized}" -ne 1 || "${suspended_or_benched}" -ne 1 ]]; then
  echo "result=BLOCKED reason=missing_hardware_acknowledgements" >&2
  exit 2
fi
if [[ -z "${output_dir}" ]]; then
  echo "result=BLOCKED reason=output_dir_required" >&2
  exit 2
fi
if ! [[ "${ticks}" =~ ^[0-9]+$ ]] || [[ "${ticks}" -lt 2 ]]; then
  echo "result=BLOCKED reason=invalid_tick_count" >&2
  exit 2
fi
if [[ ! -c "${device}" ]]; then
  echo "result=BLOCKED reason=serial_device_missing device=${device}" >&2
  exit 2
fi
if [[ -n "${config}" && ! -f "${config}" ]]; then
  echo "result=BLOCKED reason=config_missing config=${config}" >&2
  exit 2
fi
if command -v fuser >/dev/null 2>&1 && fuser "${device}" >/dev/null 2>&1; then
  echo "result=BLOCKED reason=serial_device_owned device=${device}" >&2
  exit 2
fi

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
output_dir="$(realpath -m "${output_dir}")"
mkdir -p "${output_dir}"
for name in timing.jsonl timing-summary.json transaction-trace.jsonl usbmon.txt metadata.json; do
  if [[ -e "${output_dir}/${name}" ]]; then
    echo "result=BLOCKED reason=refuse_overwrite path=${output_dir}/${name}" >&2
    exit 2
  fi
done

capture_pid=""
probe_pid=""
usbmon_was_loaded=0
debugfs_was_mounted=0
cleanup() {
  if [[ -n "${probe_pid}" ]] && kill -0 "${probe_pid}" 2>/dev/null; then
    kill -TERM "${probe_pid}" 2>/dev/null || true
    wait "${probe_pid}" 2>/dev/null || true
  fi
  if [[ -n "${capture_pid}" ]] && kill -0 "${capture_pid}" 2>/dev/null; then
    kill -TERM "${capture_pid}" 2>/dev/null || true
    wait "${capture_pid}" 2>/dev/null || true
  fi
  if [[ "${debugfs_was_mounted}" -eq 0 ]] && mountpoint -q /sys/kernel/debug; then
    umount /sys/kernel/debug 2>/dev/null || true
  fi
  if [[ "${usbmon_was_loaded}" -eq 0 ]] && [[ -d /sys/module/usbmon ]]; then
    modprobe -r usbmon 2>/dev/null || true
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if [[ -d /sys/module/usbmon ]]; then
  usbmon_was_loaded=1
else
  modprobe usbmon
fi

if mountpoint -q /sys/kernel/debug; then
  debugfs_was_mounted=1
else
  mount -t debugfs debugfs /sys/kernel/debug
fi

tty_path="$(readlink -f "/sys/class/tty/$(basename "${device}")/device")"
usb_path="${tty_path}"
while [[ "${usb_path}" != "/" ]]; do
  if [[ -r "${usb_path}/busnum" && -r "${usb_path}/devnum" ]]; then
    break
  fi
  usb_path="$(dirname "${usb_path}")"
done
if [[ ! -r "${usb_path}/busnum" || ! -r "${usb_path}/devnum" ]]; then
  echo "result=BLOCKED reason=usb_parent_not_found tty_path=${tty_path}" >&2
  exit 2
fi
usb_bus="$(tr -d '[:space:]' < "${usb_path}/busnum")"
usb_device="$(tr -d '[:space:]' < "${usb_path}/devnum")"
monitor="/sys/kernel/debug/usb/usbmon/${usb_bus}u"
if [[ ! -r "${monitor}" ]]; then
  echo "result=BLOCKED reason=usbmon_stream_missing stream=${monitor}" >&2
  exit 2
fi

if commit="$(git -C "${repo_dir}" rev-parse HEAD 2>/dev/null)"; then
  :
elif [[ -r "${repo_dir}/SOURCE_COMMIT" ]]; then
  commit="$(tr -d '[:space:]' < "${repo_dir}/SOURCE_COMMIT")"
else
  echo "result=BLOCKED reason=source_commit_unavailable" >&2
  exit 2
fi
if ! [[ "${commit}" =~ ^[0-9a-f]{40}$ ]]; then
  echo "result=BLOCKED reason=invalid_source_commit value=${commit}" >&2
  exit 2
fi
kernel="$(uname -r)"
clock_before="$(python3 -c 'import time; print(f"{time.perf_counter_ns()},{time.monotonic_ns()},{time.time_ns()}")')"

cat "${monitor}" > "${output_dir}/usbmon.txt" &
capture_pid=$!
sleep 0.2

probe_command=(
  taskset -c 0-7
  env "PYTHONPATH=${repo_dir}/src${PYTHONPATH:+:${PYTHONPATH}}"
  python3 -m open_duck_x5.probe
  --bus serial
  --device "${device}"
  --baudrate 1000000
  --timeout-ms 4
  --ticks "${ticks}"
  --frequency-hz 50
  --amplitude-rad 0
  --watchdog-failures 2
  --require-realtime
  --rt-cpu 7
  --rt-priority 80
  --instrument-transactions
  --instrumentation-output "${output_dir}/transaction-trace.jsonl"
  --hardware-authorized
  --suspended-or-benched
  --output "${output_dir}/timing.jsonl"
  --summary "${output_dir}/timing-summary.json"
)
if [[ -n "${config}" ]]; then
  probe_command+=(--config "${config}")
fi

(
  cd "${repo_dir}"
  exec "${probe_command[@]}"
) > "${output_dir}/probe-stdout.txt" 2> "${output_dir}/probe-stderr.txt" &
probe_pid=$!
set +e
wait "${probe_pid}"
probe_status=$?
set -e
probe_pid=""

sleep 0.2
kill -TERM "${capture_pid}" 2>/dev/null || true
wait "${capture_pid}" 2>/dev/null || true
capture_pid=""
clock_after="$(python3 -c 'import time; print(f"{time.perf_counter_ns()},{time.monotonic_ns()},{time.time_ns()}")')"

python3 - "${output_dir}/metadata.json" "${commit}" "${kernel}" "${device}" \
  "${usb_bus}" "${usb_device}" "${ticks}" "${probe_status}" \
  "${clock_before}" "${clock_after}" <<'PY'
import json
import sys
from pathlib import Path

(
    output,
    commit,
    kernel,
    device,
    usb_bus,
    usb_device,
    ticks,
    probe_status,
    clock_before,
    clock_after,
) = sys.argv[1:]

def clock_anchor(value: str) -> dict[str, int]:
    perf, monotonic, realtime = (int(component) for component in value.split(","))
    return {
        "perf_counter_ns": perf,
        "monotonic_ns": monotonic,
        "realtime_ns": realtime,
    }

payload = {
    "schema_version": "open_duck_x5.usbmon_capture.v1",
    "repository_commit": commit,
    "kernel": kernel,
    "serial_device": device,
    "usb_bus": int(usb_bus),
    "usb_device": int(usb_device),
    "ticks_requested": int(ticks),
    "probe_exit_status": int(probe_status),
    "torque_enable_requested": False,
    "moving_gate_authorized": False,
    "clock_anchor_before": clock_anchor(clock_before),
    "clock_anchor_after": clock_anchor(clock_after),
    "logic_analyzer_alignment": "round-robin extended-read servo ID",
}
Path(output).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
PY

sha256sum "${output_dir}"/* > "${output_dir}/sha256sums.txt"
if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
  chown -R "${SUDO_USER}:$(id -gn "${SUDO_USER}")" "${output_dir}"
fi

echo "result=$([[ "${probe_status}" -eq 0 ]] && echo COMPLETE || echo HALTED)"
echo "probe_exit_status=${probe_status}"
echo "usb_bus=${usb_bus}"
echo "usb_device=${usb_device}"
echo "output_dir=${output_dir}"
exit "${probe_status}"
