#!/usr/bin/env bash
set -euo pipefail

core="${1:-5}"

echo "Recommended kernel arguments for the dedicated control CPU:"
echo "isolcpus=${core} nohz_full=${core} rcu_nocbs=${core}"
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
