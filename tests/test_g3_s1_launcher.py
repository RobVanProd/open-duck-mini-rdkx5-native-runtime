from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "setup/run_g3_s1_suspended_guard_revalidation.sh"
PREREG = (
    ROOT
    / "artifacts/gates/grounded_validation"
    / "G3_S1_SUSPENDED_GUARD_REVALIDATION_PREREGISTRATION_20260803.json"
)
O1_REVIEW = (
    ROOT
    / "artifacts/gates/grounded_validation"
    / "G3_O1_OFFLINE_IMPLEMENTATION_PASS_REVIEWED_20260803.json"
)
LAUNCHER_REVIEW = (
    ROOT
    / "artifacts/gates/grounded_validation"
    / "G3_S1_SUSPENDED_GUARD_REVALIDATION_LAUNCHER_REVIEW_20260803.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _constant(text: str, name: str) -> str:
    match = re.search(rf'^readonly {name}="([^"]+)"$', text, re.MULTILINE)
    assert match is not None
    return match.group(1)


def test_g3_s1_launcher_is_frozen_suspended_x0_only() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    review = json.loads(LAUNCHER_REVIEW.read_text(encoding="utf-8"))

    assert prereg["status"] == "PREREGISTERED_NOT_RUN"
    assert prereg["authority"]["suspended_motion_authorized"] is False
    assert review["status"] == "PASS_REVIEWED_NOT_RUN"
    assert review["launcher"]["sha256"] == _sha256(SCRIPT)
    assert _constant(text, "expected_preregistration_sha256") == _sha256(PREREG)
    assert _constant(text, "expected_g3_o1_review_sha256") == _sha256(O1_REVIEW)
    assert text.count("-m open_duck_x5.runtime") == 1
    assert text.count("-m open_duck_x5.torque_off_readback") == 1
    assert "--grounded-guard-suspended-revalidation" in text
    assert "--gate5-authorized --hardware-authorized --suspended-or-benched" in text
    assert "--fixed-command-x 0" in text
    assert "--max-active-ticks 850" in text
    assert "--grounded-x0-authorized" not in text
    assert "--grounded-test-area-confirmed" not in text
    assert "fixed-command-x 0.08" not in text
    assert "automatic_grounded_follow_on\": False" in text


def test_g3_s1_launcher_frozen_source_matches_reviewed_commit() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    expected = {
        "expected_source_tree": "HEAD:src/open_duck_x5",
        "expected_schema_tree": "HEAD:schemas",
        "expected_pyproject_blob": "HEAD:pyproject.toml",
    }
    for constant, revision in expected.items():
        actual = subprocess.run(
            ["git", "rev-parse", revision],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert _constant(text, constant) == actual
