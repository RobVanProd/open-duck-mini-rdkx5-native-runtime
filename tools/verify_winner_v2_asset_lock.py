#!/usr/bin/env python3
"""Verify the hash-only winner-v2 offline asset lock without hardware access."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

EXPECTED_SCHEMA = "open_duck_x5.winner_v2_offline_asset_lock.v1"
EXPECTED_STATUS = "PASS_FROZEN_OFFLINE_ASSET_IDENTITIES_BLOCKED_FOR_COM_X5_AND_GATE5"
EXPECTED_POLICY_SHA256 = (
    "99d3afce0dfac127816c6327665c35b3c403e005f25cd0a505dfcb37f01304de"
)
EXPECTED_HANDOFF_MANIFEST_SHA256 = (
    "d771d188218152c782c7d688440e2dd2083b47fd9b883749123f89226c6827c5"
)
EXPECTED_LIVE_CONFIG_SHA256 = (
    "131a7b8fce1107b14f4727562f44f9e17324caf7fc22512ad7115911f050991b"
)
EXPECTED_POLICY_ACCEPTANCE_COMMIT = "4c99b5e3be203af419536382f11f3cce98283ba2"
EXPECTED_POLICY_ACCEPTANCE_SHA256 = (
    "5380897c21d3e438dbc4216ba049bc14fb6beb227a13407943d4d092519b7ddc"
)
EXPECTED_FORMAL_RESULT_SHA256 = (
    "e1842ca64e91056b96c297666803bdeec7c5ff2950d4dfe32e27044379049b14"
)
EXPECTED_REDUCED_RESULT_SHA256 = (
    "1292772e54f3734f2e48b5b0d75fb0c931949d3b7820598c4a9040a8b765dc5e"
)
REVOKED_ASSET_LOCK_SHA256 = frozenset(
    {
        "4da893b39c98d155fb0a0154a47dc46453a72b92d9d9855b5563746fa34de940",
    }
)
EXPECTED_OFFSETS_RAD = [
    0.0844,
    0.0721,
    -0.089,
    0.0371,
    -0.0767,
    0.0245,
    0.0,
    -0.089,
    -0.0399,
    0.0951,
    -0.0476,
    0.066,
    0.0798,
    0.1887,
]


class AssetLockError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssetLockError(message)


def require_not_revoked_asset_lock_hash(lock_sha256: str) -> None:
    require(
        lock_sha256 not in REVOKED_ASSET_LOCK_SHA256,
        f"asset lock is explicitly stale/revoked: {lock_sha256}",
    )


def verify_files(root: Path, files: dict[str, str], *, label: str) -> int:
    checked = 0
    for relative, expected_hash in sorted(files.items()):
        path = root / relative
        require(path.is_file(), f"{label} file is missing: {relative}")
        require(
            sha256_file(path) == expected_hash,
            f"{label} hash mismatch: {relative}",
        )
        checked += 1
    return checked


def verify_asset_lock(
    lock_path: Path,
    *,
    runtime_root: Path,
    policy_repo_root: Path,
) -> dict[str, object]:
    lock_sha256 = sha256_file(lock_path)
    require_not_revoked_asset_lock_hash(lock_sha256)
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    require(lock["schema_version"] == EXPECTED_SCHEMA, "asset-lock schema changed")
    require(lock["status"] == EXPECTED_STATUS, "asset-lock status changed")
    require(lock["frozen_offline_asset_identities"] is True, "asset lock is not frozen")

    authority = lock["authority"]
    require(authority["cpu_only"] is True, "asset lock is not CPU-only")
    for key in (
        "gate5",
        "rdkx5_access",
        "robot_clearance",
        "robot_or_motor_access",
        "runtime_deployment",
    ):
        require(authority[key] is False, f"asset lock broadened authority: {key}")

    config = lock["config_asset"]
    semantics = config["semantics"]
    require(
        config["live_board_sha256"] == EXPECTED_LIVE_CONFIG_SHA256,
        "live config identity changed",
    )
    require(config["content_committed_here"] is False, "live config bytes were embedded")
    require(semantics["start_paused"] is True, "start_paused must remain true")
    require(semantics["imu_upside_down"] is True, "IMU mapping must remain upside-down")
    require(
        semantics["phase_frequency_factor_offset"] == 0.0,
        "phase-frequency offset changed",
    )
    require(
        semantics["joints_offsets_rad_in_contract_order"] == EXPECTED_OFFSETS_RAD,
        "soft joint offsets changed",
    )

    runtime_root = runtime_root.resolve()
    runtime_assets = lock["runtime_assets"]
    runtime_checked = verify_files(
        runtime_root,
        runtime_assets["files"],
        label="runtime",
    )
    evidence_files = {
        item["path"]: item["sha256"]
        for name, item in lock["evidence_assets"].items()
        if name.startswith("runtime_")
    }
    runtime_evidence_checked = verify_files(
        runtime_root,
        evidence_files,
        label="runtime evidence",
    )
    require(
        lock["evidence_assets"]["runtime_full_recursive_result"]["sha256"]
        == EXPECTED_FORMAL_RESULT_SHA256,
        "formal runtime result identity changed",
    )
    require(
        lock["evidence_assets"]["runtime_reduced_recursive_result"]["sha256"]
        == EXPECTED_REDUCED_RESULT_SHA256,
        "corrected reduced runtime result identity changed",
    )

    policy_repo_root = policy_repo_root.resolve()
    policy_assets = lock["policy_assets"]
    require(
        policy_assets["corrected_handoff_manifest_sha256"]
        == EXPECTED_HANDOFF_MANIFEST_SHA256,
        "corrected package manifest identity changed",
    )
    require(
        policy_assets["selected_onnx_sha256"] == EXPECTED_POLICY_SHA256,
        "selected policy identity changed",
    )
    package_root = policy_repo_root / policy_assets["package_root"]
    require(package_root.is_dir(), "corrected policy handoff package is missing")
    require(
        sha256_file(package_root / "manifest.json")
        == EXPECTED_HANDOFF_MANIFEST_SHA256,
        "corrected policy handoff manifest bytes changed",
    )
    policy_checked = verify_files(
        package_root,
        policy_assets["files"],
        label="policy package",
    )

    acceptance = lock["evidence_assets"]["policy_recursive_closure_result"]
    require(
        acceptance["commit"] == EXPECTED_POLICY_ACCEPTANCE_COMMIT,
        "policy acceptance commit changed",
    )
    require(
        acceptance["sha256"] == EXPECTED_POLICY_ACCEPTANCE_SHA256,
        "policy acceptance result identity changed",
    )
    require(
        sha256_file(policy_repo_root / acceptance["path"])
        == acceptance["sha256"],
        "policy recursive-closure acceptance result changed",
    )
    policy_result = json.loads(
        (policy_repo_root / acceptance["path"]).read_text(encoding="utf-8")
    )
    require(
        policy_result["decision"] == "PASS_RECURSIVE_BIT_EXACT_WIRE_CLOSURE",
        "policy acceptance decision changed",
    )
    require(
        policy_result["runtime_result_sha256"] == EXPECTED_FORMAL_RESULT_SHA256,
        "policy acceptance binds a different formal result",
    )
    require(
        policy_result["runtime_reduced_result_sha256"]
        == EXPECTED_REDUCED_RESULT_SHA256,
        "policy acceptance binds a different corrected reduced result",
    )
    require(
        policy_result["checks"]["independent_replay"][
            "independent_teacher_forced_observation_exact_zero"
        ]
        is True,
        "policy independent replay did not prove exact-zero observation closure",
    )
    require(
        policy_result["checks"]["reduced_reporting"][
            "teacher_forced_observation_gate_exact_zero_only"
        ]
        is True,
        "policy reduced report does not enforce exact-zero observation closure",
    )
    require(
        policy_result["authority"]["robot_clearance"] is False,
        "policy result unexpectedly grants robot clearance",
    )

    require(len(lock["blockers"]) == 4, "asset-lock blocker set changed")
    return {
        "schema_version": "open_duck_x5.winner_v2_asset_lock_verification.v1",
        "status": "PASS_FROZEN_OFFLINE_ASSET_LOCK",
        "asset_lock_sha256": lock_sha256,
        "runtime_files_checked": runtime_checked,
        "runtime_evidence_files_checked": runtime_evidence_checked,
        "policy_package_files_checked": policy_checked,
        "policy_acceptance_result_checked": True,
        "live_config_verification": "HASH_ONLY_UNTIL_NO_SERVO_X5_PREFLIGHT",
        "authority": authority,
        "blockers": lock["blockers"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset-lock", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, default=Path.cwd())
    parser.add_argument("--policy-repo-root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = verify_asset_lock(
            args.asset_lock,
            runtime_root=args.runtime_root,
            policy_repo_root=args.policy_repo_root,
        )
    except (AssetLockError, KeyError, OSError, TypeError, ValueError) as exc:
        print(f"winner-v2 asset-lock verification failed: {exc}")
        return 2
    payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8", newline="\n")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
