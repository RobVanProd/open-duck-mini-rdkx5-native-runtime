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
class RealtimePreparation:
    cpu: int
    isolated: bool
    initial_affinity: tuple[int, ...]
    housekeeping_affinity: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ThreadAffinity:
    tid: int
    affinity: tuple[int, ...]
    scheduler: int
    priority: int


@dataclass(frozen=True, slots=True)
class RealtimeState:
    cpu: int
    scheduler: str
    priority: int
    isolated: bool
    affinity: tuple[int, ...]
    initial_affinity: tuple[int, ...]
    housekeeping_affinity: tuple[int, ...]
    background_threads: tuple[ThreadAffinity, ...]


def _require_linux_scheduler() -> None:
    required = (
        "sched_getaffinity",
        "sched_setaffinity",
        "sched_getscheduler",
        "sched_getparam",
        "sched_setscheduler",
        "get_native_id",
    )
    if os.name != "posix" or any(not hasattr(os, name) for name in required):
        raise RealtimeSetupError("SCHED_FIFO setup is supported only on Linux")


def process_thread_state() -> tuple[ThreadAffinity, ...]:
    """Read every live userspace thread from procfs using Linux native TIDs."""

    task_root = Path("/proc/self/task")
    try:
        task_paths = tuple(task_root.iterdir())
    except OSError as exc:
        raise RealtimeSetupError(f"cannot enumerate process threads: {exc}") from exc
    states: list[ThreadAffinity] = []
    for task_path in task_paths:
        try:
            tid = int(task_path.name)
        except ValueError:
            continue
        try:
            states.append(
                ThreadAffinity(
                    tid=tid,
                    affinity=tuple(sorted(os.sched_getaffinity(tid))),
                    scheduler=int(os.sched_getscheduler(tid)),
                    priority=int(os.sched_getparam(tid).sched_priority),
                )
            )
        except ProcessLookupError:
            # A background thread can exit between procfs enumeration and inspection.
            continue
        except OSError as exc:
            raise RealtimeSetupError(f"cannot inspect thread {tid}: {exc}") from exc
    return tuple(sorted(states, key=lambda state: state.tid))


def prepare_realtime(
    *, cpu: int, require_isolated: bool = True
) -> RealtimePreparation:
    """Partition existing/future background threads away from the control CPU."""

    _require_linux_scheduler()
    if cpu < 0 or cpu >= (os.cpu_count() or 0):
        raise RealtimeSetupError(f"CPU {cpu} does not exist")
    try:
        initial_affinity = tuple(sorted(os.sched_getaffinity(0)))
    except OSError as exc:
        raise RealtimeSetupError(f"cannot read initial process affinity: {exc}") from exc
    if cpu not in initial_affinity:
        raise RealtimeSetupError(
            f"CPU {cpu} is excluded from the process's initial affinity {initial_affinity}"
        )
    isolated = cpu in isolated_cpus()
    if require_isolated and not isolated:
        raise RealtimeSetupError(f"CPU {cpu} is not listed in /sys/devices/system/cpu/isolated")
    housekeeping = tuple(value for value in initial_affinity if value != cpu)
    if not housekeeping:
        raise RealtimeSetupError(
            "no housekeeping CPU remains; do not pin the whole service to the control CPU"
        )
    control_tid = os.get_native_id()
    try:
        os.sched_setaffinity(0, set(housekeeping))
        # Usually only the main thread exists here. Partition any earlier native
        # runtime threads too, then future threads inherit the housekeeping mask.
        for state in process_thread_state():
            if state.tid != control_tid:
                try:
                    os.sched_setaffinity(state.tid, set(housekeeping))
                except ProcessLookupError:
                    continue
    except (OSError, ValueError) as exc:
        raise RealtimeSetupError(f"cannot reserve housekeeping CPUs: {exc}") from exc
    actual = tuple(sorted(os.sched_getaffinity(0)))
    if actual != housekeeping:
        raise RealtimeSetupError(
            f"housekeeping affinity verification failed: expected {housekeeping}, got {actual}"
        )
    return RealtimePreparation(
        cpu=cpu,
        isolated=isolated,
        initial_affinity=initial_affinity,
        housekeeping_affinity=housekeeping,
    )


def configure_realtime(
    *, preparation: RealtimePreparation, priority: int = 80
) -> RealtimeState:
    _require_linux_scheduler()
    if not 1 <= priority <= 99:
        raise RealtimeSetupError("SCHED_FIFO priority must be in 1..99")
    cpu = preparation.cpu
    try:
        os.sched_setaffinity(0, {cpu})
        os.sched_setscheduler(0, os.SCHED_FIFO, os.sched_param(priority))
    except (OSError, ValueError) as exc:
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
    control_tid = os.get_native_id()
    thread_states = process_thread_state()
    control_states = [state for state in thread_states if state.tid == control_tid]
    if len(control_states) != 1 or control_states[0].affinity != (cpu,):
        raise RealtimeSetupError("control thread is missing from the verified thread partition")
    background = tuple(state for state in thread_states if state.tid != control_tid)
    offenders = [state for state in background if cpu in state.affinity]
    if offenders:
        details = ", ".join(
            f"tid={state.tid}:affinity={state.affinity}" for state in offenders
        )
        raise RealtimeSetupError(
            f"background threads can run on isolated control CPU {cpu}: {details}"
        )
    gc.disable()
    return RealtimeState(
        cpu=cpu,
        scheduler="SCHED_FIFO",
        priority=actual_priority,
        isolated=preparation.isolated,
        affinity=affinity,
        initial_affinity=preparation.initial_affinity,
        housekeeping_affinity=preparation.housekeeping_affinity,
        background_threads=background,
    )
