from __future__ import annotations

import gc
import os
from dataclasses import dataclass
from pathlib import Path


class RealtimeSetupError(RuntimeError):
    pass


def parse_cpu_list(value: str) -> set[int]:
    cpus: set[int] = set()
    for component in value.strip().split(","):
        component = component.strip()
        if not component:
            continue
        if "-" in component:
            start_text, end_text = component.split("-", 1)
            start, end = int(start_text), int(end_text)
            if end < start:
                raise ValueError(f"invalid CPU range: {component}")
            cpus.update(range(start, end + 1))
        else:
            cpus.add(int(component))
    return cpus


def isolated_cpus() -> set[int]:
    path = Path("/sys/devices/system/cpu/isolated")
    if not path.exists():
        return set()
    return parse_cpu_list(path.read_text(encoding="utf-8"))


@dataclass(frozen=True, slots=True)
class RealtimeState:
    cpu: int
    scheduler: str
    priority: int
    isolated: bool
    affinity: tuple[int, ...]


def configure_realtime(
    *, cpu: int, priority: int = 80, require_isolated: bool = True
) -> RealtimeState:
    if os.name != "posix" or not hasattr(os, "sched_setscheduler"):
        raise RealtimeSetupError("SCHED_FIFO setup is supported only on Linux")
    available = set(range(os.cpu_count() or 0))
    if cpu not in available:
        raise RealtimeSetupError(f"CPU {cpu} does not exist; available CPUs: {sorted(available)}")
    isolated = cpu in isolated_cpus()
    if require_isolated and not isolated:
        raise RealtimeSetupError(f"CPU {cpu} is not listed in /sys/devices/system/cpu/isolated")
    try:
        os.sched_setaffinity(0, {cpu})
        os.sched_setscheduler(0, os.SCHED_FIFO, os.sched_param(priority))
    except PermissionError as exc:
        raise RealtimeSetupError(
            "cannot set SCHED_FIFO/affinity; configure CAP_SYS_NICE or rtprio limits"
        ) from exc
    affinity = tuple(sorted(os.sched_getaffinity(0)))
    policy = os.sched_getscheduler(0)
    actual_priority = os.sched_getparam(0).sched_priority
    if policy != os.SCHED_FIFO or affinity != (cpu,) or actual_priority < priority:
        raise RealtimeSetupError(
            "RT verification failed: "
            f"policy={policy}, priority={actual_priority}, affinity={affinity}"
        )
    gc.disable()
    return RealtimeState(
        cpu=cpu,
        scheduler="SCHED_FIFO",
        priority=actual_priority,
        isolated=isolated,
        affinity=affinity,
    )
