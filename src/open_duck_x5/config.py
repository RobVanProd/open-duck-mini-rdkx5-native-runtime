from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from .constants import JOINT_NAMES


class ConfigError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class DuckConfig:
    start_paused: bool = False
    imu_upside_down: bool = False
    phase_frequency_factor_offset: float = 0.0
    joints_offsets: dict[str, float] = field(
        default_factory=lambda: {name: 0.0 for name in JOINT_NAMES}
    )
    expression_features: dict[str, bool] = field(default_factory=dict)
    source_path: Path | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def load(cls, path: str | Path, *, require_file: bool = True) -> DuckConfig:
        source = Path(path).expanduser()
        if not source.exists():
            if require_file:
                raise ConfigError(f"duck config not found: {source}")
            return cls(source_path=source)
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigError(f"cannot read duck config {source}: {exc}") from exc
        if not isinstance(data, dict):
            raise ConfigError("duck config root must be an object")

        start_paused = data.get("start_paused", False)
        if not isinstance(start_paused, bool):
            raise ConfigError("start_paused must be a JSON boolean")
        imu_upside_down = data.get("imu_upside_down", False)
        if not isinstance(imu_upside_down, bool):
            raise ConfigError("imu_upside_down must be a JSON boolean")

        raw_offsets = data.get("joints_offsets", {})
        if not isinstance(raw_offsets, dict):
            raise ConfigError("joints_offsets must be an object")
        missing = [name for name in JOINT_NAMES if name not in raw_offsets]
        extra = sorted(set(raw_offsets) - set(JOINT_NAMES))
        if missing:
            raise ConfigError(f"joints_offsets missing joints: {', '.join(missing)}")
        if extra:
            raise ConfigError(f"joints_offsets contains unknown joints: {', '.join(extra)}")
        offsets: dict[str, float] = {}
        for name in JOINT_NAMES:
            try:
                value = float(raw_offsets[name])
            except (TypeError, ValueError) as exc:
                raise ConfigError(f"offset for {name} must be numeric") from exc
            if not np.isfinite(value):
                raise ConfigError(f"offset for {name} must be finite")
            offsets[name] = value

        try:
            phase_offset = float(data.get("phase_frequency_factor_offset", 0.0))
        except (TypeError, ValueError) as exc:
            raise ConfigError("phase_frequency_factor_offset must be numeric") from exc
        if not np.isfinite(phase_offset):
            raise ConfigError("phase_frequency_factor_offset must be finite")

        expression_features = data.get("expression_features", {})
        if not isinstance(expression_features, dict):
            raise ConfigError("expression_features must be an object")

        return cls(
            start_paused=start_paused,
            imu_upside_down=imu_upside_down,
            phase_frequency_factor_offset=phase_offset,
            joints_offsets=offsets,
            expression_features={str(k): bool(v) for k, v in expression_features.items()},
            source_path=source,
            raw=data,
        )

    @property
    def offsets_array(self) -> np.ndarray:
        return np.fromiter((self.joints_offsets[name] for name in JOINT_NAMES), dtype=np.float64)

    def with_offsets(self, offsets: dict[str, float]) -> dict[str, Any]:
        if set(offsets) != set(JOINT_NAMES):
            raise ConfigError("replacement offsets must contain exactly the 14 frozen joints")
        output = dict(self.raw)
        output["start_paused"] = self.start_paused
        output["imu_upside_down"] = self.imu_upside_down
        output["phase_frequency_factor_offset"] = self.phase_frequency_factor_offset
        output["expression_features"] = dict(self.expression_features)
        output["joints_offsets"] = {name: float(offsets[name]) for name in JOINT_NAMES}
        return output
