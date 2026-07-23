from __future__ import annotations

import json
import runpy
from pathlib import Path
from types import FunctionType

import pytest

NAMESPACE = runpy.run_path("tools/verify_winner_v2_asset_freeze.py")
AssetFreezeError = NAMESPACE["AssetFreezeError"]
verify_asset_freeze: FunctionType = NAMESPACE["verify_asset_freeze"]
CLOSURE = Path(
    "artifacts/gates/phase_5_policy/"
    "winner_v2_final_asset_freeze_closure_20260719.json"
)


def test_final_asset_freeze_verifies_self_contained_evidence() -> None:
    result = verify_asset_freeze(CLOSURE, runtime_root=Path.cwd())
    assert result["status"] == "PASS_FINAL_OFFLINE_ASSET_FREEZE"
    assert result["policy_checks_verified"] >= 40
    assert result["authority"]["robot_clearance"] is False
    assert result["authority"]["gate5"] is False


def test_final_asset_freeze_rejects_broadened_authority(tmp_path: Path) -> None:
    closure = json.loads(CLOSURE.read_text(encoding="utf-8"))
    closure["authority"]["gate5"] = True
    changed = tmp_path / "closure.json"
    changed.write_text(json.dumps(closure), encoding="utf-8")
    with pytest.raises(AssetFreezeError, match="broadened authority: gate5"):
        verify_asset_freeze(changed, runtime_root=Path.cwd())
