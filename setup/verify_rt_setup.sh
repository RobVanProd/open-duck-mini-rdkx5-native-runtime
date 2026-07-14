#!/usr/bin/env bash
set -euo pipefail

core="${1:-5}"
priority="${2:-80}"
failed=0

isolated=""
if [[ -r /sys/devices/system/cpu/isolated ]]; then
  isolated="$(cat /sys/devices/system/cpu/isolated)"
fi
echo "kernel=$(uname -r)"
echo "requested_core=${core}"
echo "requested_priority=${priority}"
echo "isolated_cpus=${isolated:-NONE}"
echo "cmdline=$(cat /proc/cmdline)"

if ! [[ -d "/sys/devices/system/cpu/cpu${core}" ]]; then
  echo "result=FAIL reason=cpu_missing"
  exit 2
fi

python3 - "${core}" "${priority}" <<'PY' || failed=1
import os
import sys
from pathlib import Path

core = int(sys.argv[1])
priority = int(sys.argv[2])
if not 1 <= priority <= 99:
    raise RuntimeError(f"SCHED_FIFO priority {priority} is outside 1..99")


def parse_cpu_list(text: str) -> set[int]:
    cpus: set[int] = set()
    for raw_component in text.strip().split(","):
        component = raw_component.strip()
        if not component:
            continue
        if "-" in component:
            start_text, end_text = component.split("-", 1)
            start, end = int(start_text), int(end_text)
            if end < start:
                raise RuntimeError(f"invalid isolated CPU range {component!r}")
            cpus.update(range(start, end + 1))
        else:
            cpus.add(int(component))
    return cpus


isolated_path = Path("/sys/devices/system/cpu/isolated")
isolated = parse_cpu_list(isolated_path.read_text() if isolated_path.is_file() else "")
if core not in isolated:
    raise RuntimeError(f"control CPU {core} is not exactly present in isolated CPUs {sorted(isolated)}")
print(f"isolation_test=PASS isolated={sorted(isolated)}")

initial = set(os.sched_getaffinity(0))
print(f"current_affinity={sorted(initial)}")
print(f"current_scheduler={os.sched_getscheduler(0)}")
print(f"current_priority={os.sched_getparam(0).sched_priority}")
if core not in initial:
    raise RuntimeError(f"control CPU {core} is excluded from initial service affinity")
housekeeping = initial - {core}
if not housekeeping:
    raise RuntimeError("no housekeeping CPU remains; do not pin the service only to control CPU")
print(f"housekeeping_affinity={sorted(housekeeping)}")
try:
    os.sched_setaffinity(0, {core})
    print(f"affinity_test=PASS affinity={sorted(os.sched_getaffinity(0))}")
    os.sched_setscheduler(0, os.SCHED_FIFO, os.sched_param(priority))
    actual_scheduler = os.sched_getscheduler(0)
    actual_priority = os.sched_getparam(0).sched_priority
    if actual_scheduler != os.SCHED_FIFO or actual_priority < priority:
        raise RuntimeError(
            "SCHED_FIFO verification failed: "
            f"scheduler={actual_scheduler} priority={actual_priority}"
        )
    print(
        "scheduler_test=PASS "
        f"scheduler=SCHED_FIFO priority={actual_priority}"
    )
except Exception as exc:
    print(f"rt_test=FAIL error={exc!r}")
    raise
PY

if [[ "${failed}" -ne 0 ]]; then
  echo "result=FAIL"
  exit 2
fi
echo "result=PASS"
