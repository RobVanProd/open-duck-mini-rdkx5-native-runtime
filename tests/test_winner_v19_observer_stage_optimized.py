from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

from tools.winner_v19_observer_stage_optimized import (
    WinnerV19ObserverStageOptimizedTransaction,
)

PREREGISTRATION = Path(
    "artifacts/gates/phase_5_policy/"
    "t251a8_observer_stage_correction_preregistration_20260731.json"
)
RESULT = Path(
    "artifacts/gates/phase_5_policy/"
    "t251a8_observer_stage_cpu_contract_result_20260731.json"
)
REVIEW = Path(
    "artifacts/gates/phase_5_policy/"
    "t251a8_observer_stage_cpu_contract_review_20260731.json"
)
CORRECTED_HOST = Path("tools/winner_v19_observer_stage_optimized.py")
VERIFIER = Path("tools/verify_winner_v19_observer_stage_optimized.py")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_t247_observer_correction_is_exactly_preregistered() -> None:
    assert sha256(PREREGISTRATION) == (
        "78994328c3bebc6f70392d06d39212bbc7cc5adcd0f8008d4e02f8f54e959ece"
    )
    value = json.loads(PREREGISTRATION.read_text(encoding="utf-8"))
    assert value["status"] == (
        "PREREGISTERED_T251A8_OBSERVER_STAGE_ONLY_CORRECTION"
    )
    assert value["unchanged_assets"]["candidate_id"] == (
        "T247_HOME_NEGATIVE_HALF_ADAPTER_FINAL"
    )
    assert value["correction"]["new_default_off_host"] == str(
        CORRECTED_HOST
    ).replace("\\", "/")
    assert value["decision_rule"]["x5_execution"] is False
    assert value["authority"]["motion"] is False


def test_t247_observer_contract_is_exact_but_closes_on_materiality() -> None:
    assert sha256(RESULT) == (
        "6dd88f528c2b91e92448dcc74bf81a01083032d26b8f3c53c8c7629185103867"
    )
    value = json.loads(RESULT.read_text(encoding="utf-8"))
    assert value["status"] == "FAIL_T251A8_OBSERVER_STAGE_CPU_CONTRACT"
    assert value["result_sha256"] == (
        "fc4884e3d367fbab67517ea4ba38b7083b2afa381fbd3f9e64a126d72057af8a"
    )
    assert value["failed_checks"] == [
        "stage_microbenchmark_median_improves_at_least_25_percent"
    ]
    semantic = value["semantic_contract"]
    assert semantic["mismatch"] is None
    assert semantic["calibration_ticks"] == 250
    assert semantic["locomotion_ticks"] == 2_048
    assert semantic["handoff_switches"] == 1
    assert semantic["calibration_used_predecessor_observer_path"] is True
    assert semantic["post_handoff_target_identity_bound"] is True
    assert semantic["predecessor_action_trace_sha256"] == semantic[
        "corrected_action_trace_sha256"
    ]
    assert value["boundary_contract"]["all_exact"] is True
    stage_result = value["local_observer_microbenchmarks"]["stage_only"]
    assert stage_result["samples"] == 20_000
    assert stage_result["mismatch_tick"] is None
    assert stage_result["corrected_to_predecessor_median_ratio"] > 0.75
    total_result = value["local_observer_microbenchmarks"]["stage_plus_commit"]
    assert total_result["mismatch_tick"] is None
    assert total_result["corrected_to_predecessor_median_ratio"] <= 1.1
    assert value["decision"] == "CLOSE_T251A8_WITHOUT_X5_EXECUTION"
    assert value["authority"]["x5_execution"] is False
    assert value["authority"]["gate5"] is False


def test_t247_observer_review_closes_component_local_search() -> None:
    assert sha256(REVIEW) == (
        "5deb6fa14ceb70dff7cda0a89460b5974e5f72366d7a5962375b5813923286e6"
    )
    value = json.loads(REVIEW.read_text(encoding="utf-8"))
    assert value["status"] == (
        "CLOSED_T251A8_OBSERVER_STAGE_CORRECTION_AS_TOO_SMALL"
    )
    assert value["semantic_result"]["all_2298_ticks_byte_exact"] is True
    assert value["microbenchmark_result"]["stage_only"][
        "material_improvement"
    ] is False
    boundary = value["component_local_search_boundary"]
    assert boundary["status"] == (
        "EXHAUSTED_WITHOUT_CLEARING_X5_REFERENCE_RESERVE"
    )
    assert boundary["remaining_eligible_components"] == []
    assert value["decision"]["t251b_earned"] is False
    assert value["authority"]["x5_execution"] is False


def test_t247_observer_result_pins_exact_sources() -> None:
    value = json.loads(RESULT.read_text(encoding="utf-8"))
    expected = {
        "observer": Path("tools/winner_v14_optimized.py"),
        "predecessor_host": Path("tools/winner_v16_target_optimized.py"),
        "corrected_host": CORRECTED_HOST,
        "verifier": VERIFIER,
    }
    for name, path in expected.items():
        assert value["source_receipts"][name]["sha256"] == sha256(path)


def test_t247_observer_host_is_default_disabled_and_cpu_only() -> None:
    assert WinnerV19ObserverStageOptimizedTransaction.__mro__[1].__name__ == (
        "WinnerV16TargetOptimizedTransaction"
    )
    for path in Path("src/open_duck_x5").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "winner_v19_observer_stage_optimized" not in source
        assert "WinnerV19ObserverStageOptimizedTransaction" not in source
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
    assert '"x5_execution": False' in source
    assert '"policy_deployed": False' in source
    assert '"gate5": False' in source
