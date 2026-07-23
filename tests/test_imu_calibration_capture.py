from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from open_duck_x5 import imu_calibration_capture as capture_module
from open_duck_x5.imu_calibration import BNO055Calibration


def _config() -> Path:
    return Path(__file__).parents[1] / "duck_config.example.json"


def _schema(name: str) -> dict[str, object]:
    return json.loads((Path(__file__).parents[1] / "schemas" / name).read_text(encoding="utf-8"))


def test_mock_calibration_writes_verified_bounded_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(capture_module.time, "sleep", lambda _seconds: None)
    output_dir = tmp_path / "calibration"

    assert (
        capture_module.main(
            [
                "--backend",
                "mock",
                "--config",
                str(_config()),
                "--output-dir",
                str(output_dir),
                "--timeout-seconds",
                "1",
                "--poll-seconds",
                "0.1",
                "--stable-full-samples",
                "2",
            ]
        )
        == 0
    )

    summary = json.loads((output_dir / capture_module.SUMMARY_FILENAME).read_text(encoding="utf-8"))
    Draft202012Validator(_schema("imu_calibration_capture.schema.json")).validate(summary)
    records = [
        json.loads(line)
        for line in (output_dir / capture_module.STATUS_FILENAME)
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert len(records) == 2
    for index, record in enumerate(records):
        Draft202012Validator(_schema("imu_calibration_status.schema.json")).validate(record)
        assert record["poll"] == index
        assert record["status_raw"] == 0xFF
    profile_path = output_dir / capture_module.PROFILE_FILENAME
    profile = BNO055Calibration.load(profile_path)
    legacy_path = output_dir / capture_module.LEGACY_FILENAME
    assert profile.source_sha256 == hashlib.sha256(legacy_path.read_bytes()).hexdigest()
    assert profile.offsets_accelerometer == (11, -22, 33)
    assert summary["checks"]["profile_candidate"] is False
    assert summary["environment"]["servo_bus_accessed"] is False
    assert summary["environment"]["torque_enabled"] is False


def test_x5_calibration_requires_all_acknowledgements_before_device_open(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def forbid_open(*_args, **_kwargs):
        raise AssertionError("I2C must not open before exact authorization")

    monkeypatch.setattr(capture_module, "_open_device", forbid_open)
    base = [
        "--backend",
        "x5",
        "--config",
        str(_config()),
        "--output-dir",
        str(tmp_path / "never"),
    ]
    with pytest.raises(SystemExit) as missing_hardware:
        capture_module.main(base)
    assert missing_hardware.value.code == 2
    with pytest.raises(SystemExit) as missing_manual:
        capture_module.main([*base, "--hardware-authorized", "--suspended-or-benched"])
    assert missing_manual.value.code == 2
    assert not (tmp_path / "never").exists()


def test_x5_authorized_capture_has_reviewable_hardware_provenance(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(capture_module.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        capture_module,
        "_open_device",
        lambda _args, config, calibration: capture_module.MockCalibrationDevice(
            upside_down=config.imu_upside_down,
            calibration=calibration,
        ),
    )
    output_dir = tmp_path / "x5-calibration"

    assert (
        capture_module.main(
            [
                "--backend",
                "x5",
                "--config",
                str(_config()),
                "--output-dir",
                str(output_dir),
                "--timeout-seconds",
                "1",
                "--poll-seconds",
                "0.1",
                "--stable-full-samples",
                "2",
                "--hardware-authorized",
                "--suspended-or-benched",
                "--manual-calibration-authorized",
            ]
        )
        == 0
    )

    summary = json.loads((output_dir / capture_module.SUMMARY_FILENAME).read_text(encoding="utf-8"))
    Draft202012Validator(_schema("imu_calibration_capture.schema.json")).validate(summary)
    assert summary["backend"] == "x5"
    assert summary["informational_only"] is False
    assert summary["hardware_status"] == "REVIEW_REQUIRED"
    assert summary["checks"]["authorization_provenance"] is True
    assert summary["checks"]["profile_candidate"] is True
    assert summary["environment"]["manual_calibration_authorized"] is True


def test_existing_output_directory_is_rejected_before_device_open(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "existing"
    output_dir.mkdir()

    def forbid_open(*_args, **_kwargs):
        raise AssertionError("device must not open for an existing output directory")

    monkeypatch.setattr(capture_module, "_open_device", forbid_open)
    args = capture_module.build_parser().parse_args(
        [
            "--backend",
            "mock",
            "--config",
            str(_config()),
            "--output-dir",
            str(output_dir),
        ]
    )

    with pytest.raises(ValueError, match="refusing existing"):
        capture_module.run_capture(args)


def test_timeout_closes_device_and_writes_no_profile(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class NeverCalibrated:
        closed = False

        @staticmethod
        def calibration_status() -> tuple[int, dict[str, int]]:
            return 0, {
                "system": 0,
                "gyroscope": 0,
                "accelerometer": 0,
                "magnetometer": 0,
            }

        @staticmethod
        def close() -> None:
            NeverCalibrated.closed = True

    times = iter((0, 1_000_000_001))
    monkeypatch.setattr(capture_module, "clock_ns", lambda: next(times))
    monkeypatch.setattr(
        capture_module,
        "_open_device",
        lambda _args, _config, _calibration: NeverCalibrated(),
    )
    args = capture_module.build_parser().parse_args(
        [
            "--backend",
            "mock",
            "--config",
            str(_config()),
            "--output-dir",
            str(tmp_path / "never"),
            "--timeout-seconds",
            "1",
            "--poll-seconds",
            "0.1",
        ]
    )

    with pytest.raises(capture_module.CalibrationCaptureError, match="before timeout"):
        capture_module.run_capture(args)

    assert NeverCalibrated.closed is True
    assert not (tmp_path / "never").exists()


def test_failed_post_profile_verification_writes_no_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class CapturingDevice(capture_module.MockCalibrationDevice):
        pass

    class BadVerificationDevice(capture_module.MockCalibrationDevice):
        def describe(self) -> dict[str, object]:
            diagnostics = super().describe()
            diagnostics["axis_map_sign"] = 0
            return diagnostics

    opens = 0

    def open_device(_args, config, calibration):
        nonlocal opens
        opens += 1
        cls = CapturingDevice if opens == 1 else BadVerificationDevice
        return cls(upside_down=config.imu_upside_down, calibration=calibration)

    monkeypatch.setattr(capture_module, "_open_device", open_device)
    monkeypatch.setattr(capture_module.time, "sleep", lambda _seconds: None)
    args = capture_module.build_parser().parse_args(
        [
            "--backend",
            "mock",
            "--config",
            str(_config()),
            "--output-dir",
            str(tmp_path / "never"),
            "--timeout-seconds",
            "1",
            "--poll-seconds",
            "0.1",
            "--stable-full-samples",
            "2",
        ]
    )

    with pytest.raises(capture_module.CalibrationCaptureError, match="axis_map_sign"):
        capture_module.run_capture(args)

    assert not (tmp_path / "never").exists()


def test_artifact_failure_removes_staging_and_candidate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(capture_module.time, "sleep", lambda _seconds: None)
    original_write = capture_module._write_exclusive
    write_count = 0

    def fail_second_write(path: Path, payload: bytes) -> None:
        nonlocal write_count
        write_count += 1
        if write_count == 2:
            raise capture_module.CalibrationCaptureError("injected artifact failure")
        original_write(path, payload)

    monkeypatch.setattr(capture_module, "_write_exclusive", fail_second_write)
    output_dir = tmp_path / "never"
    args = capture_module.build_parser().parse_args(
        [
            "--backend",
            "mock",
            "--config",
            str(_config()),
            "--output-dir",
            str(output_dir),
            "--timeout-seconds",
            "1",
            "--poll-seconds",
            "0.1",
            "--stable-full-samples",
            "2",
        ]
    )

    with pytest.raises(capture_module.CalibrationCaptureError, match="injected"):
        capture_module.run_capture(args)

    assert not output_dir.exists()
    assert list(tmp_path.glob(".never.partial-*")) == []
