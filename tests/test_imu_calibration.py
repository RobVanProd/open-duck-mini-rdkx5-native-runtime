from __future__ import annotations

import hashlib
import json
import os
import pickle
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from open_duck_x5.imu_calibration import (
    BNO055Calibration,
    CalibrationError,
    convert_legacy_calibration,
)


def _legacy_values() -> dict[str, tuple[int, int, int]]:
    return {
        "offsets_accelerometer": (11, -22, 33),
        "offsets_gyroscope": (-44, 55, -66),
        "offsets_magnetometer": (77, -88, 99),
    }


def test_converts_legacy_primitive_pickle_to_strict_schema(tmp_path: Path) -> None:
    source = tmp_path / "imu_calib_data.pkl"
    output = tmp_path / "imu_calibration.json"
    source.write_bytes(pickle.dumps(_legacy_values(), protocol=4))

    calibration = convert_legacy_calibration(source, output)

    assert calibration.offsets_accelerometer == (11, -22, 33)
    assert calibration.offsets_gyroscope == (-44, 55, -66)
    assert calibration.offsets_magnetometer == (77, -88, 99)
    assert calibration.source_sha256 == hashlib.sha256(source.read_bytes()).hexdigest()
    assert calibration.profile_sha256 == hashlib.sha256(output.read_bytes()).hexdigest()
    schema = json.loads(
        (Path(__file__).parents[1] / "schemas" / "imu_calibration.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(schema).validate(json.loads(output.read_text(encoding="utf-8")))


def test_calibration_profile_rejects_unknown_fields_and_non_int_offsets() -> None:
    base = {
        "schema_version": "open_duck_x5.bno055_calibration.v1",
        "source_format": "apirrone.imu_calib_data.pkl",
        "source_sha256": "0" * 64,
        **_legacy_values(),
    }
    with pytest.raises(CalibrationError, match="unknown fields"):
        BNO055Calibration.from_mapping({**base, "surprise": True})
    with pytest.raises(CalibrationError, match="must be an integer"):
        BNO055Calibration.from_mapping(
            {**base, "offsets_gyroscope": (1, 2.0, 3)}
        )


def test_converter_refuses_overwrite(tmp_path: Path) -> None:
    source = tmp_path / "legacy.pkl"
    output = tmp_path / "profile.json"
    source.write_bytes(pickle.dumps(_legacy_values()))
    output.write_text("preserve me", encoding="utf-8")

    with pytest.raises(CalibrationError, match="refusing to overwrite"):
        convert_legacy_calibration(source, output)
    assert output.read_text(encoding="utf-8") == "preserve me"


def test_restricted_unpickler_rejects_global_reduce(tmp_path: Path) -> None:
    marker = tmp_path / "must-not-exist"

    class Malicious:
        def __reduce__(self) -> tuple[object, tuple[str]]:
            return os.system, (f'echo unsafe > "{marker}"',)

    source = tmp_path / "malicious.pkl"
    source.write_bytes(pickle.dumps(Malicious()))

    with pytest.raises(CalibrationError, match="safe primitive pickle"):
        convert_legacy_calibration(source, tmp_path / "profile.json")
    assert not marker.exists()
