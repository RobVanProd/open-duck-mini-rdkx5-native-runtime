from __future__ import annotations

import json
import signal
from argparse import Namespace
from pathlib import Path

import numpy as np
import pytest
from jsonschema import Draft202012Validator

from open_duck_x5 import runtime as runtime_module
from open_duck_x5.bus.mock import MockSTS3215Bus
from open_duck_x5.controller import ControllerReadout
from open_duck_x5.runtime import Runtime, build_parser, main
from open_duck_x5.safety import SafetyError


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
    root = Path(__file__).parents[1]
    tick_schema = json.loads((root / "schemas/control_tick.schema.json").read_text())
    event_schema = json.loads((root / "schemas/runtime_event.schema.json").read_text())
    assert len(ticks) == 3
    for record in ticks:
        Draft202012Validator(tick_schema).validate(record)
    assert all(record["paused"] for record in ticks)
    assert all(not record["observation_valid"] for record in ticks)
    assert all(not any(record["over_3_75_rad_s"]) for record in ticks)
    assert len(events) == 2
    for record in events:
        Draft202012Validator(event_schema).validate(record)
    assert events[0]["event"] == "runtime_start"
    assert events[0]["details"]["contract_id"].endswith("101x14.v1")
    assert len(events[0]["details"]["config"]["sha256"]) == 64
    assert events[1]["event"] == "runtime_halt"
    assert events[1]["reason"] == "normal_exit"
    assert events[1]["telemetry_records_dropped"] == 0
    assert isinstance(events[1]["timestamp_monotonic_ns"], int)


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


def test_runtime_telemetry_cannot_overwrite_config(tmp_path: Path) -> None:
    source = Path(__file__).parents[1] / "duck_config.example.json"
    config = tmp_path / "duck_config.json"
    original = source.read_bytes()
    config.write_bytes(original)
    assert (
        main(
            [
                "--bus",
                "mock",
                "--config",
                str(config),
                "--telemetry",
                str(config),
                "--max-ticks",
                "1",
            ]
        )
        == 2
    )
    assert config.read_bytes() == original


@pytest.mark.parametrize(
    ("extra_args", "message"),
    [
        ([], "reserved for Gate 5"),
        (["--gate5-authorized"], "requires --policy"),
        (["--gate5-authorized", "--policy", "candidate.onnx"], "finite --max-ticks"),
        (
            [
                "--gate5-authorized",
                "--policy",
                "candidate.onnx",
                "--max-ticks",
                "600",
            ],
            "requires --fixed-command-x",
        ),
        (
            [
                "--gate5-authorized",
                "--policy",
                "candidate.onnx",
                "--max-ticks",
                "900",
                "--fixed-command-x",
                "0",
            ],
            "finite --max-active-ticks",
        ),
        (
            [
                "--gate5-authorized",
                "--policy",
                "candidate.onnx",
                "--max-ticks",
                "600",
                "--max-active-ticks",
                "600",
                "--fixed-command-x",
                "0",
            ],
            "must exceed --max-active-ticks",
        ),
        (
            [
                "--gate5-authorized",
                "--policy",
                "candidate.onnx",
                "--max-ticks",
                "900",
                "--max-active-ticks",
                "600",
                "--fixed-command-x",
                "0",
            ],
            "requires --controller",
        ),
    ],
)
def test_serial_runtime_requires_exact_gate5_scope_before_opening_bus(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    extra_args: list[str],
    message: str,
) -> None:
    config = Path(__file__).parents[1] / "duck_config.example.json"

    def fail_if_opened(*_args, **_kwargs):
        pytest.fail("serial bus opened before Gate 5 scope validation")

    monkeypatch.setattr(runtime_module, "STS3215Bus", fail_if_opened)
    assert (
        main(
            [
                "--bus",
                "serial",
                "--config",
                str(config),
                "--telemetry",
                str(tmp_path / "never.jsonl"),
                "--hardware-authorized",
                "--suspended-or-benched",
                "--require-realtime",
                *extra_args,
            ]
        )
        == 2
    )
    assert message in capsys.readouterr().err
    assert not (tmp_path / "never.jsonl").exists()


