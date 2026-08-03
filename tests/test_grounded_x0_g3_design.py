from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
DESIGN = (
    ROOT
    / "artifacts/gates/grounded_validation"
    / "GROUNDED_X0_G3_AUTHORITY_AND_SAFETY_DESIGN_20260803.json"
)
G2_REVIEW = (
    ROOT
    / "artifacts/gates/grounded_validation"
    / "SUSPENDED_CONTROLLER_B_CUTOFF_G2_REPLACEMENT_PASS_REVIEWED_20260803.json"
)
X0_REVIEW = (
    ROOT
    / "artifacts/gates/phase_7_hardware/gate_5_policy"
    / "T247_X0_READINESS_CUED_PASS_REVIEWED_20260802.json"
)
GATE3_REVIEW = (
    ROOT
    / "artifacts/gates/phase_7_hardware/gate_3_sensors/matrix_20260719"
    / "human-review.json"
)
AGENT_INSTRUCTIONS = ROOT / "AGENTS.md"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _angle_deg(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    cosine = max(-1.0, min(1.0, dot / (left_norm * right_norm)))
    return math.degrees(math.acos(cosine))


def test_g3_design_is_earned_but_blocked_on_explicit_authority() -> None:
    value = json.loads(DESIGN.read_text(encoding="utf-8"))

    assert value["status"] == (
        "DESIGN_FROZEN_BLOCKED_ON_EXPLICIT_AUTHORITY_AMENDMENT"
    )
    assert value["earned_by"]["g2_review_sha256"] == _sha256(G2_REVIEW)
    assert value["evidence_inputs"]["suspended_x0_review_sha256"] == _sha256(
        X0_REVIEW
    )
    assert value["evidence_inputs"]["gate3_human_review_sha256"] == _sha256(
        GATE3_REVIEW
    )
    decision = value["decision"]
    assert decision["design_frozen"] is True
    assert decision["runtime_edit_authorized"] is False
    assert decision["launcher_edit_authorized"] is False
    assert decision["robot_access_authorized"] is False
    assert decision["grounded_motion_authorized"] is False
    assert decision["g3_ready_to_run"] is False


def test_g3_design_records_that_x0_has_a_moving_calibration_stage() -> None:
    value = json.loads(DESIGN.read_text(encoding="utf-8"))
    audit = value["read_only_suspended_x0_trace_audit"]

    assert audit["active_rows"] == 850
    assert audit["calibration_rows"] == 250
    assert audit["locomotion_rows"] == 600
    assert audit["max_abs_action"] == 0.5
    assert audit["max_implied_target_velocity_rad_s"] == pytest.approx(
        1.4999955892562866
    )
    assert audit["max_sent_target_change_from_first_active_tick_rad"] > 0.1
    assert audit["locomotion_target_static_after_calibration"] is True
    assert audit["suspended_contact_pattern_counts"] == {
        "none": 850,
        "left_only": 0,
        "right_only": 0,
        "both": 0,
    }


def test_g3_tilt_thresholds_recompute_from_reviewed_gate3_vectors() -> None:
    value = json.loads(DESIGN.read_text(encoding="utf-8"))
    gate3 = json.loads(GATE3_REVIEW.read_text(encoding="utf-8"))
    derivation = value["tilt_threshold_derivation"]
    upright = gate3["labels"]["upright"]["acceleration_mean_m_s2"]
    angles = {
        label: _angle_deg(
            upright,
            gate3["labels"][label]["acceleration_mean_m_s2"],
        )
        for label in ("nose_forward", "nose_back", "left_tilt", "right_tilt")
    }

    assert angles == pytest.approx(derivation["labeled_angles_deg"], abs=1e-12)
    minimum = min(angles.values())
    guard = value["required_default_off_runtime_mechanisms"][
        "automatic_stability_guard"
    ]
    assert guard["single_tick_tilt_cutoff_deg"] == pytest.approx(minimum)
    assert guard["sustained_tilt_cutoff_deg"] == pytest.approx(minimum / 2.0)
    assert guard["sustained_tilt_ticks"] == 3
    assert derivation["searched_or_tuned"] is False


def test_g3_design_requires_no_measurement_equipment_and_no_launcher() -> None:
    value = json.loads(DESIGN.read_text(encoding="utf-8"))
    setup = value["physical_setup_proposal"]

    assert setup["measurements_required"] == []
    assert setup["explicitly_not_required"] == [
        "scale",
        "caliper",
        "millimeter placement",
        "manual center-of-mass entry",
    ]
    assert value["current_authority_audit"]["grounded_launcher_exists"] is False
    assert not list((ROOT / "setup").glob("*grounded*x0*"))


def test_current_repository_authority_still_excludes_grounded_replay() -> None:
    text = AGENT_INSTRUCTIONS.read_text(encoding="utf-8")
    value = json.loads(DESIGN.read_text(encoding="utf-8"))

    assert "Grounded replay and grounded walking are outside" in text
    assert value["authority_amendment"]["currently_granted"] is False
    assert value["authority_amendment"][
        "required_before_runtime_or_launcher_implementation"
    ] is True
    assert value["required_default_off_runtime_mechanisms"][
        "honest_authority_mode"
    ]["default_enabled"] is False
