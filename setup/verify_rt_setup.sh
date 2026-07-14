#!/usr/bin/env bash
set -euo pipefail

core="${1:-5}"
failed=0

isolated=""
if [[ -r /sys/devices/system/cpu/isolated ]]; then
  isolated="$(cat /sys/devices/system/cpu/isolated)"
fi
echo "kernel=$(uname -r)"
echo "requested_core=${core}"
echo "isolated_cpus=${isolated:-NONE}"
echo "cmdline=$(cat /proc/cmdline)"

if ! [[ -d "/sys/devices/system/cpu/cpu${core}" ]]; then
  echo "result=FAIL reason=cpu_missing"
  exit 2
fi

python3 - "${core}" <<'PY' || failed=1
import os
import sys

core = int(sys.argv[1])
print(f"current_affinity={sorted(os.sched_getaffinity(0))}")
print(f"current_scheduler={os.sched_getscheduler(0)}")
print(f"current_priority={os.sched_getparam(0).sched_priority}")
try:
    os.sched_setaffinity(0, {core})
    print(f"affinity_test=PASS affinity={sorted(os.sched_getaffinity(0))}")
except Exception as exc:
    print(f"affinity_test=FAIL error={exc!r}")
    raise
PY

if [[ "${isolated}" != *"${core}"* ]]; then
  echo "isolation_test=FAIL"
  failed=1
else
  echo "isolation_test=PASS"
fi

if [[ "${failed}" -ne 0 ]]; then
  echo "result=FAIL"
  exit 2
fi
echo "result=PASS"
