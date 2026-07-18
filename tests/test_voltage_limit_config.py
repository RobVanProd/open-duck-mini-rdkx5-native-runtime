from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from open_duck_x5.bus import ErrorCode
from open_duck_x5.bus.sts3215 import (
    ADDR_LOCK,
    ADDR_MAX_INPUT_VOLTAGE,
    ADDR_PRESENT_VOLTAGE,
)
from open_duck_x5.constants import SERVO_IDS, SERVO_SYNC_READ_IDS
from open_duck_x5.voltage_limit_config import main


def _validate(path: Path) -> dict[str, object]:
    summary = json.loads(path.read_text(encoding="utf-8"))
    schema_path = (
        Path(__file__).parents[1]
        / "schemas"
        / "voltage_limit_configuration.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(summary)
    return summary


def test_mock_configuration_updates_only_maximum_and_relocks(tmp_path: Path) -> None:
    output = tmp_path / "configuration.json"
    assert (
        main(
            [
                "--bus",
                "mock",
                "--confirm-max-voltage-8v4",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    summary = _validate(output)
    assert summary["finding"] == "configured_all14"
    assert summary["safety"]["maximum_voltage_write_attempt_count"] == 14
    assert summary["safety"]["minimum_voltage_write_count"] == 0
    assert summary["safety"]["torque_enable_requested"] is False
    assert summary["safety"]["all_known_unlocked_servos_relocked"] is True
    assert all(
        record["limits"]["max_voltage_raw"] == 84
        and record["limits"]["min_voltage_raw"] == 40
        and record["voltage"]["voltage_alarm"] is False
        for record in summary["final_records"]
    )
    journal = output.with_suffix(".jsonl")
    assert journal.is_file()
    assert len(journal.read_text(encoding="utf-8").splitlines()) > 100


def test_configuration_requires_specific_eeprom_confirmation(tmp_path: Path) -> None:
    output = tmp_path / "never.json"
    with pytest.raises(SystemExit):
        main(["--bus", "mock", "--output", str(output)])
    assert not output.exists()


def test_serial_configuration_requires_both_hardware_assertions(tmp_path: Path) -> None:
    output = tmp_path / "never.json"
    with pytest.raises(SystemExit):
        main(
            [
                "--bus",
                "serial",
                "--repository-commit",
                "a" * 40,
                "--confirm-max-voltage-8v4",
                "--output",
                str(output),
            ]
        )
    assert not output.exists()


class FakeSerialBus:
    instances: list[FakeSerialBus] = []
    persist_voltage_alarm = False
    initial_max = 80
    initial_max_by_id: dict[int, int] | None = None
    initial_lock_by_id: dict[int, int] | None = None

    def __init__(self, device: str, *, baudrate: int, transaction_timeout_s: float) -> None:
        del transaction_timeout_s
        self.device = device
        self.baudrate = baudrate
        self.actions: list[object] = []
        self.registers = {servo_id: bytearray(256) for servo_id in SERVO_IDS}
        for servo_id, registers in self.registers.items():
            registers[14] = (
                self.initial_max_by_id or {}
            ).get(servo_id, self.initial_max)
            registers[15] = 40
            registers[55] = (self.initial_lock_by_id or {}).get(servo_id, 1)
            registers[62] = 83
        self.instances.append(self)

    def disable_torque(self) -> ErrorCode:
        self.actions.append("torque_off")
        return ErrorCode.OK

    def read_register_with_device_status(self, servo_id: int, address: int, length: int):
        self.actions.append(("read", servo_id, address, length))
        data = bytes(self.registers[servo_id][address : address + length])
        alarm = self.persist_voltage_alarm or self.registers[servo_id][14] < 84
        return ErrorCode.OK, (0x01 if alarm else 0x00), data

    def write_register_with_device_status(self, servo_id: int, address: int, data: bytes):
        self.actions.append(("write", servo_id, address, bytes(data)))
        self.registers[servo_id][address : address + len(data)] = data
        alarm = self.persist_voltage_alarm or self.registers[servo_id][14] < 84
        return ErrorCode.OK, (0x01 if alarm else 0x00)

    def close(self) -> None:
        self.actions.append("close")


def _serial_args(output: Path) -> list[str]:
    return [
        "--bus",
        "serial",
        "--repository-commit",
        "b" * 40,
        "--hardware-authorized",
        "--suspended-or-benched",
        "--confirm-max-voltage-8v4",
        "--output",
        str(output),
    ]


def test_serial_configuration_uses_canary_then_known_wire_order(
    monkeypatch, tmp_path: Path
) -> None:
    FakeSerialBus.instances.clear()
    FakeSerialBus.persist_voltage_alarm = False
    FakeSerialBus.initial_max = 80
    FakeSerialBus.initial_max_by_id = None
    FakeSerialBus.initial_lock_by_id = None
    monkeypatch.setattr(
        "open_duck_x5.voltage_limit_config.STS3215Bus", FakeSerialBus
    )
    output = tmp_path / "configured.json"
    assert main(_serial_args(output)) == 0
    summary = _validate(output)
    assert summary["finding"] == "configured_all14"
    writes = [
        action
        for action in FakeSerialBus.instances[0].actions
        if isinstance(action, tuple) and action[0] == "write"
    ]
    maximum_writes = [
        action for action in writes if action[2] == ADDR_MAX_INPUT_VOLTAGE
    ]
    assert [action[1] for action in maximum_writes] == list(SERVO_SYNC_READ_IDS)
    assert all(action[3] == b"\x54" for action in maximum_writes)
    assert not any(action[2] == 15 for action in writes)
    assert FakeSerialBus.instances[0].actions[-2:] == ["torque_off", "close"]


def test_persistent_canary_alarm_stops_before_other_limit_writes(
    monkeypatch, tmp_path: Path
) -> None:
    FakeSerialBus.instances.clear()
    FakeSerialBus.persist_voltage_alarm = True
    FakeSerialBus.initial_max = 80
    FakeSerialBus.initial_max_by_id = None
    FakeSerialBus.initial_lock_by_id = None
    monkeypatch.setattr(
        "open_duck_x5.voltage_limit_config.STS3215Bus", FakeSerialBus
    )
    output = tmp_path / "halted.json"
    assert main(_serial_args(output)) == 2
    summary = _validate(output)
    assert summary["run_status"] == "HALTED"
    assert "alarm remained asserted" in summary["halt_reason"]
    assert summary["safety"]["maximum_voltage_write_attempt_count"] == 1
    writes = [
        action
        for action in FakeSerialBus.instances[0].actions
        if isinstance(action, tuple) and action[0] == "write"
    ]
    assert [
        action[1] for action in writes if action[2] == ADDR_MAX_INPUT_VOLTAGE
    ] == [SERVO_SYNC_READ_IDS[0]]
    assert ("write", SERVO_SYNC_READ_IDS[0], ADDR_LOCK, b"\x01") in writes
    assert not any(
        action[1] != SERVO_SYNC_READ_IDS[0]
        and action[2] in (ADDR_LOCK, ADDR_MAX_INPUT_VOLTAGE)
        for action in writes
    )
    assert any(
        isinstance(action, tuple)
        and action[:3] == ("read", SERVO_SYNC_READ_IDS[0], ADDR_PRESENT_VOLTAGE)
        for action in FakeSerialBus.instances[0].actions
    )


def test_unexpected_preflight_value_causes_zero_eeprom_writes(
    monkeypatch, tmp_path: Path
) -> None:
    FakeSerialBus.instances.clear()
    FakeSerialBus.persist_voltage_alarm = False
    FakeSerialBus.initial_max = 82
    FakeSerialBus.initial_max_by_id = None
    FakeSerialBus.initial_lock_by_id = None
    monkeypatch.setattr(
        "open_duck_x5.voltage_limit_config.STS3215Bus", FakeSerialBus
    )
    output = tmp_path / "halted.json"
    assert main(_serial_args(output)) == 2
    summary = _validate(output)
    assert summary["finding"] == "preflight_mismatch"
    assert summary["safety"]["maximum_voltage_write_attempt_count"] == 0
    assert summary["safety"]["lock_control_write_attempt_count"] == 0
    assert not any(
        isinstance(action, tuple) and action[0] == "write"
        for action in FakeSerialBus.instances[0].actions
    )


def test_lost_unlock_ack_is_recovered_only_by_exact_readback(
    monkeypatch, tmp_path: Path
) -> None:
    class LostUnlockAckBus(FakeSerialBus):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self.lost = False

        def write_register_with_device_status(
            self, servo_id: int, address: int, data: bytes
        ):
            result = super().write_register_with_device_status(
                servo_id, address, data
            )
            if address == ADDR_LOCK and data == b"\x00" and not self.lost:
                self.lost = True
                return ErrorCode.TIMEOUT, None
            return result

    FakeSerialBus.instances.clear()
    FakeSerialBus.persist_voltage_alarm = False
    FakeSerialBus.initial_max = 80
    FakeSerialBus.initial_max_by_id = None
    FakeSerialBus.initial_lock_by_id = None
    monkeypatch.setattr(
        "open_duck_x5.voltage_limit_config.STS3215Bus", LostUnlockAckBus
    )
    output = tmp_path / "configured.json"
    assert main(_serial_args(output)) == 0
    summary = _validate(output)
    assert summary["finding"] == "configured_all14"
    assert summary["safety"]["maximum_voltage_write_attempt_count"] == 14
    assert summary["safety"]["all_known_unlocked_servos_relocked"] is True
    journal = output.with_suffix(".jsonl").read_text(encoding="utf-8")
    assert '"event": "write_ack_recovered_by_readback"' in journal


def test_lost_limit_ack_is_recovered_only_when_limit_readback_matches(
    monkeypatch, tmp_path: Path
) -> None:
    class LostLimitAckBus(FakeSerialBus):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self.lost = False

        def write_register_with_device_status(
            self, servo_id: int, address: int, data: bytes
        ):
            result = super().write_register_with_device_status(
                servo_id, address, data
            )
            if address == ADDR_MAX_INPUT_VOLTAGE and not self.lost:
                self.lost = True
                return ErrorCode.TIMEOUT, None
            return result

    FakeSerialBus.instances.clear()
    FakeSerialBus.persist_voltage_alarm = False
    FakeSerialBus.initial_max = 80
    FakeSerialBus.initial_max_by_id = None
    FakeSerialBus.initial_lock_by_id = None
    monkeypatch.setattr(
        "open_duck_x5.voltage_limit_config.STS3215Bus", LostLimitAckBus
    )
    output = tmp_path / "configured.json"
    assert main(_serial_args(output)) == 0
    summary = _validate(output)
    assert summary["finding"] == "configured_all14"
    assert summary["safety"]["maximum_voltage_write_attempt_count"] == 14
    journal = output.with_suffix(".jsonl").read_text(encoding="utf-8")
    assert '"address": 14' in journal
    assert '"event": "write_ack_recovered_by_readback"' in journal


def test_mixed_80_84_preflight_resumes_without_rewriting_completed_servos(
    monkeypatch, tmp_path: Path
) -> None:
    FakeSerialBus.instances.clear()
    FakeSerialBus.persist_voltage_alarm = False
    FakeSerialBus.initial_max = 80
    FakeSerialBus.initial_max_by_id = {20: 84, 21: 84, 22: 84}
    FakeSerialBus.initial_lock_by_id = {22: 0}
    monkeypatch.setattr(
        "open_duck_x5.voltage_limit_config.STS3215Bus", FakeSerialBus
    )
    output = tmp_path / "resumed.json"
    assert main(_serial_args(output)) == 0
    summary = _validate(output)
    assert summary["finding"] == "resumed_and_configured_all14"
    assert summary["canary_servo_id"] == 23
    assert [record["servo_id"] for record in summary["preexisting_verified"]] == [
        20,
        21,
        22,
    ]
    assert summary["safety"]["maximum_voltage_write_attempt_count"] == 11
    writes = [
        action
        for action in FakeSerialBus.instances[0].actions
        if isinstance(action, tuple) and action[0] == "write"
    ]
    maximum_writes = [
        action for action in writes if action[2] == ADDR_MAX_INPUT_VOLTAGE
    ]
    assert [action[1] for action in maximum_writes] == list(
        SERVO_SYNC_READ_IDS[3:]
    )
    assert ("write", 22, ADDR_LOCK, b"\x01") in writes
