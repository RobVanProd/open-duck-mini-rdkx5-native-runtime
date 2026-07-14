from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from open_duck_x5.config import ConfigError, DuckConfig
from open_duck_x5.constants import ACTION_DIM, JOINT_NAMES


def test_example_config_preserves_frozen_semantics() -> None:
    path = Path(__file__).parents[1] / "duck_config.example.json"
    config = DuckConfig.load(path)
    assert config.start_paused is True
    assert config.imu_upside_down is False
    assert config.phase_frequency_factor_offset == 0.0
    assert config.offsets_array.shape == (ACTION_DIM,)
    assert np.all(config.offsets_array == 0.0)


def test_config_rejects_missing_and_unknown_joint_names(tmp_path: Path) -> None:
    base = {
        "start_paused": True,
        "joints_offsets": {name: 0.0 for name in JOINT_NAMES},
    }
    del base["joints_offsets"][JOINT_NAMES[0]]
    path = tmp_path / "missing.json"
    path.write_text(json.dumps(base), encoding="utf-8")
    with pytest.raises(ConfigError, match="missing joints"):
        DuckConfig.load(path)

    base["joints_offsets"][JOINT_NAMES[0]] = 0.0
    base["joints_offsets"]["not_a_joint"] = 0.0
    path.write_text(json.dumps(base), encoding="utf-8")
    with pytest.raises(ConfigError, match="unknown joints"):
        DuckConfig.load(path)


@pytest.mark.parametrize("field", ["start_paused", "imu_upside_down"])
def test_config_rejects_string_booleans(tmp_path: Path, field: str) -> None:
    payload = {
        "start_paused": True,
        "imu_upside_down": False,
        "phase_frequency_factor_offset": 0.0,
        "joints_offsets": {name: 0.0 for name in JOINT_NAMES},
    }
    payload[field] = "false"
    path = tmp_path / "invalid-bool.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ConfigError, match=f"{field} must be a JSON boolean"):
        DuckConfig.load(path)


def test_config_rejects_nonnumeric_phase_offset(tmp_path: Path) -> None:
    payload = {
        "start_paused": True,
        "imu_upside_down": False,
        "phase_frequency_factor_offset": "not-a-number",
        "joints_offsets": {name: 0.0 for name in JOINT_NAMES},
    }
    path = tmp_path / "invalid-phase.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ConfigError, match="phase_frequency_factor_offset must be numeric"):
        DuckConfig.load(path)
