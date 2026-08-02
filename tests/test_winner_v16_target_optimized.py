from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

from tools.winner_v16_target_optimized import WinnerV16TargetOptimizedTransaction

PREREGISTRATION = Path(
    "artifacts/gates/phase_5_policy/"
    "t251a5_target_correction_preregistration_20260731.json"
)
RESULT = Path(
    "artifacts/gates/phase_5_policy/"
    "t251a5_target_cpu_contract_result_20260731.json"
)
CORRECTED_HOST = Path("tools/winner_v16_target_optimized.py")
VERIFIER = Path("tools/verify_winner_v16_target_optimized.py")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_t251a5_target_correction_is_exactly_preregistered() -> None:
    assert sha256(PREREGISTRATION) == (
        "e266defdc3eb3dfb4e24e882d526c2e2cd425a95b14e6ddc0c28708bd03f2fd4"
    )
    value = json.loads(PREREGISTRATION.read_text(encoding="utf-8"))
    assert value["status"] == "PREREGISTERED_T251A5_TARGET_ONLY_CORRECTION"
    assert value["earned_by"]["selected_component"] == "target"
    assert value["correction"]["new_default_off_host"] == str(CORRECTED_HOST).replace(
        "\\", "/"
    )
    assert value["decision_rule"]["x5_execution"] is False
    assert value["decision_rule"]["t251b_earned"] is False
    assert value["decision_rule"]["gate5_earned"] is False
    assert value["authority"]["motion"] is False


def test_t251a5_real_asset_cpu_contract_and_microbenchmark_pass() -> None:
    assert sha256(RESULT) == (
        "ecd2ae6b1053b258af0069a2228b888e01fd6cf9df66fcaa55ffe9e75d7616f4"
    )
    value = json.loads(RESULT.read_text(encoding="utf-8"))
    assert value["status"] == "PASS_T251A5_TARGET_CPU_CONTRACT"
    assert value["result_sha256"] == (
        "a8b0a71b83956fd72a21690c62c201b3d0f7e06722c310c53f8063e6945255b6"
    )
    assert value["failed_checks"] == []
    assert all(value["checks"].values())
    semantic = value["semantic_contract"]
    assert semantic["mismatch"] is None
    assert semantic["calibration_ticks"] == 250
    assert semantic["locomotion_ticks"] == 2_048
    assert semantic["handoff_switches"] == 1
    assert semantic["offsets_are_immutable"] is True
    assert semantic["desired_and_sent_are_identical_buffer"] is True
    assert semantic["predecessor_action_trace_sha256"] == semantic[
        "corrected_action_trace_sha256"
    ]
    benchmark = value["local_target_microbenchmark"]
    assert benchmark["samples"] == 20_000
    assert benchmark["alternated_order"] is True
    assert benchmark["mismatch_tick"] is None
    assert benchmark["corrected_to_predecessor_median_ratio"] <= 0.75
    assert value["decision"] == "EARN_T251A5_X5_SCREEN_PREREGISTRATION_ONLY"
    assert value["authority"]["x5_execution"] is False
    assert value["authority"]["t251b_earned"] is False
    assert value["authority"]["gate5"] is False


def test_t251a5_result_pins_exact_sources() -> None:
    value = json.loads(RESULT.read_text(encoding="utf-8"))
    expected = {
        "transaction": Path("src/open_duck_x5/winner_v13_state_coherent.py"),
        "predecessor_host": Path("tools/winner_v15_graph_host_optimized.py"),
        "corrected_host": CORRECTED_HOST,
        "verifier": VERIFIER,
    }
    for name, path in expected.items():
        assert value["source_receipts"][name]["sha256"] == sha256(path)


def test_t251a5_is_default_disabled_and_absent_from_production() -> None:
    assert WinnerV16TargetOptimizedTransaction.__mro__[1].__name__ == (
        "WinnerV15GraphHostOptimizedTransaction"
    )
    for path in Path("src/open_duck_x5").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "winner_v16_target_optimized" not in source
        assert "WinnerV16TargetOptimizedTransaction" not in source


def test_t251a5_verifier_has_no_robot_or_training_imports() -> None:
    tree = ast.parse(VERIFIER.read_text(encoding="utf-8"), filename=str(VERIFIER))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add("." * node.level + (node.module or ""))
    assert imported.isdisjoint(
        {
            "serial",
            "smbus2",
            "pygame",
            "open_duck_x5.runtime",
            "open_duck_x5.servo_bus",
            "open_duck_x5.sensors",
        }
    )
    source = VERIFIER.read_text(encoding="utf-8")
    assert '"policy_deployed": False' in source
    assert '"t251b_earned": False' in source
    assert '"gate5": False' in source
