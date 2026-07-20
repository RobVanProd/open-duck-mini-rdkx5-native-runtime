from __future__ import annotations

from open_duck_x5.winner_v6_dynamic_calibration_review import (
    CONTEXT_DIMENSION,
    CONTEXT_FIELDS,
    build_review,
)


def test_dynamic_calibration_review_preserves_v1_and_accepts_v2_schema() -> None:
    review = build_review()
    assert review["status"] == "PASS_DYNAMIC_CALIBRATION_SCHEMA_HOLD_CPU_CONTRACT"
    assert review["compatibility_boundary"]["runtime_v1_101x14_unchanged"] is True
    assert review["compatibility_boundary"]["runtime_v2_implementation_present"] is False
    assert review["accepted_calibrator_abi"]["inputs"] == [
        {"name": "obs", "dtype": "float32", "shape": [1, 115]},
        {"name": "previous_action", "dtype": "float32", "shape": [1, 14]},
        {"name": "h_in", "dtype": "float32", "shape": [1, 64]},
    ]
    assert review["accepted_locomotion_abi"]["context_order"] == list(CONTEXT_FIELDS)
    assert CONTEXT_DIMENSION == len(CONTEXT_FIELDS) == len(set(CONTEXT_FIELDS)) == 64


def test_dynamic_calibration_review_is_review_only_and_fail_closed() -> None:
    review = build_review()
    assert review["runtime_implementation"] == {
        "source_or_policy_loader_changed": False,
        "control_loop_changed": False,
        "hardware_path_reachable": False,
        "review_artifact_only": True,
    }
    assert review["authority"]["policy_zero_ppo_cpu_contract"] is True
    assert review["authority"]["training_or_hosted_compute"] is False
    assert review["authority"]["rdkx5_or_robot"] is False
    assert any(
        "every runtime process start" in rule for rule in review["required_fail_closed_rules"]
    )
