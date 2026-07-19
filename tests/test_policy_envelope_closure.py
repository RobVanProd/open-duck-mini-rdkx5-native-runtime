from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from collections.abc import Callable
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
from open_duck_x5.policy_envelope_provenance import (
    CLEARANCE_SCHEMA_VERSION,
    PolicyEnvelopeProvenanceError,
    validate_policy_envelope_repository_provenance,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(repo: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=repo,
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    ).stdout.strip()


def _commit_all(repo: Path, message: str) -> str:
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _envelope(
    *,
    policy_commit: str,
    preregistration_commit: str,
    preregistration_sha256: str,
    clearance_commit: str,
    clearance_sha256: str,
) -> dict[str, object]:
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
            "commit": policy_commit,
            "onnx_sha256": EXPECTED_SELECTED_ONNX_SHA256,
            "contract_id": "winner-v2-115d",
        },
        "preregistration": {
            "commit": preregistration_commit,
            "artifact_path": "outputs/analysis/configuration_domain.json",
            "artifact_sha256": preregistration_sha256,
        },
        "clearance": {
            "robot_clearance": True,
            "commit": clearance_commit,
            "artifact_path": "outputs/analysis/policy_robot_clearance.json",
            "artifact_sha256": clearance_sha256,
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


def _policy_repo(
    tmp_path: Path,
    mutate_envelope: Callable[[dict[str, object]], None] | None = None,
) -> tuple[Path, Path, str, str]:
    repo = tmp_path / "policy"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(
        repo,
        "remote",
        "add",
        "origin",
        "https://github.com/RobVanProd/open-duck-mini-rdkx5.git",
    )
    preregistration = repo / "outputs/analysis/configuration_domain.json"
    preregistration.parent.mkdir(parents=True)
    preregistration.write_bytes(b'{"frozen":true}\n')
    preregistration_commit = _commit_all(repo, "preregister")
    (repo / "policy-source.txt").write_text("selected\n", encoding="utf-8")
    policy_commit = _commit_all(repo, "select policy")
    clearance = repo / "outputs/analysis/policy_robot_clearance.json"
    clearance.write_bytes(
        (
            json.dumps(
                {
                    "schema_version": CLEARANCE_SCHEMA_VERSION,
                    "robot_clearance": True,
                    "policy": {
                        "onnx_sha256": EXPECTED_SELECTED_ONNX_SHA256,
                        "contract_id": "winner-v2-115d",
                    },
                    "supported_configuration_gate_passed": True,
                },
                sort_keys=True,
            )
            + "\n"
        ).encode()
    )
    clearance_commit = _commit_all(repo, "clear policy for robot")
    envelope_value = _envelope(
        policy_commit=policy_commit,
        preregistration_commit=preregistration_commit,
        preregistration_sha256=_sha256(preregistration),
        clearance_commit=clearance_commit,
        clearance_sha256=_sha256(clearance),
    )
    if mutate_envelope is not None:
        mutate_envelope(envelope_value)
    repository_path = "outputs/analysis/supported_configuration_envelope.json"
    envelope = repo / repository_path
    envelope.write_bytes((json.dumps(envelope_value, sort_keys=True) + "\n").encode())
    envelope_commit = _commit_all(repo, "publish envelope")
    return repo, envelope, repository_path, envelope_commit


def _runtime_repo_copy(tmp_path: Path) -> Path:
    root = tmp_path / "runtime"
    for relative_path in TEMPLATE_SHA256:
        destination = root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(relative_path, destination)
    return root


def _build(root: Path, policy: tuple[Path, Path, str, str]) -> dict[str, object]:
    repo, envelope, repository_path, envelope_commit = policy
    return build_policy_envelope_closure(
        repo_root=root,
        policy_repo_root=repo,
        envelope_path=envelope,
        envelope_repository_path=repository_path,
        envelope_commit=envelope_commit,
        expected_envelope_sha256=_sha256(envelope),
    )


def test_closure_computes_exact_future_hashes_without_writing(tmp_path: Path) -> None:
    root = _runtime_repo_copy(tmp_path)
    policy = _policy_repo(tmp_path)
    envelope = policy[1]
    originals = {
        relative_path: (root / relative_path).read_bytes()
        for relative_path in TEMPLATE_SHA256
    }

    result = _build(root, policy)

    assert result["status"] == (
        "POLICY_ENVELOPE_CLEARANCE_ACCEPTED_PROVENANCE_REVIEW_REQUIRED"
    )
    assert result["repository_provenance"]["status"] == (
        "PASS_POLICY_ENVELOPE_REPOSITORY_PROVENANCE"
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


def test_provenance_distinguishes_policy_and_envelope_commits(tmp_path: Path) -> None:
    repo, envelope, repository_path, envelope_commit = _policy_repo(tmp_path)

    result = validate_policy_envelope_repository_provenance(
        policy_repo_root=repo,
        envelope_path=envelope,
        envelope_repository_path=repository_path,
        envelope_commit=envelope_commit,
        expected_envelope_sha256=_sha256(envelope),
    )

    assert result["commits"]["selected_policy"] != envelope_commit
    assert result["commits"]["clearance_decision"] != envelope_commit
    assert result["commits"]["envelope_artifact"] == envelope_commit
    assert result["commits"]["preregistration_is_ancestor_of_policy"] is True
    assert result["commits"]["policy_is_ancestor_of_clearance"] is True
    assert result["commits"]["clearance_is_ancestor_of_envelope"] is True


def test_provenance_rejects_uncommitted_envelope_bytes(tmp_path: Path) -> None:
    repo, envelope, repository_path, envelope_commit = _policy_repo(tmp_path)
    envelope.write_text(envelope.read_text(encoding="utf-8") + " ", encoding="utf-8")

    with pytest.raises(PolicyEnvelopeProvenanceError, match="artifact commit"):
        validate_policy_envelope_repository_provenance(
            policy_repo_root=repo,
            envelope_path=envelope,
            envelope_repository_path=repository_path,
            envelope_commit=envelope_commit,
            expected_envelope_sha256=_sha256(envelope),
        )


def test_provenance_rejects_wrong_origin(tmp_path: Path) -> None:
    repo, envelope, repository_path, envelope_commit = _policy_repo(tmp_path)
    _git(repo, "remote", "set-url", "origin", "https://example.com/wrong.git")

    with pytest.raises(PolicyEnvelopeProvenanceError, match="origin"):
        validate_policy_envelope_repository_provenance(
            policy_repo_root=repo,
            envelope_path=envelope,
            envelope_repository_path=repository_path,
            envelope_commit=envelope_commit,
            expected_envelope_sha256=_sha256(envelope),
        )


def test_provenance_rejects_wrong_preregistration_bytes(tmp_path: Path) -> None:
    def mutate(value: dict[str, object]) -> None:
        value["preregistration"]["artifact_sha256"] = "a" * 64

    repo, envelope, repository_path, envelope_commit = _policy_repo(tmp_path, mutate)

    with pytest.raises(PolicyEnvelopeProvenanceError, match="preregistration artifact"):
        validate_policy_envelope_repository_provenance(
            policy_repo_root=repo,
            envelope_path=envelope,
            envelope_repository_path=repository_path,
            envelope_commit=envelope_commit,
            expected_envelope_sha256=_sha256(envelope),
        )


def test_provenance_rejects_wrong_clearance_bytes(tmp_path: Path) -> None:
    def mutate(value: dict[str, object]) -> None:
        value["clearance"]["artifact_sha256"] = "a" * 64

    repo, envelope, repository_path, envelope_commit = _policy_repo(tmp_path, mutate)

    with pytest.raises(PolicyEnvelopeProvenanceError, match="clearance decision artifact"):
        validate_policy_envelope_repository_provenance(
            policy_repo_root=repo,
            envelope_path=envelope,
            envelope_repository_path=repository_path,
            envelope_commit=envelope_commit,
            expected_envelope_sha256=_sha256(envelope),
        )


def test_provenance_rejects_policy_outside_preregistration_history(
    tmp_path: Path,
) -> None:
    repo, envelope, repository_path, _envelope_commit = _policy_repo(tmp_path)
    branch = _git(repo, "branch", "--show-current")
    _git(repo, "checkout", "--orphan", "unrelated-policy")
    _git(repo, "rm", "-rf", ".")
    (repo / "unrelated.txt").write_bytes(b"unrelated\n")
    unrelated_commit = _commit_all(repo, "unrelated policy")
    _git(repo, "checkout", branch)
    value = json.loads(envelope.read_text(encoding="utf-8"))
    value["policy"]["commit"] = unrelated_commit
    envelope.write_bytes((json.dumps(value, sort_keys=True) + "\n").encode())
    envelope_commit = _commit_all(repo, "publish unrelated envelope")

    with pytest.raises(PolicyEnvelopeProvenanceError, match="ancestry"):
        validate_policy_envelope_repository_provenance(
            policy_repo_root=repo,
            envelope_path=envelope,
            envelope_repository_path=repository_path,
            envelope_commit=envelope_commit,
            expected_envelope_sha256=_sha256(envelope),
        )


def test_closure_rejects_independent_envelope_hash_mismatch(tmp_path: Path) -> None:
    root = _runtime_repo_copy(tmp_path)
    repo, envelope, repository_path, envelope_commit = _policy_repo(tmp_path)

    with pytest.raises(PolicyEnvelopeClosureError, match="independently supplied"):
        build_policy_envelope_closure(
            repo_root=root,
            policy_repo_root=repo,
            envelope_path=envelope,
            envelope_repository_path=repository_path,
            envelope_commit=envelope_commit,
            expected_envelope_sha256="a" * 64,
        )


def test_closure_requires_asset_refreeze_for_changed_policy(tmp_path: Path) -> None:
    def mutate(value: dict[str, object]) -> None:
        value["policy"]["onnx_sha256"] = "a" * 64
        clearance_path = tmp_path / "policy/outputs/analysis/policy_robot_clearance.json"
        clearance = json.loads(clearance_path.read_text(encoding="utf-8"))
        clearance["policy"]["onnx_sha256"] = "a" * 64
        clearance_path.write_bytes((json.dumps(clearance, sort_keys=True) + "\n").encode())
        value["clearance"]["artifact_sha256"] = _sha256(clearance_path)
        value["clearance"]["commit"] = _commit_all(tmp_path / "policy", "change policy")

    root = _runtime_repo_copy(tmp_path)
    policy = _policy_repo(tmp_path, mutate)

    with pytest.raises(PolicyEnvelopeClosureError, match="asset freeze"):
        _build(root, policy)


def test_closure_rejects_changed_launcher_template(tmp_path: Path) -> None:
    root = _runtime_repo_copy(tmp_path)
    policy = _policy_repo(tmp_path)
    runner = root / "setup/run_winner_v2_cpu_preflight.sh"
    runner.write_text(runner.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    with pytest.raises(PolicyEnvelopeClosureError, match="template identity changed"):
        _build(root, policy)


def test_closure_rejects_invalid_envelope_before_computing_hashes(tmp_path: Path) -> None:
    def mutate(value: dict[str, object]) -> None:
        value["per_unit_physical_measurement_required"] = True

    root = _runtime_repo_copy(tmp_path)
    policy = _policy_repo(tmp_path, mutate)

    with pytest.raises(PolicyEnvelopeClosureError, match="per-unit measurement"):
        _build(root, policy)


def test_closure_rejects_policy_without_robot_clearance(tmp_path: Path) -> None:
    def mutate(value: dict[str, object]) -> None:
        value["clearance"]["robot_clearance"] = False

    root = _runtime_repo_copy(tmp_path)
    policy = _policy_repo(tmp_path, mutate)

    with pytest.raises(PolicyEnvelopeClosureError, match="robot clearance"):
        _build(root, policy)


def test_cli_failure_leaves_no_output(tmp_path: Path) -> None:
    repo, envelope, repository_path, envelope_commit = _policy_repo(tmp_path)
    output = tmp_path / "closure.json"

    status = main(
        [
            "--envelope",
            str(envelope),
            "--policy-repository",
            str(repo),
            "--envelope-repository-path",
            repository_path,
            "--envelope-commit",
            envelope_commit,
            "--expected-envelope-sha256",
            "a" * 64,
            "--output",
            str(output),
        ]
    )

    assert status == 2
    assert not output.exists()
