#!/usr/bin/env bash
set -euo pipefail

device="${1:-/dev/ttyS1}"
tty="$(basename "${device}")"
sys="/sys/class/tty/${tty}/device"

if [[ ! -e "${device}" ]]; then
  echo "result=FAIL reason=device_missing device=${device}" >&2
  exit 2
fi
if [[ ! -e "${sys}" ]]; then
  echo "result=FAIL reason=sysfs_missing path=${sys}" >&2
  exit 2
fi

resolved="$(readlink -f "${sys}")"
driver="UNKNOWN"
if [[ -L "${sys}/driver" ]]; then
  driver="$(basename "$(readlink -f "${sys}/driver")")"
elif [[ -L "${sys}/../driver" ]]; then
  driver="$(basename "$(readlink -f "${sys}/../driver")")"
fi

echo "device=${device}"
echo "sysfs=${resolved}"
echo "driver=${driver}"
echo "kernel=$(uname -r)"
echo "permissions=$(stat -c '%A %U %G' "${device}")"

udevadm info --query=property --name="${device}" | grep -E '^(ID_VENDOR_ID|ID_MODEL_ID|ID_SERIAL|ID_PATH)=' || true

latency_path="$(find "${resolved}" -maxdepth 3 -name latency_timer -print -quit 2>/dev/null || true)"
if [[ -n "${latency_path}" ]]; then
  echo "latency_timer_path=${latency_path}"
  echo "latency_timer_value=$(cat "${latency_path}")"
  echo "latency_timer_support=SUPPORTED"
else
  echo "latency_timer_support=UNSUPPORTED"
fi
echo "result=PASS"
