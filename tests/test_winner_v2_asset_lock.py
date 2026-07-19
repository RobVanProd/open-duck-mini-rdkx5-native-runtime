from __future__ import annotations

import json
import runpy
from pathlib import Path
from types import FunctionType

import pytest

NAMESPACE = runpy.run_path("tools/verify_winner_v2_asset_lock.py")
AssetLockError = NAMESPACE["AssetLockError"]
verify_asset_lock: FunctionType = NAMESPACE["verify_asset_lock"]
verify_files: FunctionType = NAMESPACE["verify_files"]


def _load_lock() -> dict[str, object]:
    return json.loads(
        Path(
            "artifacts/gates/phase_5_policy/"
            "winner_v2_offline_asset_lock_20260719.json"
        ).read_text(encoding="utf-8")
    )


def test_asset_lock_keeps_all_hardware_authority_false(tmp_path: Path) -> None:
    lock = _load_lock()
    lock["authority"]["gate5"] = True
    lock_path = tmp_path / "lock.json"
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    with pytest.raises(AssetLockError, match="broadened authority: gate5"):
        verify_asset_lock(
            lock_path,
            runtime_root=tmp_path,
            policy_repo_root=tmp_path,
        )


def test_asset_lock_freezes_corrected_knee_and_runtime_semantics() -> None:
    lock = _load_lock()
    semantics = lock["config_asset"]["semantics"]
    assert semantics["start_paused"] is True
    assert semantics["imu_upside_down"] is True
    assert semantics["phase_frequency_factor_offset"] == 0.0
    assert semantics["joints_offsets_rad_in_contract_order"][3] == 0.0371
    assert lock["policy_assets"]["selected_checkpoint_step"] == 512000
    assert lock["authority"]["robot_clearance"] is False


def test_verify_files_detects_changed_bytes(tmp_path: Path) -> None:
    path = tmp_path / "asset.bin"
    path.write_bytes(b"expected")
    with pytest.raises(AssetLockError, match="hash mismatch"):
        verify_files(
            tmp_path,
            {"asset.bin": "0" * 64},
            label="fixture",
        )
