from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from open_duck_x5.bus import ErrorCode
from open_duck_x5.constants import SERVO_SYNC_READ_IDS
from open_duck_x5.voltage_limit_probe import main


def _validate(path: Path) -> dict[str, object]:
    summary = json.loads(path.read_text(encoding="utf-8"))
    schema_path = (
        Path(__file__).parents[1] / "schemas" / "voltage_limit_diagnostic.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(summary)
    return summary


def test_mock_limit_probe_reads_only_fixed_ranges_with_torque_off(tmp_path: Path) -> None:
    output = tmp_path / "limits.json"
    assert main(["--bus", "mock", "--output", str(output)]) == 0
    summary = _validate(output)
    assert summary["complete_all14"] is True
    assert summary["finding"] == "uniform_model_and_limits"
    assert all(record["model_raw"] == 0x0309 for record in summary["records"])
    assert all(record["max_voltage_v"] == 8.0 for record in summary["records"])
    assert all(record["min_voltage_v"] == 4.0 for record in summary["records"])
    assert summary["safety"]["torque_enable_requested"] is False
    assert summary["safety"]["goal_position_write_count"] == 0
    assert summary["safety"]["eeprom_write_count"] == 0


def test_serial_limit_probe_requires_both_hardware_assertions(tmp_path: Path) -> None:
    output = tmp_path / "never.json"
    with pytest.raises(SystemExit):
        main(
            [
                "--bus",
                "serial",
                "--repository-commit",
                "a" * 40,
                "--output",
                str(output),
            ]
        )
    assert not output.exists()


def test_serial_limit_probe_only_reads_authorized_registers(monkeypatch, tmp_path: Path) -> None:
    actions: list[object] = []

    class FakeSerialBus:
        def __init__(self, device: str, *, baudrate: int, transaction_timeout_s: float) -> None:
            del transaction_timeout_s
            self.device = device
            self.baudrate = baudrate

        def disable_torque(self) -> ErrorCode:
            actions.append("torque_off")
            return ErrorCode.OK

        def read_register_with_device_status(self, servo_id: int, address: int, length: int):
            actions.append(("read", servo_id, address, length))
            data = bytes((9, 3)) if address == 3 else bytes((80, 40))
            return ErrorCode.DEVICE, 0x01, data

        def close(self) -> None:
            actions.append("close")

    monkeypatch.setattr("open_duck_x5.voltage_limit_probe.STS3215Bus", FakeSerialBus)
    output = tmp_path / "limits.json"
    assert (
        main(
            [
                "--bus",
                "serial",
                "--repository-commit",
                "b" * 40,
                "--hardware-authorized",
                "--suspended-or-benched",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    summary = _validate(output)
    assert summary["finding"] == "uniform_model_and_limits"
    expected: list[object] = ["torque_off"]
    for servo_id in SERVO_SYNC_READ_IDS:
        expected.extend(
            [
                ("read", servo_id, 3, 2),
                ("read", servo_id, 14, 2),
            ]
        )
    expected.extend(["torque_off", "close"])
    assert actions == expected
