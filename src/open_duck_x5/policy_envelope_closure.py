"""Prepare a deterministic, no-write closure plan for a policy envelope."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .configuration_support import (
    ConfigurationSupportError,
    validate_supported_configuration_envelope_data,
)
from .policy_envelope_provenance import (
    EXPECTED_CONTRACT_ID,
    EXPECTED_POLICY_REPOSITORY,
    validate_policy_envelope_repository_provenance,
)

CLOSURE_SCHEMA_VERSION = "open_duck_x5.policy_envelope_closure.v1"
PENDING_SENTINEL = "PENDING_POLICY_ENVELOPE_SHA256"
EXPECTED_CONFIGURATION_SHA256 = (
    "131a7b8fce1107b14f4727562f44f9e17324caf7fc22512ad7115911f050991b"
)
EXPECTED_SELECTED_ONNX_SHA256 = (
    "99d3afce0dfac127816c6327665c35b3c403e005f25cd0a505dfcb37f01304de"
)
TEMPLATE_SHA256 = {
    "setup/run_automatic_configuration.sh": (
        "7b5607f5b1f26975945dba158bbdfa54706a8e7a9889fbec79690fa922e77245"
    ),
    "setup/run_winner_v2_cpu_preflight.sh": (
        "c70fa0ed182ae78b640ef731f175489046136aa51894db241ae455af06dbede7"
    ),
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class PolicyEnvelopeClosureError(RuntimeError):
    """The policy envelope cannot close the currently frozen runtime assets."""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_envelope(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PolicyEnvelopeClosureError(f"could not read policy envelope: {exc}") from exc
    if not isinstance(value, dict):
        raise PolicyEnvelopeClosureError("policy envelope must be a JSON object")
    try:
        validate_supported_configuration_envelope_data(value)
    except ConfigurationSupportError as exc:
        raise PolicyEnvelopeClosureError(f"policy envelope is invalid: {exc}") from exc
    return value


def _frozen_value(source: str, name: str, label: str) -> str:
    matches = re.findall(
        rf'^readonly {re.escape(name)}="([^"]+)"$', source, flags=re.MULTILINE
    )
    if len(matches) != 1:
        raise PolicyEnvelopeClosureError(
            f"{label} must contain exactly one readonly {name} assignment"
        )
    return matches[0]


def _candidate_script(
    *, path: Path, relative_path: str, envelope_sha256: str
) -> tuple[str, str]:
    try:
        original = path.read_bytes()
        source = original.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise PolicyEnvelopeClosureError(f"could not read {relative_path}: {exc}") from exc
    actual_sha256 = _sha256_bytes(original)
    expected_sha256 = TEMPLATE_SHA256[relative_path]
    if actual_sha256 != expected_sha256:
        raise PolicyEnvelopeClosureError(
            f"{relative_path} template identity changed: "
            f"{actual_sha256} != {expected_sha256}"
        )
    assignment = f'readonly expected_policy_envelope_sha256="{PENDING_SENTINEL}"'
    replacement = f'readonly expected_policy_envelope_sha256="{envelope_sha256}"'
    if source.count(assignment) != 1:
        raise PolicyEnvelopeClosureError(
            f"{relative_path} must contain exactly one pending-envelope assignment"
        )
    if source.count(PENDING_SENTINEL) != 1:
        raise PolicyEnvelopeClosureError(
            f"{relative_path} contains an unexpected pending-envelope sentinel population"
        )
    candidate = source.replace(assignment, replacement, 1).encode("utf-8")
    if PENDING_SENTINEL.encode() in candidate:
        raise PolicyEnvelopeClosureError(
            f"{relative_path} candidate still contains the pending sentinel"
        )
    return actual_sha256, _sha256_bytes(candidate)


def build_policy_envelope_closure(
    *,
    repo_root: Path,
    policy_repo_root: Path,
    envelope_path: Path,
    envelope_repository_path: str,
    envelope_commit: str,
    expected_envelope_sha256: str,
) -> dict[str, Any]:
    """Validate one handoff and compute exact future launcher hashes without writing."""
    root = repo_root.resolve()
    envelope_file = envelope_path.resolve()
    if not _SHA256_RE.fullmatch(expected_envelope_sha256):
        raise PolicyEnvelopeClosureError(
            "expected policy-envelope identity must be a lowercase SHA-256"
        )
    actual_envelope_sha256 = _sha256(envelope_file)
    if actual_envelope_sha256 != expected_envelope_sha256:
        raise PolicyEnvelopeClosureError(
            "policy-envelope identity differs from the independently supplied SHA-256"
        )
    envelope = _load_envelope(envelope_file)
    provenance = validate_policy_envelope_repository_provenance(
        policy_repo_root=policy_repo_root,
        envelope_path=envelope_file,
        envelope_repository_path=envelope_repository_path,
        envelope_commit=envelope_commit,
        expected_envelope_sha256=expected_envelope_sha256,
    )
    policy = envelope["policy"]
    if policy["repository"] != EXPECTED_POLICY_REPOSITORY:
        raise PolicyEnvelopeClosureError("policy repository differs from the handoff contract")
    if policy["contract_id"] != EXPECTED_CONTRACT_ID:
        raise PolicyEnvelopeClosureError("policy contract_id differs from winner-v2-115d")
    if policy["onnx_sha256"] != EXPECTED_SELECTED_ONNX_SHA256:
        raise PolicyEnvelopeClosureError(
            "policy ONNX differs from the currently frozen runtime asset; "
            "repeat the two-repository asset freeze before closing launchers"
        )

    scripts: dict[str, str] = {}
    for relative_path in TEMPLATE_SHA256:
        path = root / relative_path
        try:
            scripts[relative_path] = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise PolicyEnvelopeClosureError(f"could not read {relative_path}: {exc}") from exc
        config_sha256 = _frozen_value(
            scripts[relative_path], "expected_config_sha256", relative_path
        )
        if config_sha256 != EXPECTED_CONFIGURATION_SHA256:
            raise PolicyEnvelopeClosureError(
                f"{relative_path} configuration identity differs from the frozen contract"
            )
        sentinel = _frozen_value(
            scripts[relative_path], "expected_policy_envelope_sha256", relative_path
        )
        if sentinel != PENDING_SENTINEL:
            raise PolicyEnvelopeClosureError(
                f"{relative_path} is not the reviewed pending-envelope template"
            )

    selected_onnx = _frozen_value(
        scripts["setup/run_winner_v2_cpu_preflight.sh"],
        "expected_selected_onnx_sha256",
        "setup/run_winner_v2_cpu_preflight.sh",
    )
    if selected_onnx != policy["onnx_sha256"]:
        raise PolicyEnvelopeClosureError(
            "preflight selected ONNX differs from the policy envelope"
        )

    finalized: list[dict[str, Any]] = []
    for relative_path in TEMPLATE_SHA256:
        template_sha256, candidate_sha256 = _candidate_script(
            path=root / relative_path,
            relative_path=relative_path,
            envelope_sha256=actual_envelope_sha256,
        )
        finalized.append(
            {
                "path": relative_path,
                "template_sha256": template_sha256,
                "candidate_sha256": candidate_sha256,
                "replacement_count": 1,
                "written": False,
            }
        )

    return {
        "schema_version": CLOSURE_SCHEMA_VERSION,
        "status": "POLICY_ENVELOPE_STRUCTURE_ACCEPTED_PROVENANCE_REVIEW_REQUIRED",
        "envelope": {
            "path": str(envelope_file),
            "sha256": actual_envelope_sha256,
            "policy": policy,
            "preregistration": envelope["preregistration"],
            "per_unit_physical_measurement_required": False,
            "policy_robustness_gate_passed": True,
        },
        "runtime": {
            "configuration_sha256": EXPECTED_CONFIGURATION_SHA256,
            "selected_onnx_sha256": EXPECTED_SELECTED_ONNX_SHA256,
            "candidate_launchers": finalized,
            "templates_modified": False,
        },
        "repository_provenance": provenance,
        "remaining_review": {
            "apply_only_the_two_recorded_sentinel_replacements": True,
            "refreeze_preflight_reviewer_runner_identity": True,
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate a policy envelope and compute no-write launcher closure hashes"
    )
    parser.add_argument("--envelope", type=Path, required=True)
    parser.add_argument("--policy-repository", type=Path, required=True)
    parser.add_argument("--envelope-repository-path", required=True)
    parser.add_argument("--envelope-commit", required=True)
    parser.add_argument("--expected-envelope-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = Path(__file__).resolve().parents[2]
    output = args.output.resolve()
    protected = {args.envelope.resolve()} | {
        (repo_root / relative_path).resolve() for relative_path in TEMPLATE_SHA256
    }
    if output in protected:
        print("result=FAIL reason=closure output may not overwrite an input")
        return 2
    output.unlink(missing_ok=True)
    try:
        result = build_policy_envelope_closure(
            repo_root=repo_root,
            policy_repo_root=args.policy_repository,
            envelope_path=args.envelope,
            envelope_repository_path=args.envelope_repository_path,
            envelope_commit=args.envelope_commit,
            expected_envelope_sha256=args.expected_envelope_sha256,
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except (OSError, PolicyEnvelopeClosureError) as exc:
        output.unlink(missing_ok=True)
        print(f"result=FAIL reason={exc}")
        return 2
    print(f"result={result['status']} output={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
