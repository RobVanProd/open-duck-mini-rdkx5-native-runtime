from __future__ import annotations

import hashlib
import json
from pathlib import Path

from open_duck_x5.winner_v6_dynamic_calibration_review import (
    build_review as build_v6_review,
)
from open_duck_x5.winner_v11_dynamic_calibration_review import (
    POLICY_ARTIFACT_CLAIMED_SHA256,
    POLICY_ARTIFACT_COMMITTED_SHA256,
    POLICY_COMMIT,
    WINNER_V10_FINAL_SHA256,
    WINNER_V10_HALF_SHA256,
    build_review,
    main,
)


def test_winner_v11_reuses_exact_reviewed_dual_state_abi() -> None:
    review = build_review()
    prior = build_v6_review()

    assert review["policy_request"]["commit"] == POLICY_COMMIT
    assert review["policy_request"]["claimed_artifact_sha256"] == (
        POLICY_ARTIFACT_CLAIMED_SHA256
    )
    assert review["policy_request"]["committed_artifact_sha256"] == (
        POLICY_ARTIFACT_COMMITTED_SHA256
    )
    assert review["accepted_interface"]["calibrator"]["inputs"] == (
        prior["accepted_calibrator_abi"]["inputs"]
    )
    assert review["accepted_interface"]["calibrator"]["outputs"] == (
        prior["accepted_calibrator_abi"]["outputs"]
    )
    assert review["accepted_interface"]["locomotion"]["inputs"] == (
        prior["accepted_locomotion_abi"]["inputs"]
    )
    assert review["accepted_interface"]["locomotion"]["outputs"] == (
        prior["accepted_locomotion_abi"]["outputs"]
    )


def test_winner_v11_pins_new_base_without_reopening_closed_results() -> None:
    review = build_review()
    protected = review["protected_winner_v10_base"]
    provenance = review["reviewed_provenance"]

    assert protected["policy_sha256"] == {
        "half": WINNER_V10_HALF_SHA256,
        "final": WINNER_V10_FINAL_SHA256,
    }
    assert protected["r2_condition7_terminal_hold_preserved"] is True
    assert protected["robot_clearance"] is False
    assert provenance["closed_v6b_result"]["reclassified"] is False
    assert provenance["closed_v6b_result"]["retry_authorized"] is False
    assert review["runtime_feasibility"]["winner_v10_requires_runtime_semantic_change"] is False
    sequence = review["required_winner_v6_sequence_inheritance"]
    assert sequence["frequency_hz"] == 50
    assert sequence["calibration_phase"] == [1.0, 0.0]
    assert sequence["calibration_phase_advances"] is False
    assert sequence["context_bounds"] == [-1.0, 1.0]
    assert len(sequence["context_order"]) == 64
    assert sequence["runtime_remains_paused_after_handoff"] is True


def test_winner_v11_holds_zero_ppo_and_all_broader_authority() -> None:
    review = build_review()
    contract = review["zero_ppo_cpu_mechanics_contract"]
    authority = review["authority"]

    assert contract["optimizer_steps"] == 0
    assert contract["formal_behavior_cells"] == 0
    assert contract["default_off_continuous_actions_bit_exact_to_winner_v10"] is True
    assert contract["default_off_previous_action_out_bit_exact_to_winner_v10"] is True
    assert contract["host_must_not_add_second_limiter_or_projection"] is True
    assert contract["inward_torque_bounds_are_plant_xml_semantics"] is True
    assert contract["host_must_not_translate_torque_bounds_into_action_limits"] is True
    assert contract["execution_authorized_by_this_review"] is False
    assert authority["policy_metadata_hash_correction"] is True
    assert authority["policy_freeze_zero_ppo_cpu_mechanics_contract"] is False
    assert authority["policy_run_zero_ppo_cpu_mechanics_contract"] is False
    for prohibited in (
        "training_or_optimizer",
        "colab_hosted_gpu_or_igpu",
        "runtime_policy_implementation",
        "rdkx5_or_robot",
        "serial_gpio_i2c",
        "torque_or_motion",
        "gate5_or_deployment",
        "robot_clearance",
    ):
        assert authority[prohibited] is False


def test_condition7_x0_does_not_become_a_host_deadband() -> None:
    review = build_review()
    evidence = review["condition7_x0_evidence"]
    feasibility = review["runtime_feasibility"]
    contract = review["zero_ppo_cpu_mechanics_contract"]

    assert evidence["trace_population"] == 4
    assert evidence["all_trace_sha256"] == (
        "2303e73ed34a77ab5b46e70f622ebf7f97290d83af8826ecce3542cd2f79641e"
    )
    assert evidence["all_traces_byte_identical"] is True
    assert evidence["all_samples"] == 47
    assert evidence["winner_v10_x0_action_and_state_exact_zero"] is True
    assert feasibility["existing_runtime_v2_forces_x0_action_zero"] is False
    assert feasibility["existing_runtime_v2_can_remain_default_off_review_only"] is True
    assert contract["default_off_x0_remains_exact_winner_v10_deadband"] is True
    assert contract["future_enabled_x0_action_is_graph_authoritative"] is True
    assert contract["runtime_must_not_independently_force_enabled_x0_action_zero"] is True
    assert contract["future_enabled_x0_requires_separate_behavior_gate"] is True


def test_crlf_receipts_hold_zero_ppo_authority() -> None:
    review = build_review()
    binding = review["hash_binding_review"]

    assert POLICY_ARTIFACT_CLAIMED_SHA256 != POLICY_ARTIFACT_COMMITTED_SHA256
    assert binding["policy_artifact_claim_matches_committed_bytes"] is False
    assert binding["policy_artifact_claim_matches_lf_to_crlf_transcoding"] is True
    assert binding["platform_dependent_hash_binding"] is True
    assert len(binding["mismatched_sources"]) == 6
    for evidence in binding["mismatched_sources"].values():
        assert evidence["claimed"] != evidence["committed"]
    assert binding["all_embedded_source_hashes_match_committed_bytes"] is False


def test_winner_v11_review_cli_hash_binds_markdown(tmp_path: Path) -> None:
    output = tmp_path / "result.json"
    markdown = tmp_path / "RESULT.md"

    assert main(["--output", str(output), "--markdown", str(markdown)]) == 0
    payload = output.read_bytes()
    assert b"\r\n" not in payload
    assert json.loads(payload) == build_review()
    digest = hashlib.sha256(payload).hexdigest()
    text = markdown.read_text(encoding="utf-8")
    assert digest in text
    assert POLICY_ARTIFACT_CLAIMED_SHA256 in text
    assert POLICY_ARTIFACT_COMMITTED_SHA256 in text
    assert "may not be frozen or run" in text
