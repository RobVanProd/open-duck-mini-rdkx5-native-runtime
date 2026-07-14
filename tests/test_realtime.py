from __future__ import annotations

from types import SimpleNamespace

import pytest

from open_duck_x5 import realtime


class FakeScheduler:
    def __init__(self) -> None:
        self.control_tid = 100
        self.affinities = {
            100: {0, 1, 2, 3, 4, 5},
            101: {0, 1, 2, 3, 4, 5},
        }
        self.schedulers = {100: 0, 101: 0}
        self.priorities = {100: 0, 101: 0}

    def get_affinity(self, tid: int) -> set[int]:
        return set(self.affinities[self.control_tid if tid == 0 else tid])

    def set_affinity(self, tid: int, cpus: set[int]) -> None:
        self.affinities[self.control_tid if tid == 0 else tid] = set(cpus)

    def set_scheduler(self, tid: int, policy: int, parameter: SimpleNamespace) -> None:
        actual_tid = self.control_tid if tid == 0 else tid
        self.schedulers[actual_tid] = policy
        self.priorities[actual_tid] = int(parameter.sched_priority)

    def get_scheduler(self, tid: int) -> int:
        return self.schedulers[self.control_tid if tid == 0 else tid]

    def get_parameter(self, tid: int) -> SimpleNamespace:
        actual_tid = self.control_tid if tid == 0 else tid
        return SimpleNamespace(sched_priority=self.priorities[actual_tid])

    def thread_state(self) -> tuple[realtime.ThreadAffinity, ...]:
        return tuple(
            realtime.ThreadAffinity(
                tid=tid,
                affinity=tuple(sorted(affinity)),
                scheduler=self.schedulers[tid],
                priority=self.priorities[tid],
            )
            for tid, affinity in sorted(self.affinities.items())
        )


def test_cpu_list_parser_uses_exact_ids_and_expands_ranges() -> None:
    parsed = realtime.parse_cpu_list("0-3,5,10-11")

    assert parsed == {0, 1, 2, 3, 5, 10, 11}
    assert 1 not in realtime.parse_cpu_list("10")


def test_cpu_list_parser_rejects_reversed_range() -> None:
    with pytest.raises(ValueError, match="invalid CPU range"):
        realtime.parse_cpu_list("5-3")


def install_fake_scheduler(
    monkeypatch: pytest.MonkeyPatch, scheduler: FakeScheduler
) -> None:
    monkeypatch.setattr(realtime, "_require_linux_scheduler", lambda: None)
    monkeypatch.setattr(realtime, "isolated_cpus", lambda: {5})
    monkeypatch.setattr(realtime.os, "cpu_count", lambda: 6)
    monkeypatch.setattr(
        realtime.os, "get_native_id", lambda: scheduler.control_tid, raising=False
    )
    monkeypatch.setattr(
        realtime.os, "sched_getaffinity", scheduler.get_affinity, raising=False
    )
    monkeypatch.setattr(
        realtime.os, "sched_setaffinity", scheduler.set_affinity, raising=False
    )
    monkeypatch.setattr(realtime.os, "sched_setscheduler", scheduler.set_scheduler, raising=False)
    monkeypatch.setattr(
        realtime.os, "sched_getscheduler", scheduler.get_scheduler, raising=False
    )
    monkeypatch.setattr(
        realtime.os, "sched_getparam", scheduler.get_parameter, raising=False
    )
    monkeypatch.setattr(
        realtime.os,
        "sched_param",
        lambda priority: SimpleNamespace(sched_priority=priority),
        raising=False,
    )
    monkeypatch.setattr(realtime.os, "SCHED_FIFO", 1, raising=False)
    monkeypatch.setattr(realtime, "process_thread_state", scheduler.thread_state)


def test_realtime_partition_keeps_all_background_threads_off_control_cpu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scheduler = FakeScheduler()
    install_fake_scheduler(monkeypatch, scheduler)

    preparation = realtime.prepare_realtime(cpu=5)

    assert preparation.initial_affinity == (0, 1, 2, 3, 4, 5)
    assert preparation.housekeeping_affinity == (0, 1, 2, 3, 4)
    assert scheduler.affinities[100] == {0, 1, 2, 3, 4}
    assert scheduler.affinities[101] == {0, 1, 2, 3, 4}

    # Simulate a sensor/logger/ONNX worker created after preparation. It inherits
    # the current main-thread housekeeping mask.
    scheduler.affinities[102] = set(scheduler.affinities[100])
    scheduler.schedulers[102] = 0
    scheduler.priorities[102] = 0
    state = realtime.configure_realtime(preparation=preparation, priority=80)

    assert state.affinity == (5,)
    assert state.scheduler == "SCHED_FIFO"
    assert state.priority == 80
    assert scheduler.affinities[100] == {5}
    assert all(5 not in thread.affinity for thread in state.background_threads)
    assert {thread.tid for thread in state.background_threads} == {101, 102}


def test_realtime_rejects_service_pinned_only_to_control_cpu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scheduler = FakeScheduler()
    scheduler.affinities[100] = {5}
    scheduler.affinities.pop(101)
    scheduler.schedulers.pop(101)
    scheduler.priorities.pop(101)
    install_fake_scheduler(monkeypatch, scheduler)

    with pytest.raises(realtime.RealtimeSetupError, match="no housekeeping CPU"):
        realtime.prepare_realtime(cpu=5)


def test_realtime_verification_rejects_background_thread_on_control_cpu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scheduler = FakeScheduler()
    install_fake_scheduler(monkeypatch, scheduler)
    preparation = realtime.prepare_realtime(cpu=5)
    scheduler.affinities[101] = {0, 5}

    with pytest.raises(realtime.RealtimeSetupError, match="background threads.*101"):
        realtime.configure_realtime(preparation=preparation, priority=80)
