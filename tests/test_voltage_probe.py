from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from open_duck_x5.bus import ErrorCode
from open_duck_x5.constants import SERVO_SYNC_READ_IDS
from open_duck_x5.voltage_probe import main


def _validate(path: Path) -> dict[str, object]:
    summary = json.loads(path.read_text(encoding="utf-8"))
    schema_path = Path(__file__).parents[1] / "schemas" / "voltage_diagnostic.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(summary)
    return summary


def test_mock_voltage_probe_records_all_fourteen_without_motion(tmp_path: Path) -> None:
    output = tmp_path / "voltage.json"
    assert main(["--bus", "mock", "--output", str(output)]) == 0
    summary = _validate(output)
    assert summary["run_status"] == "COMPLETE"
    assert summary["finding"] == "no_input_voltage_error"
    assert summary["complete_all14"] is True
    assert [record["servo_id"] for record in summary["records"]] == list(
        SERVO_SYNC_READ_IDS
    )
    assert all(record["present_voltage_v"] == 7.4 for record in summary["records"])
    assert summary["safety"] == {
        "final_torque_off_status": "ok",
        "goal_position_write_count": 0,
        "initial_torque_off_status": "ok",
        "torque_enable_requested": False,
    }


def test_serial_voltage_probe_requires_both_hardware_assertions(tmp_path: Path) -> None:
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


def test_serial_voltage_probe_preserves_error_payload_and_only_reads(
    monkeypatch, tmp_path: Path
) -> None:
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
            return ErrorCode.DEVICE, 0x01, bytes((74,))

        def close(self) -> None:
            actions.append("close")

    monkeypatch.setattr("open_duck_x5.voltage_probe.STS3215Bus", FakeSerialBus)
    output = tmp_path / "voltage.json"
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
    assert summary["finding"] == "all_servos_input_voltage_error"
    assert all(record["response_status"] == "device" for record in summary["records"])
    assert all(record["device_status_raw"] == 1 for record in summary["records"])
    assert all(record["present_voltage_v"] == 7.4 for record in summary["records"])
    assert actions == [
        "torque_off",
        *(("read", servo_id, 62, 1) for servo_id in SERVO_SYNC_READ_IDS),
        "torque_off",
        "close",
    ]
