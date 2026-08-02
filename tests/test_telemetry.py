import json
from pathlib import Path

import numpy as np
import pytest
from jsonschema import Draft202012Validator, ValidationError

from open_duck_x5.bus import ErrorCode, ServoSnapshot
from open_duck_x5.constants import ACTION_DIM, OBSERVATION_DIM
from open_duck_x5.single_servo_probe import AsyncSingleServoWriter
from open_duck_x5.telemetry import (
    AsyncControlWriter,
    AsyncProbeWriter,
    TelemetryError,
)


@pytest.mark.parametrize("writer_type", [AsyncProbeWriter, AsyncControlWriter])
def test_writer_open_failure_is_reported_synchronously(
    tmp_path: Path, writer_type: type[AsyncProbeWriter] | type[AsyncControlWriter]
) -> None:
    with pytest.raises(TelemetryError, match="writer failed"):
        writer_type(tmp_path)


def test_probe_writer_pool_exhaustion_is_fatal(tmp_path: Path) -> None:
    writer = AsyncProbeWriter(tmp_path / "timing.jsonl", capacity=1)
    reserved = writer._free.get_nowait()
    try:
        with pytest.raises(TelemetryError, match="pool exhausted"):
            writer.publish(
                0,
                0,
                0,
                0,
                ServoSnapshot.create(),
                np.zeros(ACTION_DIM, dtype=np.float64),
            )
        assert writer.dropped == 1
    finally:
        writer._free.put(reserved)
        writer.close()


def test_control_writer_pool_exhaustion_is_fatal(tmp_path: Path) -> None:
    writer = AsyncControlWriter(tmp_path / "control.jsonl", capacity=1)
    reserved = writer._free.get_nowait()
    try:
        with pytest.raises(TelemetryError, match="pool exhausted"):
            writer.publish(
                0,
                0,
                0,
                0,
                True,
                False,
                0,
                0,
                ServoSnapshot.create(),
                np.zeros(OBSERVATION_DIM, dtype=np.float32),
                np.zeros(ACTION_DIM, dtype=np.float32),
                np.zeros(ACTION_DIM, dtype=np.float64),
                np.zeros(ACTION_DIM, dtype=np.float64),
                np.zeros(ACTION_DIM, dtype=np.float64),
                np.zeros(ACTION_DIM, dtype=np.bool_),
            )
        assert writer.dropped == 1
    finally:
        writer._free.put(reserved)
        writer.close(reason="test")


def test_control_writer_preserves_t247_observation_and_route_metadata(
    tmp_path: Path,
) -> None:
    path = tmp_path / "t247-control.jsonl"
    writer = AsyncControlWriter(path, observation_dim=115)
    observation = np.arange(115, dtype=np.float32)
    writer.publish(
        250,
        1,
        20_000_000,
        2_000_000,
        False,
        True,
        10,
        20,
        ServoSnapshot.create(),
        observation,
        np.zeros(ACTION_DIM, dtype=np.float32),
        np.zeros(ACTION_DIM, dtype=np.float64),
        np.zeros(ACTION_DIM, dtype=np.float64),
        np.zeros(ACTION_DIM, dtype=np.float64),
        np.zeros(ACTION_DIM, dtype=np.bool_),
        policy_stage="locomotion",
        selected_context_route="lower-cond0",
        selected_command_route="x080",
    )
    writer.close(reason="test")
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    tick = records[0]
    schema = json.loads(
        (Path(__file__).parents[1] / "schemas" / "control_tick.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(schema).validate(tick)
    assert tick["observation"] == observation.tolist()
    assert len(tick["observation"]) == 115
    assert tick["policy_host"] == {
        "stage": "locomotion",
        "selected_context_route": "lower-cond0",
        "selected_command_route": "x080",
    }
    without_host = dict(tick)
    del without_host["policy_host"]
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(without_host)


def test_single_servo_writer_pool_exhaustion_is_fatal(tmp_path: Path) -> None:
    writer = AsyncSingleServoWriter(tmp_path / "single.jsonl", 20, capacity=1)
    reserved = writer._free.get_nowait()
    try:
        with pytest.raises(TelemetryError, match="pool exhausted"):
            writer.publish(0, 0, 0, 0, ErrorCode.OK, 0, 0)
        assert writer.dropped == 1
    finally:
        writer._free.put(reserved)
        writer.close()
