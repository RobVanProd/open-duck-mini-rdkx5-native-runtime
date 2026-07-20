#!/usr/bin/env bash
set -euo pipefail

core="${1:-7}"

echo "Recommended kernel arguments for the dedicated control CPU:"
echo "isolcpus=${core}"
echo "The stock X5 6.1.83 kernel reports CONFIG_NO_HZ_FULL unsupported and"
echo "rcu_nocbs unknown; do not claim those settings without a different kernel."
echo
echo "Current kernel command line:"
cat /proc/cmdline
echo
echo "Kernel-reported isolated CPUs:"
if [[ -r /sys/devices/system/cpu/isolated ]]; then
  cat /sys/devices/system/cpu/isolated
else
  echo "UNAVAILABLE"
fi
echo
echo "This script does not edit bootloader files. Record the X5 image's bootloader path first."