def test_serial_gate5_refuses_unpaused_config_before_opening_bus(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    raw_config = json.loads(
        (Path(__file__).parents[1] / "duck_config.example.json").read_text(
            encoding="utf-8"
        )
    )
    raw_config["start_paused"] = False
    config = tmp_path / "unpaused.json"
    config.write_text(json.dumps(raw_config), encoding="utf-8")

    def fail_if_opened(*_args, **_kwargs):
        pytest.fail("serial bus opened with start_paused=false")

    monkeypatch.setattr(runtime_module, "STS3215Bus", fail_if_opened)
    assert (
        main(
            [
                "--bus",
                "serial",
                "--config",
                str(config),
                "--policy",
                str(tmp_path / "candidate.onnx"),
                "--telemetry",
                str(tmp_path / "never.jsonl"),
                "--max-ticks",
                "900",
                "--max-active-ticks",
                "600",
                "--fixed-command-x",
                "0",
                "--controller",
                "xbox",
                "--gate5-authorized",
                "--hardware-authorized",
                "--suspended-or-benched",
                "--require-realtime",
            ]
        )
        == 2
    )
    assert "requires start_paused=true" in capsys.readouterr().err
    assert not (tmp_path / "never.jsonl").exists()


def test_serial_startup_establishes_torque_off_before_sensor_initialization(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []

    class FakeBus:
        def disable_torque(self):
            events.append("disable_torque")
            return runtime_module.ErrorCode.OK

        @staticmethod
        def close() -> None:
            events.append("bus_close")

    def create_bus(*_args, **_kwargs):
        events.append("bus_open")
        return FakeBus()

    def fail_contacts():
        events.append("contacts_open")
        raise RuntimeError("simulated GPIO initialization failure")

    monkeypatch.setattr(runtime_module, "prepare_realtime", lambda **_kwargs: object())
    monkeypatch.setattr(runtime_module, "STS3215Bus", create_bus)
    monkeypatch.setattr(runtime_module, "X5FootContacts", fail_contacts)
    config = Path(__file__).parents[1] / "duck_config.example.json"
    args = build_parser().parse_args(
        [
            "--bus",
            "serial",
            "--config",
            str(config),
            "--policy",
            str(tmp_path / "candidate.onnx"),
            "--telemetry",
            str(tmp_path / "never.jsonl"),
            "--max-ticks",
            "900",
            "--max-active-ticks",
            "600",
            "--fixed-command-x",
            "0",
            "--controller",
            "xbox",
            "--gate5-authorized",
            "--hardware-authorized",
            "--suspended-or-benched",
            "--require-realtime",
        ]
    )

    with pytest.raises(RuntimeError, match="simulated GPIO"):
        Runtime(args)

    assert events[:3] == ["bus_open", "disable_torque", "contacts_open"]
    assert events[-2:] == ["disable_torque", "bus_close"]


def test_runtime_halts_when_physical_controller_sample_is_stale() -> None:
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

    with pytest.raises(SafetyError, match="controller state.*stale"):
        runtime._update_controller(250_000_002)

    assert runtime.paused is False


def test_serial_gate5_controller_is_pause_only_and_command_locked() -> None:
    class NoisyController:
        @staticmethod
        def read_into(output: ControllerReadout) -> None:
            output.commands[:] = (0.1, -0.2, 0.7, 0.3, -0.4, 0.5, -0.6)
            output.pause_toggle = False
            output.phase_frequency_factor = 1.3
            output.timestamp_ns = 10_000
            output.connected = True

    runtime = object.__new__(Runtime)
    runtime.controller = NoisyController()
    runtime.controller_readout = ControllerReadout()
    runtime.commands = np.zeros(7, dtype=np.float64)
    runtime.args = Namespace(
        fixed_command_x=0.08,
        controller="xbox",
        bus="serial",
        gate5_authorized=True,
    )
    runtime.paused = False
    runtime.policy = object()

    runtime._update_controller(10_000)

    np.testing.assert_array_equal(runtime.commands, [0.08, 0, 0, 0, 0, 0, 0])
    assert runtime.controller_readout.phase_frequency_factor == 1.0


def test_total_tick_cap_halts_when_active_policy_target_is_not_reached(
    tmp_path: Path,
) -> None:
    telemetry = tmp_path / "active-target-not-reached.jsonl"
    assert (
        main(
            [
                "--bus",
                "mock",
                "--config",
                str(Path(__file__).parents[1] / "duck_config.example.json"),
                "--telemetry",
                str(telemetry),
                "--home-seconds",
                "0.001",
                "--max-ticks",
                "3",
                "--max-active-ticks",
                "2",
            ]
        )
        == 2
    )
    records = [json.loads(line) for line in telemetry.read_text(encoding="utf-8").splitlines()]
    halt = [record for record in records if record.get("event") == "runtime_halt"]
    assert len(halt) == 1
    assert "active policy target: 0/2" in halt[0]["reason"]


def test_runtime_cleanup_reports_failed_torque_off_and_still_closes_bus() -> None:
    class FailingCutoffBus:
        closed = False

        @staticmethod
        def disable_torque():
            return runtime_module.ErrorCode.IO

        def close(self) -> None:
            self.closed = True

    runtime = object.__new__(Runtime)
    runtime.writer = None
    runtime.controller = None
    runtime.sensor_hub = None
    runtime.bus = FailingCutoffBus()
    bus = runtime.bus
    runtime._gc_was_enabled = False

    with pytest.raises(SafetyError, match="cleanup torque-off failed: io"):
        runtime.close()

    assert bus.closed is True
    assert runtime.bus is None


def test_stop_during_home_move_torques_off_with_signal_reason(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = Path(__file__).parents[1] / "duck_config.example.json"
    telemetry = tmp_path / "signal-control.jsonl"
    args = build_parser().parse_args(
        [
            "--bus",
            "mock",
            "--config",
            str(config),
            "--telemetry",
            str(telemetry),
            "--home-seconds",
            "1",
            "--max-ticks",
            "1",
        ]
    )
    runtime = Runtime(args)
    bus = runtime.bus

    class InterruptingTicker:
        @staticmethod
        def wait() -> tuple[int, int]:
            runtime.request_stop(signal.SIGTERM)
            return (0, 0)

    monkeypatch.setattr(runtime_module, "AbsoluteTicker", InterruptingTicker)
    try:
        with pytest.raises(SafetyError, match="stop requested during home move"):
            runtime.run()
        assert bus.torque_enabled is False
    finally:
        runtime.close()

    records = [json.loads(line) for line in telemetry.read_text(encoding="utf-8").splitlines()]
    halt = [record for record in records if record.get("event") == "runtime_halt"]
    assert len(halt) == 1
    assert halt[0]["reason"] == f"signal:{signal.SIGTERM}"


def test_active_policy_stale_sensor_halts_and_torques_off(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    raw_config = json.loads(
        (Path(__file__).parents[1] / "duck_config.example.json").read_text(
            encoding="utf-8"
        )
    )
    raw_config["start_paused"] = False
    config = tmp_path / "unpaused.json"
    config.write_text(json.dumps(raw_config), encoding="utf-8")
    telemetry = tmp_path / "stale-control.jsonl"
    bus = MockSTS3215Bus(latency_s=0.0)

    class FakePolicy:
        @staticmethod
        def infer(_observation: np.ndarray) -> np.ndarray:
            return np.zeros(14, dtype=np.float32)

    class StaleSensorHub:
        @staticmethod
        def read_into(output, now_ns: int) -> None:
            output.imu_timestamp_ns = now_ns
            output.contacts_timestamp_ns = now_ns
            output.imu_age_ns = 0
            output.contacts_age_ns = 0
            output.imu_stale = True
            output.contacts_stale = False

        @staticmethod
        def close() -> None:
            return None

    monkeypatch.setattr(runtime_module, "MockSTS3215Bus", lambda: bus)
    monkeypatch.setattr(runtime_module, "MockSensorHub", StaleSensorHub)
    monkeypatch.setattr(runtime_module, "OnnxPolicy", lambda _path: FakePolicy())
    (tmp_path / "candidate.onnx").write_bytes(b"fake-onnx-for-runtime-test")

    assert (
        main(
            [
                "--bus",
                "mock",
                "--config",
                str(config),
                "--policy",
                str(tmp_path / "candidate.onnx"),
                "--telemetry",
                str(telemetry),
                "--home-seconds",
                "0.001",
                "--max-ticks",
                "1",
            ]
        )
        == 2
    )
    assert bus.torque_enabled is False
    records = [json.loads(line) for line in telemetry.read_text(encoding="utf-8").splitlines()]
    halt = [record for record in records if record.get("event") == "runtime_halt"]
    assert len(halt) == 1
    assert "observation became stale: imu" in halt[0]["reason"]
