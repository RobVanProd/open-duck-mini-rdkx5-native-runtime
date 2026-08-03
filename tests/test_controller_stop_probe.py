from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from open_duck_x5 import controller_stop_probe as probe
from open_duck_x5.hardware_guard import HardwareAuthorizationError


class FakeTicker:
    def __init__(self, *, period_ns: int) -> None:
        self.period_ns = period_ns
        self.tick = 0

    def wait(self) -> tuple[int, int]:
        self.tick += 1
        return self.tick * self.period_ns, 0


def _args(tmp_path, **overrides):
    values = {
        "controller": "xbox",
        "ticks": 10,
        "frequency_hz": 50.0,
        "output": tmp_path / "controller.jsonl",
        "summary": tmp_path / "summary.json",
        "hardware_authorized": True,
        "suspended_or_benched": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_controller_stop_probe_requires_hardware_acknowledgements(tmp_path) -> None:
    with pytest.raises(HardwareAuthorizationError):
        probe.run_probe(_args(tmp_path, hardware_authorized=False))


def test_controller_stop_probe_accepts_exact_b_edge_without_servo_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    class Controller:
        reads = 0
        closed = False

        def read_into(self, output) -> None:
            self.reads += 1
            output.connected = True
            output.timestamp_ns = self.reads * 20_000_000
            output.pause_toggle = False
            output.emergency_stop = self.reads == 3

        def close(self) -> None:
            self.closed = True

    controller = Controller()
    monkeypatch.setattr(probe, "create_controller", lambda _kind: controller)
    monkeypatch.setattr(probe, "AbsoluteTicker", FakeTicker)

    summary = probe.run_probe(_args(tmp_path))

    assert summary["status"] == "PASS"
    assert summary["emergency_stop_tick"] == 2
    assert summary["emergency_stop_events"] == 1
    assert summary["pause_toggle_events"] == 0
    assert summary["serial_access"] is False
    assert summary["servo_access"] is False
    assert summary["torque_enabled"] is False
    assert summary["motion"] is False
    assert controller.closed is True
    records = [
        json.loads(line)
        for line in (tmp_path / "controller.jsonl").read_text().splitlines()
    ]
    assert len(records) == 3
    assert records[-1]["emergency_stop"] is True


def test_controller_stop_probe_rejects_a_button_instead_of_b(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    class Controller:
        @staticmethod
        def read_into(output) -> None:
            output.connected = True
            output.timestamp_ns = 20_000_000
            output.pause_toggle = True
            output.emergency_stop = False

        @staticmethod
        def close() -> None:
            return None

    monkeypatch.setattr(probe, "create_controller", lambda _kind: Controller())
    monkeypatch.setattr(probe, "AbsoluteTicker", FakeTicker)

    summary = probe.run_probe(_args(tmp_path))

    assert summary["status"] == "FAIL"
    assert summary["failure"] == "wrong_button_a_pause_toggle_observed"
    assert summary["emergency_stop_events"] == 0


def test_controller_stop_probe_refuses_existing_evidence(tmp_path) -> None:
    output = tmp_path / "controller.jsonl"
    output.write_text("preserve\n")

    with pytest.raises(ValueError, match="refuse existing evidence"):
        probe.run_probe(_args(tmp_path, output=output))

    assert output.read_text() == "preserve\n"
