from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from open_duck_x5.configuration_support import ENVELOPE_SCHEMA_VERSION
from open_duck_x5.constants import JOINT_NAMES
from open_duck_x5.policy_envelope_closure import (
    EXPECTED_SELECTED_ONNX_SHA256,
    PENDING_SENTINEL,
    TEMPLATE_SHA256,
    PolicyEnvelopeClosureError,
    build_policy_envelope_closure,
    main,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _envelope() -> dict[str, object]:
    joint_bounds = {
        "delay_ticks": [0.0, 4.0],
        "gain_ratio": [0.5, 1.5],
        "time_constant_s": [0.0, 0.2],
        "tracking_p95_rad": [0.0, 0.05],
        "current_p95_a": [0.0, 2.0],
    }
    return {
        "schema_version": ENVELOPE_SCHEMA_VERSION,
        "policy": {
            "repository": "RobVanProd/open-duck-mini-rdkx5",
            "commit": "d" * 40,
            "onnx_sha256": EXPECTED_SELECTED_ONNX_SHA256,
            "contract_id": "winner-v2-115d",
        },
        "preregistration": {
            "commit": "e" * 40,
            "artifact_path": "outputs/analysis/configuration_domain.json",
            "artifact_sha256": "c" * 64,
        },
        "per_unit_physical_measurement_required": False,
        "policy_robustness_gate_passed": True,
        "configuration_domain": {
            "torso_mass_scale": [0.5, 1.5],
            "torso_com_x_m": [-0.05, 0.05],
            "torso_com_y_m": [-0.03, 0.03],
            "torso_com_z_m": [-0.03, 0.03],
            "torso_inertia_scale": {
                "xx": [0.5, 1.5],
                "yy": [0.5, 1.5],
                "zz": [0.5, 1.5],
            },
            "coupled_sample_count": 128,
            "held_out_sample_count": 32,
            "supported_optional_component_configurations": [
                "baseline",
                "optional_torso_parts_removed",
            ],
        },
        "profile_metric_bounds": {
            "joints": {name: dict(joint_bounds) for name in JOINT_NAMES},
            "body": {
                "pitch_rate_p95_rad_s": [0.0, 1.0],
                "roll_rate_p95_rad_s": [0.0, 1.0],
                "acceleration_norm_p95_m_s2": [8.0, 12.0],
            },
        },
    }


def _repo_copy(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    for relative_path in TEMPLATE_SHA256:
        destination = root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(relative_path, destination)
    return root


def _write_envelope(tmp_path: Path, value: dict[str, object]) -> Path:
    path = tmp_path / "envelope.json"
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    return path


def test_closure_computes_exact_future_hashes_without_writing(tmp_path: Path) -> None:
    root = _repo_copy(tmp_path)
    envelope = _write_envelope(tmp_path, _envelope())
    originals = {
        relative_path: (root / relative_path).read_bytes()
        for relative_path in TEMPLATE_SHA256
    }

    result = build_policy_envelope_closure(
        repo_root=root,
        envelope_path=envelope,
        expected_envelope_sha256=_sha256(envelope),
    )

    assert result["status"] == (
        "POLICY_ENVELOPE_STRUCTURE_ACCEPTED_PROVENANCE_REVIEW_REQUIRED"
    )
    assert result["runtime"]["templates_modified"] is False
    assert result["envelope"]["per_unit_physical_measurement_required"] is False
    assert all(value is False for value in result["authority"].values())
    for record in result["runtime"]["candidate_launchers"]:
        original = originals[record["path"]]
        expected_candidate = original.replace(
            PENDING_SENTINEL.encode(), _sha256(envelope).encode(), 1
        )
        assert record["candidate_sha256"] == hashlib.sha256(expected_candidate).hexdigest()
        assert (root / record["path"]).read_bytes() == original


def test_closure_rejects_independent_envelope_hash_mismatch(tmp_path: Path) -> None:
    root = _repo_copy(tmp_path)
    envelope = _write_envelope(tmp_path, _envelope())

    with pytest.raises(PolicyEnvelopeClosureError, match="independently supplied"):
        build_policy_envelope_closure(
            repo_root=root,
            envelope_path=envelope,
            expected_envelope_sha256="a" * 64,
        )


def test_closure_requires_asset_refreeze_for_changed_policy(tmp_path: Path) -> None:
    root = _repo_copy(tmp_path)
    value = _envelope()
    value["policy"]["onnx_sha256"] = "a" * 64
    envelope = _write_envelope(tmp_path, value)

    with pytest.raises(PolicyEnvelopeClosureError, match="asset freeze"):
        build_policy_envelope_closure(
            repo_root=root,
            envelope_path=envelope,
            expected_envelope_sha256=_sha256(envelope),
        )


def test_closure_rejects_changed_launcher_template(tmp_path: Path) -> None:
    root = _repo_copy(tmp_path)
    envelope = _write_envelope(tmp_path, _envelope())
    runner = root / "setup/run_winner_v2_cpu_preflight.sh"
    runner.write_text(runner.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    with pytest.raises(PolicyEnvelopeClosureError, match="template identity changed"):
        build_policy_envelope_closure(
            repo_root=root,
            envelope_path=envelope,
            expected_envelope_sha256=_sha256(envelope),
        )


def test_closure_rejects_invalid_envelope_before_computing_hashes(tmp_path: Path) -> None:
    root = _repo_copy(tmp_path)
    value = _envelope()
    value["per_unit_physical_measurement_required"] = True
    envelope = _write_envelope(tmp_path, value)

    with pytest.raises(PolicyEnvelopeClosureError, match="per-unit measurement"):
        build_policy_envelope_closure(
            repo_root=root,
            envelope_path=envelope,
            expected_envelope_sha256=_sha256(envelope),
        )


def test_cli_failure_leaves_no_output(tmp_path: Path) -> None:
    envelope = _write_envelope(tmp_path, _envelope())
    output = tmp_path / "closure.json"

    status = main(
        [
            "--envelope",
            str(envelope),
            "--expected-envelope-sha256",
            "a" * 64,
            "--output",
            str(output),
        ]
    )

    assert status == 2
    assert not output.exists()
