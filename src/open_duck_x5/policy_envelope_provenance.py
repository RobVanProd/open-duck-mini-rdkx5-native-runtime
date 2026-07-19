"""Verify a policy envelope and preregistration directly from Git objects."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

from .configuration_support import (
    ConfigurationSupportError,
    validate_supported_configuration_envelope_data,
)

PROVENANCE_SCHEMA_VERSION = "open_duck_x5.policy_envelope_provenance.v1"
EXPECTED_POLICY_REPOSITORY = "RobVanProd/open-duck-mini-rdkx5"
EXPECTED_CONTRACT_ID = "winner-v2-115d"
EXPECTED_ORIGIN_URLS = {
    "https://github.com/RobVanProd/open-duck-mini-rdkx5.git",
    "git@github.com:RobVanProd/open-duck-mini-rdkx5.git",
    "ssh://git@github.com/RobVanProd/open-duck-mini-rdkx5.git",
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


class PolicyEnvelopeProvenanceError(RuntimeError):
    """Policy envelope Git provenance is incomplete or inconsistent."""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(repo: Path, *arguments: str) -> bytes:
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=repo,
            check=False,
            capture_output=True,
        )
    except OSError as exc:
        raise PolicyEnvelopeProvenanceError(f"could not execute git: {exc}") from exc
    if completed.returncode == 0:
        return completed.stdout
    detail = completed.stderr.decode("utf-8", errors="replace").strip()
    raise PolicyEnvelopeProvenanceError(
        f"git {' '.join(arguments)} failed with {completed.returncode}: {detail}"
    )


def _commit(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _COMMIT_RE.fullmatch(value):
        raise PolicyEnvelopeProvenanceError(f"{label} must be a full Git commit identity")
    return value


def _repository_path(value: str, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise PolicyEnvelopeProvenanceError(
            f"{label} must be a nonempty repository-relative POSIX path"
        )
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise PolicyEnvelopeProvenanceError(
            f"{label} must be a normalized repository-relative POSIX path"
        )
    return value


def _load_envelope(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PolicyEnvelopeProvenanceError(f"could not read policy envelope: {exc}") from exc
    if not isinstance(value, dict):
        raise PolicyEnvelopeProvenanceError("policy envelope must be a JSON object")
    try:
        validate_supported_configuration_envelope_data(value)
    except ConfigurationSupportError as exc:
        raise PolicyEnvelopeProvenanceError(f"policy envelope is invalid: {exc}") from exc
    return value


def _require_commit(repo: Path, commit: str, label: str) -> None:
    object_type = _git(repo, "cat-file", "-t", commit).decode().strip()
    if object_type != "commit":
        raise PolicyEnvelopeProvenanceError(f"{label} is not a Git commit")


def _require_ancestor(repo: Path, ancestor: str, descendant: str, label: str) -> None:
    try:
        completed = subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor, descendant],
            cwd=repo,
            check=False,
            capture_output=True,
        )
    except OSError as exc:
        raise PolicyEnvelopeProvenanceError(f"could not execute git: {exc}") from exc
    if completed.returncode == 0:
        return
    if completed.returncode == 1:
        raise PolicyEnvelopeProvenanceError(f"{label} ancestry is not satisfied")
    detail = completed.stderr.decode("utf-8", errors="replace").strip()
    raise PolicyEnvelopeProvenanceError(
        f"could not verify {label} ancestry: git returned {completed.returncode}: {detail}"
    )


def validate_policy_envelope_repository_provenance(
    *,
    policy_repo_root: Path,
    envelope_path: Path,
    envelope_repository_path: str,
    envelope_commit: str,
    expected_envelope_sha256: str,
) -> dict[str, Any]:
    """Re-read the exact envelope and preregistration bytes from Git commits."""
    repo = policy_repo_root.resolve()
    envelope_file = envelope_path.resolve()
    repository_envelope_path = _repository_path(
        envelope_repository_path, "envelope repository path"
    )
    artifact_commit = _commit(envelope_commit, "envelope artifact commit")
    if not _SHA256_RE.fullmatch(expected_envelope_sha256):
        raise PolicyEnvelopeProvenanceError(
            "expected policy-envelope identity must be a lowercase SHA-256"
        )
    if _git(repo, "rev-parse", "--is-inside-work-tree").decode().strip() != "true":
        raise PolicyEnvelopeProvenanceError("policy repository path is not a Git worktree")
    origin_url = _git(repo, "remote", "get-url", "origin").decode().strip()
    if origin_url not in EXPECTED_ORIGIN_URLS:
        raise PolicyEnvelopeProvenanceError(
            "policy repository origin is not the expected GitHub repo"
        )

    actual_envelope_sha256 = _sha256(envelope_file)
    if actual_envelope_sha256 != expected_envelope_sha256:
        raise PolicyEnvelopeProvenanceError(
            "local policy-envelope identity differs from the independently supplied SHA-256"
        )
    envelope = _load_envelope(envelope_file)
    policy = envelope["policy"]
    preregistration = envelope["preregistration"]
    if policy["repository"] != EXPECTED_POLICY_REPOSITORY:
        raise PolicyEnvelopeProvenanceError("policy repository differs from the handoff contract")
    if policy["contract_id"] != EXPECTED_CONTRACT_ID:
        raise PolicyEnvelopeProvenanceError("policy contract_id differs from winner-v2-115d")

    policy_commit = _commit(policy["commit"], "selected policy commit")
    preregistration_commit = _commit(
        preregistration["commit"], "preregistration commit"
    )
    preregistration_path = _repository_path(
        preregistration["artifact_path"], "preregistration artifact path"
    )
    for commit, label in (
        (preregistration_commit, "preregistration commit"),
        (policy_commit, "selected policy commit"),
        (artifact_commit, "envelope artifact commit"),
    ):
        _require_commit(repo, commit, label)
    _require_ancestor(
        repo,
        preregistration_commit,
        policy_commit,
        "preregistration -> selected policy",
    )
    _require_ancestor(
        repo,
        policy_commit,
        artifact_commit,
        "selected policy -> envelope artifact",
    )

    committed_envelope = _git(
        repo, "show", f"{artifact_commit}:{repository_envelope_path}"
    )
    if _sha256_bytes(committed_envelope) != expected_envelope_sha256:
        raise PolicyEnvelopeProvenanceError(
            "envelope bytes at the artifact commit differ from the supplied envelope"
        )
    committed_preregistration = _git(
        repo, "show", f"{preregistration_commit}:{preregistration_path}"
    )
    if _sha256_bytes(committed_preregistration) != preregistration["artifact_sha256"]:
        raise PolicyEnvelopeProvenanceError(
            "preregistration artifact bytes differ from the envelope identity"
        )

    return {
        "schema_version": PROVENANCE_SCHEMA_VERSION,
        "status": "PASS_POLICY_ENVELOPE_REPOSITORY_PROVENANCE",
        "repository": {
            "slug": EXPECTED_POLICY_REPOSITORY,
            "origin_url": origin_url,
            "worktree": str(repo),
        },
        "commits": {
            "preregistration": preregistration_commit,
            "selected_policy": policy_commit,
            "envelope_artifact": artifact_commit,
            "preregistration_is_ancestor_of_policy": True,
            "policy_is_ancestor_of_envelope": True,
        },
        "envelope": {
            "local_path": str(envelope_file),
            "repository_path": repository_envelope_path,
            "sha256": actual_envelope_sha256,
        },
        "preregistration": {
            "repository_path": preregistration_path,
            "sha256": preregistration["artifact_sha256"],
        },
        "policy": {
            "onnx_sha256": policy["onnx_sha256"],
            "contract_id": policy["contract_id"],
        },
        "authority": {
            "robot_clearance": False,
            "serial": False,
            "torque": False,
            "motion": False,
            "gate5": False,
            "runtime_deployment": False,
        },
    }
