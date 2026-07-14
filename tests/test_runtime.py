from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import numpy as np

from open_duck_x5.controller import ControllerReadout
from open_duck_x5.runtime import Runtime, main


def test_mock_runtime_starts_paused_and_exits_cleanly(tmp_path: Path) -> None:
    config = Path(__file__).parents[1] / "duck_config.example.json"
    telemetry = tmp_path / "control.jsonl"
    assert (
        main(
            [
                "--bus",
                "mock",
                "--config",
                str(config),
                "--telemetry",
                str(telemetry),
                "--home-seconds",
                "0.001",
                "--max-ticks",
                "3",
            ]
        )
        == 0
    )
    records = [json.loads(line) for line in telemetry.read_text(encoding="utf-8").splitlines()]
    ticks = [record for record in records if record["schema_version"].endswith("control_tick.v1")]
    events = [record for record in records if record["schema_version"].endswith("runtime_event.v1")]
    assert len(ticks) == 3
    assert all(record["paused"] for record in ticks)
    assert all(not record["observation_valid"] for record in ticks)
    assert len(events) == 1
    assert events[0]["event"] == "runtime_halt"
    assert events[0]["reason"] == "normal_exit"
    assert isinstance(events[0]["timestamp_monotonic_ns"], int)


def test_runtime_rejects_unsafe_startup_arguments_before_opening_bus(
    tmp_path: Path,
) -> None:
    config = Path(__file__).parents[1] / "duck_config.example.json"
    assert (
        main(
            [
                "--bus",
                "mock",
                "--config",
                str(config),
                "--telemetry",
                str(tmp_path / "never.jsonl"),
                "--home-seconds",
                "0",
                "--max-ticks",
                "1",
            ]
        )
        == 2
    )
    assert not (tmp_path / "never.jsonl").exists()


def test_runtime_pauses_when_physical_controller_sample_is_stale() -> None:
    class StaleController:
        @staticmethod
        def read_into(output: ControllerReadout) -> None:
            output.commands.fill(0.0)
            output.pause_toggle = False
            output.phase_frequency_factor = 1.0
            output.timestamp_ns = 1
            output.connected = True

    runtime = object.__new__(Runtime)
    runtime.controller = StaleController()
    runtime.controller_readout = ControllerReadout()
    runtime.commands = np.zeros(7, dtype=np.float64)
    runtime.args = Namespace(fixed_command_x=None, controller="xbox")
    runtime.paused = False
    runtime.policy = object()

    runtime._update_controller(250_000_002)

    assert runtime.paused is True
