#!/usr/bin/env python3
"""Verify the two-repository winner-v2 final offline asset freeze."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

EXPECTED_SCHEMA = "open_duck_x5.winner_v2_final_asset_freeze_closure.v1"
EXPECTED_STATUS = "PASS_FINAL_OFFLINE_ASSET_FREEZE"
EXPECTED_LOCK_SHA256 = (
    "48fd6d81aa9f621d0167536829ed7df62fe1d3b92b161607315aec9e8f64ef31"
)
EXPECTED_POLICY_REVIEW_SHA256 = (
    "53351707ab1477541a4193b291bdc5ec8073ad500c171f7778fc36bf363aadea"
)
EXPECTED_POLICY_REVIEW_COMMIT = "4521cd8fdcf5603dfb1405417ce38cd2f031fd84"
EXPECTED_RUNTIME_COMMIT = "290fe4726a0310c1a368767ce900340a52eba412"
EXPECTED_POLICY_ACCEPTANCE_COMMIT = "4c99b5e3be203af419536382f11f3cce98283ba2"
EXPECTED_POLICY_ACCEPTANCE_SHA256 = (
    "5380897c21d3e438dbc4216ba049bc14fb6beb227a13407943d4d092519b7ddc"
)


class AssetFreezeError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssetFreezeError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def checked_path(root: Path, relative: str, *, label: str) -> Path:
    path = (root / relative).resolve()
    require(path.is_relative_to(root), f"{label} path escapes runtime root")
    require(path.is_file(), f"{label} file is missing: {relative}")
    return path


def verify_asset_freeze(closure_path: Path, *, runtime_root: Path) -> dict[str, object]:
    runtime_root = runtime_root.resolve()
    closure = json.loads(closure_path.read_text(encoding="utf-8"))
    require(closure["schema_version"] == EXPECTED_SCHEMA, "closure schema changed")
    require(closure["status"] == EXPECTED_STATUS, "closure status changed")
    require(
        closure["reviewed_runtime_commit"] == EXPECTED_RUNTIME_COMMIT,
        "reviewed runtime commit changed",
    )

    authority = closure["authority"]
    require(authority["cpu_only"] is True, "closure is not CPU-only")
    for key in (
        "gate5",
        "rdkx5_access",
        "robot_clearance",
        "robot_or_motor_access",
        "runtime_deployment",
    ):
        require(authority[key] is False, f"closure broadened authority: {key}")

    lock_meta = closure["asset_lock"]
    require(lock_meta["sha256"] == EXPECTED_LOCK_SHA256, "asset-lock identity changed")
    lock_path = checked_path(runtime_root, lock_meta["path"], label="asset lock")
    require(sha256_file(lock_path) == EXPECTED_LOCK_SHA256, "asset-lock bytes changed")
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    require(lock["authority"] == authority, "closure and lock authority differ")
    require(
        lock["blockers"] == closure["remaining_blockers"],
        "closure and lock blocker sets differ",
    )

    verification_path = checked_path(
        runtime_root,
        lock_meta["runtime_verification_path"],
        label="runtime lock verification",
    )
    require(
        sha256_file(verification_path) == lock_meta["runtime_verification_sha256"],
        "runtime lock-verification bytes changed",
    )
    runtime_verification = json.loads(verification_path.read_text(encoding="utf-8"))
    require(
        runtime_verification["status"] == "PASS_FROZEN_OFFLINE_ASSET_LOCK",
        "runtime lock verification did not pass",
    )
    require(
        runtime_verification["asset_lock_sha256"] == EXPECTED_LOCK_SHA256,
        "runtime verification binds a different lock",
    )

    review_meta = closure["policy_review"]
    require(
        review_meta["commit"] == EXPECTED_POLICY_REVIEW_COMMIT,
        "policy review commit changed",
    )
    require(
        review_meta["snapshot_sha256"] == EXPECTED_POLICY_REVIEW_SHA256,
        "policy review identity changed",
    )
    review_path = checked_path(
        runtime_root,
        review_meta["snapshot_path"],
        label="policy review snapshot",
    )
    require(
        sha256_file(review_path) == EXPECTED_POLICY_REVIEW_SHA256,
        "policy review snapshot bytes changed",
    )
    review = json.loads(review_path.read_text(encoding="utf-8"))
    require(review["issues"] == [], "policy review reports issues")
    require(
        review["status"] == "PASS_FROZEN_OFFLINE_ASSET_LOCK_POLICY_REVIEW",
        "policy review did not pass",
    )
    require(review["decision"] == review["status"], "policy review decision differs")
    require(all(review["checks"].values()), "one or more policy review checks failed")
    require(review["asset_lock_sha256"] == EXPECTED_LOCK_SHA256, "policy reviewed another lock")
    require(review["runtime_head"] == EXPECTED_RUNTIME_COMMIT, "policy reviewed another runtime")
    require(
        review["locked_policy_acceptance_commit"]
        == EXPECTED_POLICY_ACCEPTANCE_COMMIT,
        "policy review binds another acceptance commit",
    )
    require(
        review["locked_policy_acceptance_sha256"]
        == EXPECTED_POLICY_ACCEPTANCE_SHA256,
        "policy review binds another acceptance result",
    )

    identities = closure["frozen_identities"]
    require(
        identities["policy_acceptance_commit"] == EXPECTED_POLICY_ACCEPTANCE_COMMIT,
        "closure policy acceptance commit changed",
    )
    require(
        identities["policy_acceptance_sha256"] == EXPECTED_POLICY_ACCEPTANCE_SHA256,
        "closure policy acceptance result changed",
    )
    require(
        lock["policy_assets"]["selected_onnx_sha256"]
        == identities["selected_onnx_sha256"],
        "selected ONNX identity differs from lock",
    )

    return {
        "schema_version": "open_duck_x5.winner_v2_final_asset_freeze_verification.v1",
        "status": EXPECTED_STATUS,
        "closure_sha256": sha256_file(closure_path),
        "asset_lock_sha256": EXPECTED_LOCK_SHA256,
        "policy_review_commit": EXPECTED_POLICY_REVIEW_COMMIT,
        "policy_review_sha256": EXPECTED_POLICY_REVIEW_SHA256,
        "reviewed_runtime_commit": EXPECTED_RUNTIME_COMMIT,
        "policy_checks_verified": len(review["checks"]),
        "authority": authority,
        "remaining_blockers": closure["remaining_blockers"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--closure", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = verify_asset_freeze(args.closure, runtime_root=args.runtime_root)
    except (AssetFreezeError, KeyError, OSError, TypeError, ValueError) as exc:
        print(f"winner-v2 asset-freeze verification failed: {exc}")
        return 2
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8", newline="\n")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
