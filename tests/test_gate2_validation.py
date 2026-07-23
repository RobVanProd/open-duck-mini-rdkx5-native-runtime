from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from open_duck_x5.gate2_validation import (
    Gate2ValidationError,
    main,
    validate_gate2_summary,
)

CONFIG_SHA = "131a7b8fce1107b14f4727562f44f9e17324caf7fc22512ad7115911f050991b"


def _passing_summary(*, moving: bool) -> dict:
    path = (
        Path(__file__).parents[1]
        / "artifacts"
        / "gates"
        / "phase_7_hardware"
        / "gate_2_all14_home"
        / "cpu_governor_ab"
        / "summary.json"
    )
    summary = copy.deepcopy(json.loads(path.read_text(encoding="utf-8")))
    environment = summary["environment"]
    gates = summary["gates"]
    environment["home_seconds"] = 5.0
    environment["config_sha256"] = CONFIG_SHA
    environment["config_path"] = "/home/sunrise/duck_config.json"
    environment["moving_gate_authorized"] = moving
    environment["torque_enabled"] = moving
    gates["moving_gate_scope"] = moving
    gates["gate2_home_hold_candidate"] = moving
    if moving:
        summary["tracking_absolute_error_rad"]["samples"] = 10_000
    return summary


@pytest.mark.parametrize("moving", [False, True])
def test_gate2_validation_accepts_only_matching_stage(moving: bool) -> None:
    validate_gate2_summary(
        _passing_summary(moving=moving),
        moving=moving,
        expected_config_sha256=CONFIG_SHA,
    )


def test_gate2_validation_rejects_direct_bus_max_even_if_gate_boolean_is_true() -> None:
    summary = _passing_summary(moving=False)
    summary["bus_total_ms"]["max"] = 5.0
    with pytest.raises(Gate2ValidationError, match="bus max"):
        validate_gate2_summary(
            summary, moving=False, expected_config_sha256=CONFIG_SHA
        )


def test_gate2_validation_rejects_motion_candidate_in_preflight() -> None:
    summary = _passing_summary(moving=False)
    summary["gates"]["gate2_home_hold_candidate"] = True
    with pytest.raises(Gate2ValidationError, match="gate candidate"):
        validate_gate2_summary(
            summary, moving=False, expected_config_sha256=CONFIG_SHA
        )


def test_gate2_validation_rejects_missing_home_provenance() -> None:
    summary = _passing_summary(moving=True)
    del summary["environment"]["home_seconds"]
    with pytest.raises(Gate2ValidationError, match="structure is incomplete"):
        validate_gate2_summary(
            summary, moving=True, expected_config_sha256=CONFIG_SHA
        )


def test_gate2_validation_cli_fails_closed(tmp_path: Path) -> None:
    summary_path = tmp_path / "summary.json"
    summary = _passing_summary(moving=True)
    summary["environment"]["torque_off_status"] = "io"
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    assert (
        main(
            [
                "--summary",
                str(summary_path),
                "--stage",
                "home_hold",
                "--expected-config-sha256",
                CONFIG_SHA,
            ]
        )
        == 2
    )
