from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from open_duck_x5 import imu_calibration as imu_calibration_module
from open_duck_x5 import imu_calibration_capture as capture_module
from open_duck_x5 import imu_calibration_review as review_module
from open_duck_x5 import sensors as sensors_module
from open_duck_x5.imu_calibration import sha256_file


def _config() -> Path:
    return Path(__file__).parents[1] / "duck_config.example.json"


def _schema() -> dict[str, object]:
    return json.loads(
        (Path(__file__).parents[1] / "schemas" / "imu_calibration_review.schema.json").read_text(
            encoding="utf-8"
        )
    )


def _current_capture_software() -> dict[str, str]:
    return {
        "capture": sha256_file(Path(capture_module.__file__).resolve()),
        "sensors": sha256_file(Path(sensors_module.__file__).resolve()),
        "imu_calibration": sha256_file(Path(imu_calibration_module.__file__).resolve()),
    }


def _capture(monkeypatch: pytest.MonkeyPatch, output_dir: Path) -> Path:
    monkeypatch.setattr(capture_module.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        capture_module,
        "_open_device",
        lambda _args, config, calibration: capture_module.MockCalibrationDevice(
            upside_down=config.imu_upside_down,
            calibration=calibration,
        ),
    )
    config_path = output_dir.parent / f"{output_dir.name}-duck-config.json"
    config = json.loads(_config().read_text(encoding="utf-8"))
    config["imu_upside_down"] = True
    config_path.write_text(json.dumps(config), encoding="utf-8")
    args = capture_module.build_parser().parse_args(
        [
            "--backend",
            "x5",
            "--config",
            str(config_path),
            "--output-dir",
            str(output_dir),
            "--hardware-authorized",
            "--suspended-or-benched",
            "--manual-calibration-authorized",
        ]
    )
    capture_module.run_capture(args)
    return config_path


def _verify(capture_dir: Path, config_path: Path) -> dict[str, object]:
    return review_module.verify_calibration_capture(
        capture_dir,
        expected_config_sha256=sha256_file(config_path),
        expected_capture_software_sha256=_current_capture_software(),
    )


def test_independent_review_rederives_complete_capture(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    capture_dir = tmp_path / "capture"
    config_path = _capture(monkeypatch, capture_dir)

    packet = _verify(capture_dir, config_path)

    Draft202012Validator(_schema()).validate(packet)
    assert packet["status"] == "REVIEW_REQUIRED"
    assert packet["data_integrity_candidate"] is True
    assert packet["physical_calibration_decision"] == "REVIEW_REQUIRED"
    assert packet["status_rows"] == 5
    assert len(packet["raw_artifacts"]) == 4
    assert all(packet["checks"].values())


def test_review_rejects_extra_file_and_status_tampering(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    capture_dir = tmp_path / "capture"
    config_path = _capture(monkeypatch, capture_dir)
    extra = capture_dir / "unreviewed.txt"
    extra.write_text("not part of the frozen population", encoding="utf-8")

    with pytest.raises(review_module.CalibrationReviewError, match="missing or extra"):
        _verify(capture_dir, config_path)

    extra.unlink()
    status_path = capture_dir / capture_module.STATUS_FILENAME
    rows = status_path.read_text(encoding="utf-8").splitlines()
    final = json.loads(rows[-1])
    final.update(
        {
            "status_raw": 0,
            "system": 0,
            "gyroscope": 0,
            "accelerometer": 0,
            "magnetometer": 0,
        }
    )
    rows[-1] = json.dumps(final, separators=(",", ":"))
    status_path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    with pytest.raises(review_module.CalibrationReviewError, match="does not end"):
        _verify(capture_dir, config_path)


def test_review_rejects_software_and_legacy_source_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    capture_dir = tmp_path / "capture"
    config_path = _capture(monkeypatch, capture_dir)
    summary_path = capture_dir / capture_module.SUMMARY_FILENAME
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["software"]["sensors"]["sha256"] = "0" * 64
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    with pytest.raises(review_module.CalibrationReviewError, match="source hash mismatch"):
        _verify(capture_dir, config_path)

    second_dir = tmp_path / "second"
    second_config = _capture(monkeypatch, second_dir)
    second_pickle = second_dir / capture_module.LEGACY_FILENAME
    second_pickle.write_bytes(second_pickle.read_bytes() + b"x")
    with pytest.raises(review_module.CalibrationReviewError, match="source hash mismatch"):
        _verify(second_dir, second_config)


def test_frozen_capture_source_hashes_match_published_commit() -> None:
    root = Path(__file__).parents[1]
    source_paths = {
        "capture": "src/open_duck_x5/imu_calibration_capture.py",
        "sensors": "src/open_duck_x5/sensors.py",
        "imu_calibration": "src/open_duck_x5/imu_calibration.py",
    }
    for name, path in source_paths.items():
        payload = subprocess.check_output(
            [
                "git",
                "show",
                f"{review_module.EXPECTED_CAPTURE_SOURCE_COMMIT}:{path}",
            ],
            cwd=root,
        )
        assert (
            hashlib.sha256(payload).hexdigest()
            == (review_module.EXPECTED_CAPTURE_SOFTWARE_SHA256[name])
        )
