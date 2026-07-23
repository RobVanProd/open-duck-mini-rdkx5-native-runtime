from __future__ import annotations

import hashlib
import json
from pathlib import Path

from open_duck_x5.winner_v11_dynamic_calibration_rereview import (
    POLICY_ARTIFACT_SHA256,
    POLICY_COMMIT,
    PRIOR_RUNTIME_HOLD_COMMIT,
    PRIOR_RUNTIME_HOLD_SHA256,
    SOURCE_RECEIPTS,
    build_review,
    main,
)
from open_duck_x5.winner_v11_dynamic_calibration_review import (
    build_review as build_hold_review,
)


def test_rereview_closes_only_the_lf_binding_hold() -> None:
    review = build_review()
    closure = review["hash_correction_closure"]

    assert review["policy_request"]["commit"] == POLICY_COMMIT
    assert review["policy_request"]["committed_lf_sha256"] == POLICY_ARTIFACT_SHA256
    assert closure["prior_runtime_hold_commit"] == PRIOR_RUNTIME_HOLD_COMMIT
    assert closure["prior_runtime_hold_artifact_sha256"] == PRIOR_RUNTIME_HOLD_SHA256
    assert closure["prior_hold_reclassified"] is False
    assert closure["metadata_only_correction"] is True
    assert closure["graph_abi_gate_or_authority_changed"] is False
    assert closure["zero_ppo_run_started_before_review"] is False
    assert closure["source_receipts"] == SOURCE_RECEIPTS
    assert closure["source_receipt_count"] == 9
    assert closure["all_source_receipts_match_committed_git_blobs"] is True
    assert closure["lf_hash_binding_closed"] is True


def test_rereview_keeps_exact_abi_and_sequence_contract() -> None:
    review = build_review()
    hold = build_hold_review()

    assert review["accepted_interface"]["calibrator"] == (
        hold["accepted_interface"]["calibrator"]
    )
    assert review["accepted_interface"]["locomotion"] == (
        hold["accepted_interface"]["locomotion"]
    )
    sequence = review["required_sequence_semantics"]
    assert sequence["frequency_hz"] == 50
    assert sequence["calibrator_initial_previous_action"].endswith("zeros[1,14]")
    assert sequence["calibrator_initial_hidden_state"].endswith("zeros[1,64]")
    assert sequence["calibration_command"].endswith("zeros[7]")
    assert sequence["calibration_phase"] == [1.0, 0.0]
    assert sequence["calibration_phase_advances"] is False
    assert sequence["context_bounds_inclusive"] == [-1.0, 1.0]
    assert sequence["runtime_remains_paused_after_handoff"] is True


def test_rereview_preserves_x0_and_torque_semantic_boundary() -> None:
    boundary = build_review()["x0_and_torque_boundary"]

    assert boundary["condition7_x0_trace_population"] == 4
    assert boundary["condition7_x0_all_byte_identical"] is True
    assert boundary["condition7_x0_action_and_state_exact_zero"] is True
    assert boundary["condition7_x0_all_terminate_after_samples"] == 47
    assert boundary["default_off_x0_remains_byte_exact_winner_v10"] is True
    assert boundary["future_enabled_x0_is_graph_authoritative_and_may_be_nonzero"] is True
    assert boundary["runtime_must_not_force_enabled_x0_zero"] is True
    assert boundary["future_enabled_x0_requires_separate_behavior_gate"] is True
    assert boundary["inward_torque_representation_is_plant_xml_semantics"] is True
    assert boundary["inward_torque_requires_runtime_semantic_change"] is False


def test_rereview_authorizes_only_zero_ppo_cpu_mechanics() -> None:
    review = build_review()
    contract = review["authorized_zero_ppo_cpu_contract"]
    authority = review["authority"]

    assert contract["optimizer_steps"] == 0
    assert contract["formal_behavior_cells"] == 0
    assert contract["calibrator_ticks"] == 250
    assert authority["policy_freeze_zero_ppo_cpu_mechanics_contract"] is True
    assert authority["policy_run_zero_ppo_cpu_mechanics_contract"] is True
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


def test_rereview_cli_hash_binds_markdown(tmp_path: Path) -> None:
    output = tmp_path / "result.json"
    markdown = tmp_path / "RESULT.md"

    assert main(["--output", str(output), "--markdown", str(markdown)]) == 0
    payload = output.read_bytes()
    assert b"\r\n" not in payload
    assert json.loads(payload) == build_review()
    digest = hashlib.sha256(payload).hexdigest()
    text = markdown.read_text(encoding="utf-8")
    assert digest in text
    assert POLICY_ARTIFACT_SHA256 in text
    assert "does not authorize training" in text
