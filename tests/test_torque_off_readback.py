from __future__ import annotations

import json
from pathlib import Path

import pytest

from open_duck_x5.bus import ErrorCode
from open_duck_x5.constants import SERVO_SYNC_READ_IDS
from open_duck_x5.torque_off_readback import main


def test_mock_torque_off_readback_reads_all_14_with_id_13_last(
    tmp_path: Path,
) -> None:
    output = tmp_path / "torque-off.json"
    assert main(["--bus", "mock", "--output", str(output)]) == 0
    summary = json.loads(output.read_text(encoding="utf-8"))
    assert summary["status"] == "PASS"
    assert summary["checks"] == {
        "all_14_torque_enable_registers_zero": True,
        "complete_all_14": True,
        "final_disable_ok": True,
        "initial_disable_ok": True,
    }
    assert [record["servo_id"] for record in summary["records"]] == list(
        SERVO_SYNC_READ_IDS
    )
    assert summary["read_order"][-2:] == [14, 13]
    assert all(record["register_address"] == 40 for record in summary["records"])
    assert all(record["torque_enable_raw"] == 0 for record in summary["records"])
    assert summary["safety"] == {
        "final_torque_off_status": "ok",
        "goal_position_write_count": 0,
        "initial_torque_off_status": "ok",
        "torque_enable_requested": False,
    }


def test_serial_torque_off_readback_requires_both_hardware_assertions(
    tmp_path: Path,
) -> None:
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


def test_serial_torque_off_readback_is_independent_and_read_only_after_disable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
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
            return ErrorCode.OK, 0, b"\x00"

        def close(self) -> None:
            actions.append("close")

    monkeypatch.setattr(
        "open_duck_x5.torque_off_readback.STS3215Bus", FakeSerialBus
    )
    output = tmp_path / "torque-off.json"
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
    summary = json.loads(output.read_text(encoding="utf-8"))
    assert summary["status"] == "PASS"
    assert actions == [
        "torque_off",
        *(("read", servo_id, 40, 1) for servo_id in SERVO_SYNC_READ_IDS),
        "torque_off",
        "close",
    ]
