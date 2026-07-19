from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from open_duck_x5.winner_v2_cpu_preflight import (
    COMMANDS,
    MINIMUM_TICKS_PER_COMMAND,
    TimingCell,
    build_result,
    write_samples,
)
from open_duck_x5.winner_v2_cpu_preflight_review import (
    EXPECTED_CONFIG_SHA256,
    EXPECTED_HANDOFF_MANIFEST_SHA256,
    EXPECTED_PREFLIGHT_MODULE_SHA256,
    EXPECTED_RUNNER_SHA256,
    EXPECTED_SELECTED_ONNX_SHA256,
    EXPECTED_SOURCE_ARCHIVE_SHA256,
    EXPECTED_SOURCE_COMMIT,
    WinnerV2CpuPreflightReviewError,
    main,
    validate_preflight_evidence,
)

ENVELOPE_SHA256 = "a" * 64


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_sha256s(root: Path) -> None:
    names = sorted(
        path.name for path in root.iterdir() if path.is_file() and path.name != "sha256sums.txt"
    )
    (root / "sha256sums.txt").write_text(
        "".join(f"{_sha256(root / name)}  {name}\n" for name in names),
        encoding="utf-8",
    )


def _valid_evidence(tmp_path: Path) -> Path:
    root = tmp_path / "evidence"
    root.mkdir()
    envelope = tmp_path / "envelope.json"
    config = tmp_path / "duck_config.json"
    envelope.write_bytes(b"envelope")
    config.write_bytes(b"config")

    ticks = MINIMUM_TICKS_PER_COMMAND
    stage = np.full(ticks, 500_000, dtype=np.int64)
    commit = np.full(ticks, 100_000, dtype=np.int64)
    transaction = stage + commit
    cells = [
        TimingCell(command, stage.copy(), commit.copy(), transaction.copy())
        for command in COMMANDS
    ]
    environment = {
        "system": "Linux",
        "platform": "Linux-rdk-x5",
        "python": "3.10.12",
        "numpy": "2.0.0",
        "onnxruntime": "1.20.0",
        "affinity": [7],
        "scheduler": 1,
        "sched_fifo_value": 1,
        "priority": 80,
        "governor": "performance",
        "isolated_cpus": "7",
    }
    result = build_result(
        handoff_root=tmp_path / "handoff",
        envelope_path=envelope,
        config_path=config,
        formal_result={
            "status": "PASS_RECURSIVE_BIT_EXACT_WIRE_CLOSURE",
            "manifest_sha256": EXPECTED_HANDOFF_MANIFEST_SHA256,
        },
        cells=cells,
        environment=environment,
    )
    result["inputs"]["policy_envelope"]["sha256"] = ENVELOPE_SHA256
    result["inputs"]["config"]["sha256"] = EXPECTED_CONFIG_SHA256
    timing = root / "timing.jsonl"
    write_samples(timing, cells)
    result["samples"] = {
        "path": str(timing),
        "sha256": _sha256(timing),
        "records": len(COMMANDS) * ticks,
    }
    (root / "summary.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    metadata = {
        "schema_version": "open_duck_x5.winner_v2_cpu_preflight_runner.v1",
        "source_commit": EXPECTED_SOURCE_COMMIT,
        "source_archive_sha256": EXPECTED_SOURCE_ARCHIVE_SHA256,
        "preflight_module_sha256": EXPECTED_PREFLIGHT_MODULE_SHA256,
        "runner_sha256": EXPECTED_RUNNER_SHA256,
        "policy_envelope_sha256": ENVELOPE_SHA256,
        "config_sha256": EXPECTED_CONFIG_SHA256,
        "handoff_manifest_sha256": EXPECTED_HANDOFF_MANIFEST_SHA256,
        "selected_onnx_sha256": EXPECTED_SELECTED_ONNX_SHA256,
        "ticks_per_command": ticks,
        "commands": list(COMMANDS),
        "rt_cpu": 7,
        "rt_priority": 80,
        "preflight_exit_status": 0,
        "governor_restore_status": 0,
        "review_status": "REVIEW_REQUIRED",
        "no_servo_access": True,
        "robot_clearance": False,
        "gate5": False,
        "motion": False,
        "torque": False,
    }
    (root / "runner-metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    for name, value in (
        ("governor-before.txt", "schedutil\n"),
        ("governor-during.txt", "performance\n"),
        ("governor-after.txt", "schedutil\n"),
        ("preflight-stdout.txt", "result=PASS_X5_CPU_ONLY_PREFLIGHT_CANDIDATE\n"),
        ("preflight-stderr.txt", ""),
        ("source-commit.txt", f"{EXPECTED_SOURCE_COMMIT}\n"),
        (
            "source-archive-sha256.txt",
            f"{EXPECTED_SOURCE_ARCHIVE_SHA256}  source.tar.gz\n",
        ),
    ):
        (root / name).write_text(value, encoding="utf-8")
    _write_sha256s(root)
    return root


