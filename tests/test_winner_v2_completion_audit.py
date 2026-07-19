from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from open_duck_x5.winner_v2_completion_audit import (
    EXPECTED_SHA256,
    WinnerV2CompletionAuditError,
    audit_winner_v2_completion,
)


def _copy_inputs(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    for relative_path in EXPECTED_SHA256:
        destination = root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(relative_path, destination)
    source_root = root / "src/open_duck_x5"
    for name in ("winner_v2_verifier.py", "winner_v2_cpu_preflight.py"):
        shutil.copyfile(Path("src/open_duck_x5") / name, source_root / name)
    return root


def test_completion_audit_separates_offline_pass_from_pending_campaign() -> None:
    result = audit_winner_v2_completion(repo_root=Path.cwd())

    assert result["status"] == "HOLD_POLICY_ENVELOPE_AND_PHYSICAL_GATES"
    assert result["offline_runtime_v2_complete"] is True
    assert result["goal_complete"] is False
    assert all(item["status"] == "PASS" for item in result["offline_requirements"])
    campaign = {item["id"]: item["status"] for item in result["campaign_requirements"]}
    assert campaign["manual_com_measurement_packet"] == "SUPERSEDED_NO_MEASUREMENT"
    assert campaign["supported_configuration_envelope"] == "PENDING_POLICY"
    assert campaign["x5_cpu_only_preflight"] == "NOT_RUN"
    assert all(value is False for value in result["authority"].values())


def test_completion_audit_rejects_coherently_unreviewed_artifact_change(
    tmp_path: Path,
) -> None:
    root = _copy_inputs(tmp_path)
    result_path = (
        root
        / "artifacts/gates/phase_5_policy/winner_v2_runtime_v2_verification_20260719.json"
    )
    result_path.write_bytes(result_path.read_bytes() + b" ")

    with pytest.raises(WinnerV2CompletionAuditError, match="frozen identity changed"):
        audit_winner_v2_completion(repo_root=root)


def test_completion_audit_rejects_production_runtime_import(tmp_path: Path) -> None:
    root = _copy_inputs(tmp_path)
    (root / "src/open_duck_x5/runtime.py").write_text(
        "from .winner_v2 import WinnerV2TickTransaction\n",
        encoding="utf-8",
    )

    with pytest.raises(WinnerV2CompletionAuditError, match="enables winner-v2"):
        audit_winner_v2_completion(repo_root=root)
