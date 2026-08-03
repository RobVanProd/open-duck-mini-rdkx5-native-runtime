from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

from tools.winner_v18_transaction_optimized import (
    WinnerV18TransactionOptimizedTransaction,
)

PREREGISTRATION = Path(
    "artifacts/gates/phase_5_policy/"
    "t251a7_transaction_residual_correction_preregistration_20260731.json"
)
RESULT = Path(
    "artifacts/gates/phase_5_policy/"
    "t251a7_transaction_cpu_contract_result_20260731.json"
)
REVIEW = Path(
    "artifacts/gates/phase_5_policy/"
    "t251a7_transaction_cpu_contract_review_20260731.json"
)
CORRECTED_HOST = Path("tools/winner_v18_transaction_optimized.py")
VERIFIER = Path("tools/verify_winner_v18_transaction_optimized.py")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_t247_transaction_correction_is_exactly_preregistered() -> None:
    assert sha256(PREREGISTRATION) == (
        "7bd6f29f4487b37729f4360c0d5de564279e69c8e689c47d3cda9e298c09b044"
    )
    value = json.loads(PREREGISTRATION.read_text(encoding="utf-8"))
    assert value["status"] == (
        "PREREGISTERED_T251A7_TRANSACTION_RESIDUAL_ONLY_CORRECTION"
    )
    assert value["unchanged_assets"]["candidate_id"] == (
        "T247_HOME_NEGATIVE_HALF_ADAPTER_FINAL"
    )
    assert value["correction"]["new_default_off_host"] == str(
        CORRECTED_HOST
    ).replace("\\", "/")
    assert value["decision_rule"]["x5_execution"] is False
    assert value["authority"]["motion"] is False


def test_t247_transaction_contract_is_exact_but_closes_on_materiality() -> None:
    assert sha256(RESULT) == (
        "1a179ff8f23b23a19e2e296287a351d5096dcf363b3a1ab6bbcd646091b7e577"
    )
    value = json.loads(RESULT.read_text(encoding="utf-8"))
    assert value["status"] == "FAIL_T251A7_TRANSACTION_CPU_CONTRACT"
    assert value["result_sha256"] == (
        "54fc59dabea7ce725cbd5bcfaca3698660ced114834c0f22a325c4903e7ed69a"
    )
    assert value["failed_checks"] == [
        "microbenchmark_median_improves_at_least_25_percent"
    ]
    semantic = value["semantic_contract"]
    assert semantic["mismatch"] is None
    assert semantic["calibration_ticks"] == 250
    assert semantic["locomotion_ticks"] == 2_048
    assert semantic["handoff_switches"] == 1
    assert semantic["predecessor_action_trace_sha256"] == semantic[
        "corrected_action_trace_sha256"
    ]
    assert value["fallback_contract"]["all_exact"] is True
    assert len(value["fallback_contract"]["cases"]) == 7
    assert value["fault_contract"]["all_exact"] is True
    assert len(value["fault_contract"]["cases"]) == 6
    benchmark = value["local_transaction_microbenchmark"]
    assert benchmark["samples"] == 20_000
    assert benchmark["mismatch_tick"] is None
    assert benchmark["corrected_to_predecessor_median_ratio"] > 0.75
    assert value["decision"] == "CLOSE_T251A7_WITHOUT_X5_EXECUTION"
    assert value["authority"]["x5_execution"] is False
    assert value["authority"]["gate5"] is False


def test_t247_transaction_review_selects_only_observer_stage_next() -> None:
    assert sha256(REVIEW) == (
        "1d1733d993ed3f72b50867dc54dd9694da4c1bdb73e8224f25a87d53f9580607"
    )
    value = json.loads(REVIEW.read_text(encoding="utf-8"))
    assert value["status"] == (
        "CLOSED_T251A7_TRANSACTION_RESIDUAL_CORRECTION_AS_TOO_SMALL"
    )
    assert value["semantic_result"]["all_2298_ticks_byte_exact"] is True
    assert value["microbenchmark_result"]["material_improvement"] is False
    assert value["next_measured_component"]["name"] == "observer_stage"
    assert value["decision"]["t251b_earned"] is False
    assert value["authority"]["x5_execution"] is False


def test_t247_transaction_result_pins_exact_sources() -> None:
    value = json.loads(RESULT.read_text(encoding="utf-8"))
    expected = {
        "transaction": Path("src/open_duck_x5/winner_v13_state_coherent.py"),
        "predecessor_host": Path("tools/winner_v16_target_optimized.py"),
        "corrected_host": CORRECTED_HOST,
        "verifier": VERIFIER,
    }
    for name, path in expected.items():
        assert value["source_receipts"][name]["sha256"] == sha256(path)


def test_t247_transaction_host_is_default_disabled_and_cpu_only() -> None:
    assert WinnerV18TransactionOptimizedTransaction.__mro__[1].__name__ == (
        "WinnerV16TargetOptimizedTransaction"
    )
    for path in Path("src/open_duck_x5").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "winner_v18_transaction_optimized" not in source
        assert "WinnerV18TransactionOptimizedTransaction" not in source
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
