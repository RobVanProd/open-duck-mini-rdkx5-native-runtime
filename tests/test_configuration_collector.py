from __future__ import annotations

import json
from pathlib import Path

import pytest

from open_duck_x5 import configuration_collector
from open_duck_x5.bus import ErrorCode, MockSTS3215Bus
from open_duck_x5.configuration_collector import STAGE_TICKS, TICK_COUNT, main
from open_duck_x5.configuration_profile import (
    METADATA_SCHEMA_VERSION,
    TICK_SCHEMA_VERSION,
    build_automatic_configuration_profile,
)
from open_duck_x5.configuration_support import validate_automatic_profile_data
from open_duck_x5.constants import JOINT_NAMES, SERVO_IDS


def _config() -> Path:
    return Path(__file__).resolve().parents[1] / "duck_config.example.json"


def _output_arguments(tmp_path: Path) -> list[str]:
    return [
        "--config",
        str(_config()),
        "--trace",
        str(tmp_path / "trace.jsonl"),
        "--metadata",
        str(tmp_path / "metadata.json"),
        "--profile",
        str(tmp_path / "profile.json"),
    ]


def test_mock_collector_emits_complete_informational_evidence_chain(tmp_path: Path) -> None:
    assert main(["--mock-no-wait", *_output_arguments(tmp_path)]) == 0

    trace_path = tmp_path / "trace.jsonl"
    metadata_path = tmp_path / "metadata.json"
    profile_path = tmp_path / "profile.json"
    rows = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    profile = json.loads(profile_path.read_text(encoding="utf-8"))

    assert len(rows) == TICK_COUNT
    assert [row["tick"] for row in rows] == list(range(TICK_COUNT))
    assert all(row["schema_version"] == TICK_SCHEMA_VERSION for row in rows)
    for index, joint_name in enumerate(JOINT_NAMES):
        stage = rows[index * STAGE_TICKS : (index + 1) * STAGE_TICKS]
        assert {row["stage_joint"] for row in stage} == {joint_name}
    assert metadata["schema_version"] == METADATA_SCHEMA_VERSION
    assert metadata["backend"] == "mock"
    assert metadata["informational_only"] is True
    assert metadata["hardware_authorized"] is False
    assert metadata["motion_authorized"] is False
    assert metadata["configuration_calibration_authorized"] is False
    assert metadata["imu_calibration_sha256"] is None
    assert metadata["imu_calibration_source_sha256"] is None
    assert metadata["inventory"]["responding_servo_ids"] == list(SERVO_IDS)
    assert metadata["torque_off_confirmed"] is True
    assert profile["source"]["backend"] == "mock"
    assert profile["source"]["informational_only"] is True
    assert validate_automatic_profile_data(profile) == ["source.informational_only_mock"]

    reproduced = build_automatic_configuration_profile(
        trace_path=trace_path,
        metadata_path=metadata_path,
        configuration_path=_config(),
    )
    assert reproduced == profile


def test_serial_collector_checks_exact_authority_before_opening_bus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened = False

    def forbidden_bus(*args, **kwargs):
        nonlocal opened
        del args, kwargs
        opened = True
        raise AssertionError("serial bus must not open")

    monkeypatch.setattr(configuration_collector, "STS3215Bus", forbidden_bus)
    with pytest.raises(SystemExit):
        main(["--bus", "serial", *_output_arguments(tmp_path)])
    assert opened is False
    assert list(tmp_path.iterdir()) == []


def test_collector_refuses_existing_output_without_overwrite(tmp_path: Path) -> None:
    trace = tmp_path / "trace.jsonl"
    trace.write_text("protected", encoding="utf-8")

    with pytest.raises(SystemExit):
        main(["--mock-no-wait", *_output_arguments(tmp_path)])
    assert trace.read_text(encoding="utf-8") == "protected"
    assert not (tmp_path / "metadata.json").exists()
    assert not (tmp_path / "profile.json").exists()


def test_mock_no_wait_is_forbidden_for_serial_backend(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        main(["--bus", "serial", "--mock-no-wait", *_output_arguments(tmp_path)])
    assert list(tmp_path.iterdir()) == []


def test_mid_trace_failure_cuts_torque_and_publishes_no_final_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    instances: list[MockSTS3215Bus] = []

    class FailingBus(MockSTS3215Bus):
        def exchange_into(self, positions_rad, snapshot, tick_index):
            super().exchange_into(positions_rad, snapshot, tick_index)
            if tick_index == 3:
                snapshot.stale[0] = True
                snapshot.status[0] = int(ErrorCode.TIMEOUT)

    def bus_factory(*, latency_s: float):
        instance = FailingBus(latency_s=latency_s)
        instances.append(instance)
        return instance

    monkeypatch.setattr(configuration_collector, "MockSTS3215Bus", bus_factory)
    with pytest.raises(SystemExit):
        main(["--mock-no-wait", *_output_arguments(tmp_path)])

    assert len(instances) == 1
    assert instances[0].torque_enabled is False
    assert not (tmp_path / "trace.jsonl").exists()
    assert not (tmp_path / "metadata.json").exists()
    assert not (tmp_path / "profile.json").exists()
    assert (tmp_path / "trace.jsonl.partial").exists()
