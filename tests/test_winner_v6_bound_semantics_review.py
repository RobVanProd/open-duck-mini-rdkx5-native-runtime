from __future__ import annotations

from open_duck_x5.winner_v6_bound_semantics_review import build_review


def test_review_splits_default_enabled_and_physical_populations() -> None:
    review = build_review()
    split = review["accepted_semantic_split"]
    assert review["status"] == "PASS_BOUND_SEMANTICS_SPLIT_HOLD_V6B_CONTRACT"
    assert split["default_off_identity"]["new_adapter_projection_applied"] is False
    assert split["default_off_identity"]["double_limiting_permitted"] is False
    assert split["enabled_adapter_projection"]["new_adapter_projection_applied"] is True
    assert (
        split["protected_full_action_contract"][
            "independent_joint_state_and_previous_action_pairs_valid"
        ]
        is False
    )


def test_review_keeps_failed_contract_and_runtime_held() -> None:
    review = build_review()
    assert review["policy_evidence"]["completed_formal_result_reclassified"] is False
    assert review["policy_evidence"]["completed_formal_contract_retry_authorized"] is False
    assert review["v6b_contract_constraints"]["same_network_weights"] is True
    assert review["v6b_contract_constraints"]["only_allowed_change"].startswith(
        "split the bound assertions"
    )
    assert review["runtime_implementation"]["review_artifact_only"] is True
    assert review["authority"]["training_or_ppo"] is False
    assert review["authority"]["rdkx5_or_robot"] is False
