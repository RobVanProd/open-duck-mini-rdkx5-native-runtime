#!/usr/bin/env bash
set -euo pipefail

device="${1:-/dev/ttyUSB0}"
tty="$(basename "${device}")"
sys="/sys/class/tty/${tty}/device"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo $0 ${device}" >&2
  exit 2
fi
if [[ ! -e "${sys}" ]]; then
  echo "Device sysfs path missing: ${sys}" >&2
  exit 2
fi

resolved="$(readlink -f "${sys}")"
latency_path="$(find "${resolved}" -maxdepth 3 -name latency_timer -print -quit 2>/dev/null || true)"
if [[ -z "${latency_path}" ]]; then
  echo "UNSUPPORTED: ${device} exposes no latency_timer; no rule installed" >&2
  exit 3
fi

rule="/etc/udev/rules.d/99-open-duck-serial-latency.rules"
printf 'SUBSYSTEM=="usb-serial", KERNEL=="%s", ATTR{latency_timer}="1"\n' "${tty}" >"${rule}"
chmod 0644 "${rule}"
udevadm control --reload-rules
echo 1 >"${latency_path}"

value="$(cat "${latency_path}")"
if [[ "${value}" != "1" ]]; then
  echo "Verification failed: ${latency_path}=${value}" >&2
  exit 4
fi
echo "Installed ${rule}; ${latency_path}=1"
