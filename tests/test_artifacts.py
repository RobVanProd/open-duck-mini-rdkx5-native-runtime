from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_reviewed_artifact_manifest_is_complete_and_valid() -> None:
    root = Path(__file__).parents[1]
    result = subprocess.run(
        [sys.executable, "tools/hash_artifacts.py", "--check"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    manifest = (root / "artifacts" / "manifest.sha256").read_text(encoding="utf-8")
    assert "timing.jsonl" not in manifest
    assert "summary.json" in manifest
