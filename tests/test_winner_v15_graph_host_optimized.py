from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

from tools.winner_v15_graph_host_optimized import (
    WinnerV15GraphHostOptimizedTransaction,
)

PREREGISTRATION = Path(
    "artifacts/gates/phase_5_policy/"
    "t251a4_graph_host_correction_preregistration_20260731.json"
)
RESULT = Path(
    "artifacts/gates/phase_5_policy/"
    "t251a4_graph_host_cpu_contract_result_20260731.json"
)
VERIFIER = Path("tools/verify_winner_v15_graph_host_optimized.py")
CORRECTED_HOST = Path("tools/winner_v15_graph_host_optimized.py")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_t251a4_correction_was_preregistered_without_advancement() -> None:
    assert sha256(PREREGISTRATION) == (
        "f556a2d55386ed9eb0e7389429c7b86a6374200c444be080a0315d11c15ff1d9"
    )
    value = json.loads(PREREGISTRATION.read_text(encoding="utf-8"))
    assert value["status"] == "PREREGISTERED_T251A4_GRAPH_HOST_ONLY_CORRECTION"
    assert value["earned_by"]["selected_component"] == "graph_host"
    assert value["correction"]["new_default_off_host"] == str(CORRECTED_HOST).replace(
        "\\", "/"
    )
    assert value["authority"]["x5_execution"] is False
    assert value["decision_rule"]["t251b_earned"] is False
    assert value["decision_rule"]["gate5_earned"] is False
    assert value["authority"]["motion"] is False


def test_t251a4_real_asset_cpu_contract_is_exact_and_cannot_advance() -> None:
    assert sha256(RESULT) == (
        "c33906f75cceb746b46e2b331fe13a71d4fc246fafcaa0b5e72d871d32ccfb27"
    )
    value = json.loads(RESULT.read_text(encoding="utf-8"))
    assert value["status"] == "PASS_T251A4_GRAPH_HOST_CPU_CONTRACT"
    assert value["result_sha256"] == (
        "7b4b4b015f2bb69323bb2cf1d794d94817a3e977a09306f11c91cc59fa313595"
    )
    assert value["failed_checks"] == []
    assert all(value["checks"].values())
    semantic = value["semantic_contract"]
    assert semantic["mismatch"] is None
    assert semantic["calibration_ticks"] == 250
    assert semantic["locomotion_ticks"] == 2_048
    assert semantic["handoff_switches"] == 1
    assert semantic["baseline_action_trace_sha256"] == semantic[
        "corrected_action_trace_sha256"
    ]
    assert semantic["maximum_rate_excess_rad_s"] == 0.0
    assert value["local_x86_timing_informational_only"]["selection_weight"] == 0
    assert value["decision"] == "EARN_T251A4_X5_SCREEN_PREREGISTRATION_ONLY"
    assert value["authority"]["x5_execution"] is False
    assert value["authority"]["t251b_earned"] is False
    assert value["authority"]["policy_deployed"] is False
    assert value["authority"]["gate5"] is False


def test_t251a4_result_pins_the_exact_corrected_sources() -> None:
    value = json.loads(RESULT.read_text(encoding="utf-8"))
    expected = {
        "transaction": Path("src/open_duck_x5/winner_v13_state_coherent.py"),
        "predecessor_host": Path("tools/winner_v14_optimized.py"),
        "corrected_host": CORRECTED_HOST,
        "verifier": VERIFIER,
    }
    for name, path in expected.items():
        assert value["source_receipts"][name]["sha256"] == sha256(path)


def test_t251a4_is_default_disabled_and_absent_from_production() -> None:
    assert WinnerV15GraphHostOptimizedTransaction.__mro__[1].__name__ == (
        "WinnerV14X5OptimizedTransaction"
    )
    for path in Path("src/open_duck_x5").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "winner_v15_graph_host_optimized" not in source
        assert "WinnerV15GraphHostOptimizedTransaction" not in source


def test_t251a4_verifier_has_no_robot_or_training_imports() -> None:
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
    assert "policy_deployed\": False" in source
    assert "t251b_earned\": False" in source
    assert "gate5\": False" in source
