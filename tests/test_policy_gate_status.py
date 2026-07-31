from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATUS = ROOT / "status" / "policy_gate.json"


def _status() -> dict[str, object]:
    return json.loads(STATUS.read_text(encoding="utf-8"))


def test_policy_gate_status_is_fail_closed_while_t237_is_partial() -> None:
    status = _status()
    t237 = status["gates"]["t237_full_r2"]
    authority = status["authority"]

    assert status["schema_version"] == (
        "open_duck.runtime_policy_gate_status.v1"
    )
    assert status["status"] == "T237_FULL_R2_IN_PROGRESS"
    assert t237["status"] == "IN_PROGRESS"
    assert t237["completed_conditions"] == 5
    assert t237["expected_conditions"] == 20
    assert t237["green_completed_cells"] == 80
    assert t237["completed_cells"] == 80
    assert t237["maximum_cells"] == 320
    assert status["gates"]["t238_deployment_contract_audit"] == (
        "NOT_PREREGISTERED"
    )
    assert status["gates"]["gate_5"] == "NOT_RUN"
    assert authority["robot_clearance"] is False
    assert authority["gate_5_authorized"] is False
    assert authority["policy_deployment_authorized"] is False


def test_policy_gate_status_pins_runtime_v2_abi_and_both_graphs() -> None:
    status = _status()
    abi = status["candidate_abi"]
    graphs = status["candidate_graphs"]

    assert abi["inputs"] == {
        "obs": [1, 115],
        "previous_action": [1, 14],
        "calibration_context": [1, 64],
        "h_in": [1, 64],
    }
    assert abi["outputs"] == {
        "continuous_actions": [1, 14],
        "previous_action_out": [1, 14],
        "h_out": [1, 64],
    }
    assert [graph["role"] for graph in graphs] == ["half", "final"]
    assert [graph["step"] for graph in graphs] == [1003520, 2007040]
    assert all(graph["bytes"] == 988264 for graph in graphs)
    assert all(len(graph["sha256"]) == 64 for graph in graphs)
    assert len({graph["sha256"] for graph in graphs}) == 2


def test_policy_gate_status_points_to_the_evidence_archive() -> None:
    status = _status()
    evidence = status["evidence_repository"]

    assert evidence["url"] == (
        "https://github.com/RobVanProd/open-duck-mini-rdkx5"
    )
    assert evidence["branch"] == "codex/winner-v4-response-contract"
    assert evidence["branch_head"] == "0058ac51"
    assert evidence["local_remote_divergence_after_push"] == [0, 0]
