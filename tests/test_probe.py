from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator

from open_duck_x5 import probe
from open_duck_x5.probe import main


def test_mock_probe_writes_schema_valid_jsonl_and_summary(tmp_path: Path) -> None:
    output = tmp_path / "timing.jsonl"
    summary_path = tmp_path / "summary.json"
    assert (
        main(
            [
                "--bus",
                "mock",
                "--ticks",
                "12",
                "--mock-latency-ms",
                "0",
                "--output",
                str(output),
                "--summary",
                str(summary_path),
            ]
        )
        == 0
    )
    records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    schema_path = Path(__file__).parents[1] / "schemas" / "timing_tick.schema.json"
    validator = Draft202012Validator(json.loads(schema_path.read_text(encoding="utf-8")))
    assert len(records) == 12
    for record in records:
        validator.validate(record)
        assert len(record["motion"]["target_positions_rad"]) == 14
        assert len(record["motion"]["actual_positions_rad"]) == 14
        assert len(record["motion"]["absolute_error_rad"]) == 14
        assert record["serial"]["per_servo_device_status"] == [0] * 14
        assert record["extended"]["device_status_raw"] == 0

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary_schema_path = Path(__file__).parents[1] / "schemas" / "timing_summary.schema.json"
    summary_schema = json.loads(summary_schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(summary_schema)
    Draft202012Validator(summary_schema).validate(summary)
    assert summary["schema_version"] == "open_duck_x5.timing_summary.v2"
    assert summary["run_status"] == "COMPLETE"
    assert summary["halt_reason"] is None
    assert summary["backend"] == "mock"
    assert summary["informational_only"] is True
    assert summary["ticks"] == 12
    assert summary["transactions_failed"] == 0
    assert summary["device_alarm_reply_count"] == 0
    assert summary["voltage_alarm_reply_count"] == 0
    assert summary["transaction_status_counts"]["ok"] == 12 * 16
    assert summary["transaction_failure_counts"] == {
        "timeout": 0,
        "crc": 0,
        "partial": 0,
        "device": 0,
        "unexpected_id": 0,
        "io": 0,
        "unexpected_packet": 0,
    }
    assert summary["tracking_absolute_error_rad"]["samples"] == 12
    assert summary["jsonl_sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert summary["environment"]["telemetry_records_dropped"] == 0
    assert summary["environment"]["realtime"] is None
    assert summary["environment"]["torque_off_status"] == "ok"
    assert summary["environment"]["home_seconds"] == 2.0
    assert summary["environment"]["controller"] == "none"
    assert summary["environment"]["controller_backend"] is None
    assert summary["gates"]["complete_record_stream"] is True
    assert summary["gates"]["zero_device_alarms"] is True
    assert summary["gates"]["torque_off_confirmed"] is True
    assert summary["gates"]["gate2_home_hold_candidate"] is False
    assert summary["gates"]["gate4_sine_candidate"] is False


def test_probe_refuses_output_summary_collision(tmp_path: Path) -> None:
    collision = tmp_path / "collision.json"
    with pytest.raises(SystemExit):
        main(
            [
                "--bus",
                "mock",
                "--ticks",
                "2",
                "--output",
                str(collision),
                "--summary",
                str(collision),
            ]
        )
    assert not collision.exists()


def test_probe_refuses_physical_controller_on_mock_bus(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        main(
            [
                "--bus",
                "mock",
                "--controller",
                "xbox",
                "--ticks",
                "2",
                "--output",
                str(tmp_path / "timing.jsonl"),
                "--summary",
                str(tmp_path / "summary.json"),
            ]
        )


def test_probe_requires_instrumentation_flag_and_distinct_output(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        main(
            [
                "--bus",
                "mock",
                "--ticks",
                "2",
                "--instrumentation-output",
                str(tmp_path / "trace.jsonl"),
                "--output",
                str(tmp_path / "timing.jsonl"),
                "--summary",
                str(tmp_path / "summary.json"),
            ]
        )

    collision = tmp_path / "trace.jsonl"
    with pytest.raises(SystemExit):
        main(
            [
                "--bus",
                "mock",
                "--ticks",
                "2",
                "--instrument-transactions",
                "--instrumentation-output",
                str(collision),
                "--output",
                str(collision),
                "--summary",
                str(tmp_path / "summary.json"),
            ]
        )


def test_mock_probe_writes_transaction_instrumentation_after_loop(tmp_path: Path) -> None:
    trace = tmp_path / "trace.jsonl"
    assert (
        main(
            [
                "--bus",
                "mock",
                "--ticks",
                "3",
                "--mock-latency-ms",
                "0",
                "--instrument-transactions",
                "--instrumentation-output",
                str(trace),
                "--output",
                str(tmp_path / "timing.jsonl"),
                "--summary",
                str(tmp_path / "summary.json"),
            ]
        )
        == 0
    )
    records = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
    assert [record["tick"] for record in records] == [0, 1, 2]


def test_startup_readiness_requires_a_distinct_result_path(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        main(
            [
                "--bus",
                "mock",
                "--ticks",
                "2",
                "--startup-readiness-exchange",
                "--output",
                str(tmp_path / "timing.jsonl"),
                "--summary",
                str(tmp_path / "summary.json"),
            ]
        )

    collision = tmp_path / "readiness.json"
    with pytest.raises(SystemExit):
        main(
            [
                "--bus",
                "mock",
                "--ticks",
                "2",
                "--startup-readiness-exchange",
                "--startup-readiness-output",
                str(collision),
                "--output",
                str(collision),
                "--summary",
                str(tmp_path / "summary.json"),
            ]
        )


def test_startup_readiness_is_recorded_and_precedes_measured_tick_zero(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class DeterministicTicker:
        instances = 0

        def __init__(self, period_ns: int) -> None:
            type(self).instances += 1
            self.period_ns = period_ns
            self.next_ns = probe.clock_ns()

        def wait(self) -> tuple[int, int]:
            result = self.next_ns
            self.next_ns += self.period_ns
            return result, 0

    monkeypatch.setattr(probe, "AbsoluteTicker", DeterministicTicker)
    readiness_path = tmp_path / "readiness.json"
    summary_path = tmp_path / "summary.json"

    assert (
        main(
            [
                "--bus",
                "mock",
                "--ticks",
                "3",
                "--mock-latency-ms",
                "0",
                "--startup-readiness-exchange",
                "--startup-readiness-output",
                str(readiness_path),
                "--output",
                str(tmp_path / "timing.jsonl"),
                "--summary",
                str(summary_path),
            ]
        )
        == 0
    )

    readiness = json.loads(readiness_path.read_text(encoding="utf-8"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert readiness["status"] == "PASS"
    assert readiness["failures"] == []
    assert DeterministicTicker.instances == 1
    assert readiness["next_measured_tick_period_ms"] == 20.0
    first_tick = json.loads(
        (tmp_path / "timing.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    assert first_tick["tick_period_ms"] == 20.0
    assert summary["startup_readiness"] == readiness
    assert summary["ticks"] == 3
    assert summary["gates"]["startup_readiness_required"] is True
    assert summary["gates"]["startup_readiness_passed"] is True
    assert summary["overall_bus_max_ms"] == max(
        readiness["bus_total_ms"], summary["bus_total_ms"]["max"]
    )


def test_failed_startup_readiness_is_not_retried_or_counted_as_a_measured_tick(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class FirstExchangeFails(probe.MockSTS3215Bus):
        exchange_calls = 0

        def exchange_into(self, targets, snapshot, tick):
            type(self).exchange_calls += 1
            super().exchange_into(targets, snapshot, tick)
            snapshot.status[0] = int(probe.ErrorCode.CRC)
            snapshot.stale[0] = True

    monkeypatch.setattr(probe, "MockSTS3215Bus", FirstExchangeFails)
    readiness_path = tmp_path / "readiness.json"
    summary_path = tmp_path / "summary.json"

    assert (
        main(
            [
                "--bus",
                "mock",
                "--ticks",
                "3",
                "--mock-latency-ms",
                "0",
                "--startup-readiness-exchange",
                "--startup-readiness-output",
                str(readiness_path),
                "--output",
                str(tmp_path / "timing.jsonl"),
                "--summary",
                str(summary_path),
            ]
        )
        == 2
    )

    readiness = json.loads(readiness_path.read_text(encoding="utf-8"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert FirstExchangeFails.exchange_calls == 1
    assert readiness["status"] == "FAIL"
    assert readiness["per_servo_status"][0] == "crc"
    assert summary["ticks"] == 0
    assert summary["run_status"] == "HALTED"
    assert summary["gates"]["startup_readiness_passed"] is False


def test_measured_tick_zero_still_decides_the_unchanged_bus_max_gate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class MeasuredTickZeroFails(probe.MockSTS3215Bus):
        exchange_calls = 0

        def exchange_into(self, targets, snapshot, tick):
            type(self).exchange_calls += 1
            super().exchange_into(targets, snapshot, tick)
            if type(self).exchange_calls == 2:
                snapshot.bus_total_ns = 5_100_000
                snapshot.status[0] = int(probe.ErrorCode.CRC)
                snapshot.stale[0] = True

    monkeypatch.setattr(probe, "MockSTS3215Bus", MeasuredTickZeroFails)
    readiness_path = tmp_path / "readiness.json"
    summary_path = tmp_path / "summary.json"

    assert (
        main(
            [
                "--bus",
                "mock",
                "--ticks",
                "2",
                "--mock-latency-ms",
                "0",
                "--watchdog-failures",
                "2",
                "--startup-readiness-exchange",
                "--startup-readiness-output",
                str(readiness_path),
                "--output",
                str(tmp_path / "timing.jsonl"),
                "--summary",
                str(summary_path),
            ]
        )
        == 0
    )

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert MeasuredTickZeroFails.exchange_calls == 3
    assert summary["startup_readiness"]["status"] == "PASS"
    assert summary["gates"]["startup_readiness_passed"] is True
    assert summary["ticks"] == 2
    assert summary["bus_total_ms"]["max"] == 5.1
    assert summary["overall_bus_max_ms"] == 5.1
    assert summary["gates"]["bus_max_under_5_ms"] is False
    assert summary["gates"]["overall_bus_max_under_5_ms"] is False


def test_controller_is_primed_before_serial_open_and_checked_before_readiness(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []

    class FakeController:
        def read_into(self, output) -> None:
            events.append("controller_read")
            output.connected = True
            output.timestamp_ns = probe.clock_ns()
            output.pause_toggle = False

        @staticmethod
        def close() -> None:
            events.append("controller_close")

    class FakeSerialBus(probe.MockSTS3215Bus):
        def __init__(self, *_args, **_kwargs) -> None:
            events.append("serial_open")
            super().__init__(latency_s=0.0)
            self.device = "/dev/ttyS1"
            self.baudrate = 1_000_000

        def disable_torque(self):
            events.append("torque_off")
            return super().disable_torque()

        def exchange_into(self, targets, snapshot, tick):
            events.append("exchange")
            return super().exchange_into(targets, snapshot, tick)

    def create_controller(_kind: str):
        events.append("controller_open")
        return FakeController()

    def prepare_realtime(**_kwargs):
        events.append("prepare_realtime")
        return SimpleNamespace()

    def configure_realtime(**_kwargs):
        events.append("configure_realtime")
        return SimpleNamespace()

    monkeypatch.setattr(probe, "create_controller", create_controller)
    monkeypatch.setattr(probe, "STS3215Bus", FakeSerialBus)
    monkeypatch.setattr(probe, "prepare_realtime", prepare_realtime)
    monkeypatch.setattr(probe, "configure_realtime", configure_realtime)
    monkeypatch.setattr(probe, "asdict", lambda _value: {"verified": True})

    args = probe.build_parser().parse_args(
        [
            "--bus",
            "serial",
            "--controller",
            "xbox",
            "--require-realtime",
            "--hardware-authorized",
            "--suspended-or-benched",
            "--ticks",
            "2",
            "--startup-readiness-exchange",
            "--startup-readiness-output",
            str(tmp_path / "readiness.json"),
            "--output",
            str(tmp_path / "timing.jsonl"),
            "--summary",
            str(tmp_path / "summary.json"),
        ]
    )
    args.stop_signal = None

    summary = probe.run_probe(args)

    assert summary["run_status"] == "COMPLETE"
    assert events.index("controller_open") < events.index("serial_open")
    first_controller_read = events.index("controller_read")
    assert first_controller_read < events.index("serial_open")
    configure_index = events.index("configure_realtime")
    readiness_index = events.index("exchange")
    assert configure_index < readiness_index
    assert "controller_read" in events[configure_index + 1 : readiness_index]


def test_probe_controller_emergency_stop_trips_immediately() -> None:
    class EmergencyStopController:
        @staticmethod
        def read_into(output) -> None:
            output.connected = True
            output.timestamp_ns = probe.clock_ns()
            output.pause_toggle = False
            output.emergency_stop = True

    readout = probe.ControllerReadout()
    with pytest.raises(probe.WatchdogTrip, match="controller emergency stop"):
        probe._read_controller_or_trip(
            EmergencyStopController(),
            readout,
            reject_toggle=False,
        )


def test_probe_emergency_stop_during_home_entry_disables_torque(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class EmergencyStopController:
        reads = 0

        def read_into(self, output) -> None:
            self.reads += 1
            output.connected = True
            output.timestamp_ns = probe.clock_ns()
            output.pause_toggle = False
            output.emergency_stop = self.reads >= 4

        @staticmethod
        def close() -> None:
            return None

    class FakeSerialBus(probe.MockSTS3215Bus):
        instance = None

        def __init__(self, *_args, **_kwargs) -> None:
            super().__init__(latency_s=0.0)
            self.device = "/dev/ttyS1"
            self.baudrate = 1_000_000
            self.ever_enabled = False
            FakeSerialBus.instance = self

        def enable_torque(self):
            self.ever_enabled = True
            return super().enable_torque()

    monkeypatch.setattr(probe, "create_controller", lambda _kind: EmergencyStopController())
    monkeypatch.setattr(probe, "STS3215Bus", FakeSerialBus)
    monkeypatch.setattr(probe, "prepare_realtime", lambda **_kwargs: SimpleNamespace())
    monkeypatch.setattr(probe, "configure_realtime", lambda **_kwargs: SimpleNamespace())
    monkeypatch.setattr(probe, "asdict", lambda _value: {"verified": True})

    summary = probe.run_probe(
        probe.build_parser().parse_args(
            [
                "--bus",
                "serial",
                "--controller",
                "xbox",
                "--enable-torque",
                "--moving-gate-authorized",
                "--hardware-authorized",
                "--suspended-or-benched",
                "--require-realtime",
                "--config",
                str(Path(__file__).parents[1] / "duck_config.example.json"),
                "--home-seconds",
                "0.1",
                "--ticks",
                "2",
                "--output",
                str(tmp_path / "timing.jsonl"),
                "--summary",
                str(tmp_path / "summary.json"),
            ]
        )
    )

    assert summary["run_status"] == "HALTED"
    assert summary["halt_reason"] == "physical controller emergency stop requested"
    assert summary["gates"]["torque_off_confirmed"] is True
    assert FakeSerialBus.instance is not None
    assert FakeSerialBus.instance.ever_enabled is True
    assert FakeSerialBus.instance.torque_enabled is False


def test_mock_moving_probe_runs_slow_home_path(tmp_path: Path) -> None:
    root = Path(__file__).parents[1]
    output = tmp_path / "moving.jsonl"
    summary_path = tmp_path / "moving-summary.json"
    assert (
        main(
            [
                "--bus",
                "mock",
                "--enable-torque",
                "--config",
                str(root / "duck_config.example.json"),
                "--home-seconds",
                "0.001",
                "--ticks",
                "2",
                "--mock-latency-ms",
                "0",
                "--output",
                str(output),
                "--summary",
                str(summary_path),
            ]
        )
        == 0
    )
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["environment"]["torque_enabled"] is True
    assert summary["environment"]["home_seconds"] == 0.001
    assert len(summary["environment"]["config_sha256"]) == 64


def test_probe_failed_cleanup_torque_off_marks_run_halted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class FailingCutoffBus(probe.MockSTS3215Bus):
        def disable_torque(self):
            super().disable_torque()
            return probe.ErrorCode.IO

    monkeypatch.setattr(probe, "MockSTS3215Bus", FailingCutoffBus)
    summary_path = tmp_path / "summary.json"
    assert (
        main(
            [
                "--bus",
                "mock",
                "--ticks",
                "2",
                "--mock-latency-ms",
                "0",
                "--output",
                str(tmp_path / "timing.jsonl"),
                "--summary",
                str(summary_path),
            ]
        )
        == 2
    )
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["run_status"] == "HALTED"
    assert summary["halt_reason"] == "cleanup torque-off failed: io"
    assert summary["environment"]["torque_off_status"] == "io"
    assert summary["gates"]["torque_off_confirmed"] is False


def test_probe_stop_during_home_move_reaches_torque_off(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bus = probe.MockSTS3215Bus(latency_s=0.0)
    args = probe.build_parser().parse_args(
        [
            "--bus",
            "mock",
            "--enable-torque",
            "--ticks",
            "2",
            "--output",
            str(tmp_path / "signal.jsonl"),
            "--summary",
            str(tmp_path / "signal-summary.json"),
        ]
    )
    args.stop_signal = None

    class InterruptingTicker:
        @staticmethod
        def wait() -> tuple[int, int]:
            args.stop_signal = 15
            return (0, 0)

    monkeypatch.setattr(probe, "MockSTS3215Bus", lambda **_kwargs: bus)
    monkeypatch.setattr(probe, "AbsoluteTicker", InterruptingTicker)
    summary = probe.run_probe(args)

    assert summary["run_status"] == "HALTED"
    assert summary["halt_reason"] == "signal:15"
    assert bus.torque_enabled is False


def test_probe_home_move_hard_overrun_reaches_torque_off(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bus = probe.MockSTS3215Bus(latency_s=0.0)

    class HomeTripWatchdog:
        def __init__(self, **_kwargs: object) -> None:
            pass

        @staticmethod
        def observe(**_kwargs: object) -> None:
            raise probe.WatchdogTrip("hard tick overrun during home")

    monkeypatch.setattr(probe, "MockSTS3215Bus", lambda **_kwargs: bus)
    monkeypatch.setattr(probe, "Watchdog", HomeTripWatchdog)
    args = probe.build_parser().parse_args(
        [
            "--bus",
            "mock",
            "--enable-torque",
            "--home-seconds",
            "0.001",
            "--ticks",
            "2",
            "--mock-latency-ms",
            "0",
            "--output",
            str(tmp_path / "overrun.jsonl"),
            "--summary",
            str(tmp_path / "overrun-summary.json"),
        ]
    )
    args.stop_signal = None

    summary = probe.run_probe(args)

    assert summary["run_status"] == "HALTED"
    assert summary["halt_reason"] == "hard tick overrun during home"
    assert bus.torque_enabled is False


def test_moving_probe_device_alarm_halts_and_reaches_torque_off(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class AlarmBus(probe.MockSTS3215Bus):
        def exchange_into(self, target_positions_rad, snapshot, tick):
            result = super().exchange_into(target_positions_rad, snapshot, tick)
            snapshot.device_status[0] = 0x01
            return result

    bus = AlarmBus(latency_s=0.0)
    monkeypatch.setattr(probe, "MockSTS3215Bus", lambda **_kwargs: bus)
    args = probe.build_parser().parse_args(
        [
            "--bus",
            "mock",
            "--enable-torque",
            "--home-seconds",
            "0.001",
            "--ticks",
            "2",
            "--mock-latency-ms",
            "0",
            "--output",
            str(tmp_path / "alarm.jsonl"),
            "--summary",
            str(tmp_path / "alarm-summary.json"),
        ]
    )
    args.stop_signal = None

    summary = probe.run_probe(args)

    assert summary["run_status"] == "HALTED"
    assert summary["halt_reason"] == "servo device alarm during moving probe: 20:0x01"
    assert bus.torque_enabled is False


def test_serial_movement_needs_gate_assertion_before_opening_bus(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        main(
            [
                "--bus",
                "serial",
                "--enable-torque",
                "--hardware-authorized",
                "--suspended-or-benched",
                "--output",
                str(tmp_path / "never.jsonl"),
                "--summary",
                str(tmp_path / "never.json"),
            ]
        )


def test_serial_probe_requires_verified_realtime_before_opening_bus(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def forbid_bus(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("serial bus must not open before RT requirement validation")

    monkeypatch.setattr(probe, "STS3215Bus", forbid_bus)
    with pytest.raises(SystemExit):
        main(
            [
                "--bus",
                "serial",
                "--hardware-authorized",
                "--suspended-or-benched",
                "--output",
                str(tmp_path / "never.jsonl"),
                "--summary",
                str(tmp_path / "never.json"),
            ]
        )
    assert not (tmp_path / "never.jsonl").exists()