def test_independent_review_recomputes_complete_evidence(tmp_path: Path) -> None:
    root = _valid_evidence(tmp_path)

    result = validate_preflight_evidence(
        evidence_dir=root,
        expected_envelope_sha256=ENVELOPE_SHA256,
    )

    assert result["status"] == "PASS_X5_CPU_PREFLIGHT_EVIDENCE_VALIDATED"
    assert result["review_status"] == "REVIEW_REQUIRED"
    assert len(result["recomputed_transaction_ms"]) == 2
    assert result["recomputed_transaction_ms"][1]["p99_9"] == 0.6
    assert all(value is False for value in result["authority"].values())


def test_reviewer_pins_current_runner_and_preflight_module() -> None:
    assert _sha256(Path("setup/run_winner_v2_cpu_preflight.sh")) == EXPECTED_RUNNER_SHA256
    assert (
        _sha256(Path("src/open_duck_x5/winner_v2_cpu_preflight.py"))
        == EXPECTED_PREFLIGHT_MODULE_SHA256
    )


def test_review_rejects_coherently_rehashed_summary_stat_tamper(tmp_path: Path) -> None:
    root = _valid_evidence(tmp_path)
    summary_path = root / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["timing_cells"][1]["transaction_ms"]["p99_9"] = 0.7
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_sha256s(root)

    with pytest.raises(WinnerV2CpuPreflightReviewError, match="differs from timing JSONL"):
        validate_preflight_evidence(
            evidence_dir=root,
            expected_envelope_sha256=ENVELOPE_SHA256,
        )


def test_review_rejects_coherently_rehashed_governor_restore_tamper(tmp_path: Path) -> None:
    root = _valid_evidence(tmp_path)
    (root / "governor-after.txt").write_text("performance\n", encoding="utf-8")
    _write_sha256s(root)

    with pytest.raises(WinnerV2CpuPreflightReviewError, match="governor"):
        validate_preflight_evidence(
            evidence_dir=root,
            expected_envelope_sha256=ENVELOPE_SHA256,
        )


def test_review_rejects_coherently_rehashed_runner_identity_tamper(tmp_path: Path) -> None:
    root = _valid_evidence(tmp_path)
    metadata_path = root / "runner-metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["runner_sha256"] = "b" * 64
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _write_sha256s(root)

    with pytest.raises(WinnerV2CpuPreflightReviewError, match="runner metadata"):
        validate_preflight_evidence(
            evidence_dir=root,
            expected_envelope_sha256=ENVELOPE_SHA256,
        )


def test_review_cli_requires_output_outside_immutable_evidence(tmp_path: Path) -> None:
    root = _valid_evidence(tmp_path)
    output = root / "review.json"

    status = main(
        [
            "--evidence-dir",
            str(root),
            "--expected-envelope-sha256",
            ENVELOPE_SHA256,
            "--output",
            str(output),
        ]
    )

    assert status == 2
    assert not output.exists()
