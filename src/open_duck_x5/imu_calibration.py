from __future__ import annotations

import argparse
import hashlib
import io
import json
import pickle
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CALIBRATION_SCHEMA_VERSION = "open_duck_x5.bno055_calibration.v1"
LEGACY_SOURCE_FORMAT = "apirrone.imu_calib_data.pkl"
MAX_CALIBRATION_BYTES = 64 * 1024
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_OFFSET_KEYS = (
    "offsets_accelerometer",
    "offsets_gyroscope",
    "offsets_magnetometer",
)


class CalibrationError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _offset_triplet(value: object, name: str) -> tuple[int, int, int]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise CalibrationError(f"{name} must contain exactly three integers")
    output: list[int] = []
    for index, item in enumerate(value):
        if isinstance(item, bool) or not isinstance(item, int):
            raise CalibrationError(f"{name}[{index}] must be an integer")
        if not -32768 <= item <= 32767:
            raise CalibrationError(f"{name}[{index}] is outside signed 16-bit range")
        output.append(item)
    return output[0], output[1], output[2]


@dataclass(frozen=True, slots=True)
class BNO055Calibration:
    source_sha256: str
    offsets_accelerometer: tuple[int, int, int]
    offsets_gyroscope: tuple[int, int, int]
    offsets_magnetometer: tuple[int, int, int]
    profile_path: Path | None = None
    profile_sha256: str | None = None

    @classmethod
    def from_mapping(
        cls,
        data: Mapping[str, Any],
        *,
        profile_path: Path | None = None,
        profile_sha256: str | None = None,
    ) -> BNO055Calibration:
        expected = {
            "schema_version",
            "source_format",
            "source_sha256",
            *_OFFSET_KEYS,
        }
        missing = sorted(expected - set(data))
        extra = sorted(set(data) - expected)
        if missing:
            raise CalibrationError(f"calibration profile missing fields: {', '.join(missing)}")
        if extra:
            raise CalibrationError(f"calibration profile has unknown fields: {', '.join(extra)}")
        if data["schema_version"] != CALIBRATION_SCHEMA_VERSION:
            raise CalibrationError("unsupported calibration schema_version")
        if data["source_format"] != LEGACY_SOURCE_FORMAT:
            raise CalibrationError("unsupported calibration source_format")
        source_sha256 = data["source_sha256"]
        if not isinstance(source_sha256, str) or not _SHA256_RE.fullmatch(source_sha256):
            raise CalibrationError("source_sha256 must be 64 lowercase hexadecimal characters")
        if profile_sha256 is not None and not _SHA256_RE.fullmatch(profile_sha256):
            raise CalibrationError("profile_sha256 must be 64 lowercase hexadecimal characters")
        return cls(
            source_sha256=source_sha256,
            offsets_accelerometer=_offset_triplet(
                data["offsets_accelerometer"], "offsets_accelerometer"
            ),
            offsets_gyroscope=_offset_triplet(
                data["offsets_gyroscope"], "offsets_gyroscope"
            ),
            offsets_magnetometer=_offset_triplet(
                data["offsets_magnetometer"], "offsets_magnetometer"
            ),
            profile_path=profile_path,
            profile_sha256=profile_sha256,
        )

    @classmethod
    def load(cls, path: str | Path) -> BNO055Calibration:
        source = Path(path).expanduser().resolve()
        try:
            size = source.stat().st_size
        except OSError as exc:
            raise CalibrationError(f"cannot stat calibration profile {source}: {exc}") from exc
        if not 1 <= size <= MAX_CALIBRATION_BYTES:
            raise CalibrationError(
                f"calibration profile size must be in 1..{MAX_CALIBRATION_BYTES} bytes"
            )
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise CalibrationError(f"cannot read calibration profile {source}: {exc}") from exc
        if not isinstance(data, dict):
            raise CalibrationError("calibration profile root must be an object")
        return cls.from_mapping(
            data,
            profile_path=source,
            profile_sha256=sha256_file(source),
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": CALIBRATION_SCHEMA_VERSION,
            "source_format": LEGACY_SOURCE_FORMAT,
            "source_sha256": self.source_sha256,
            "offsets_accelerometer": list(self.offsets_accelerometer),
            "offsets_gyroscope": list(self.offsets_gyroscope),
            "offsets_magnetometer": list(self.offsets_magnetometer),
        }


class _RestrictedUnpickler(pickle.Unpickler):
    def find_class(self, module: str, name: str) -> object:
        raise pickle.UnpicklingError(f"global object is forbidden: {module}.{name}")

    def persistent_load(self, pid: object) -> object:
        raise pickle.UnpicklingError(f"persistent object is forbidden: {pid!r}")


def _load_restricted_legacy_pickle(path: Path) -> tuple[Mapping[str, Any], str]:
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise CalibrationError(f"cannot read legacy calibration {path}: {exc}") from exc
    if not 1 <= len(payload) <= MAX_CALIBRATION_BYTES:
        raise CalibrationError(
            f"legacy calibration size must be in 1..{MAX_CALIBRATION_BYTES} bytes"
        )
    try:
        data = _RestrictedUnpickler(io.BytesIO(payload)).load()
    except (EOFError, pickle.UnpicklingError, ValueError) as exc:
        raise CalibrationError(f"legacy calibration is not a safe primitive pickle: {exc}") from exc
    if not isinstance(data, dict):
        raise CalibrationError("legacy calibration root must be a dictionary")
    if set(data) != set(_OFFSET_KEYS):
        raise CalibrationError(
            "legacy calibration must contain exactly offsets_accelerometer, "
            "offsets_gyroscope, and offsets_magnetometer"
        )
    return data, hashlib.sha256(payload).hexdigest()


def convert_legacy_calibration(source: Path, output: Path) -> BNO055Calibration:
    source = source.expanduser().resolve()
    output = output.expanduser().resolve()
    if source == output:
        raise CalibrationError("legacy input and JSON output must be different files")
    if output.exists():
        raise CalibrationError(f"refusing to overwrite existing calibration profile: {output}")
    data, source_sha256 = _load_restricted_legacy_pickle(source)
    calibration = BNO055Calibration.from_mapping(
        {
            "schema_version": CALIBRATION_SCHEMA_VERSION,
            "source_format": LEGACY_SOURCE_FORMAT,
            "source_sha256": source_sha256,
            **{key: data[key] for key in _OFFSET_KEYS},
        }
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(calibration.to_mapping(), indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    try:
        with output.open("xb") as handle:
            handle.write(encoded)
    except OSError as exc:
        raise CalibrationError(f"cannot create calibration profile {output}: {exc}") from exc
    return BNO055Calibration.load(output)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert apirrone's primitive BNO055 calibration pickle to strict JSON"
    )
    parser.add_argument("--legacy-pickle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        calibration = convert_legacy_calibration(args.legacy_pickle, args.output)
    except CalibrationError as exc:
        parser.error(str(exc))
    print(json.dumps(calibration.to_mapping(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
