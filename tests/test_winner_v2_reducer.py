from __future__ import annotations

import json
import runpy
from pathlib import Path
from types import FunctionType

import pytest

NAMESPACE = runpy.run_path("tools/reduce_winner_v2_recursive_result.py")
reduce_frozen_result: FunctionType = NAMESPACE["reduce_frozen_result"]
main: FunctionType = NAMESPACE["main"]
FULL_RESULT = Path(
    "artifacts/gates/phase_5_policy/"
    "winner_v2_runtime_v2_verification_20260719.json"
)


def test_reducer_enforces_exact_teacher_forced_observation_gate() -> None:
    reduced = reduce_frozen_result(FULL_RESULT)
    assert reduced["status"] == "PASS_RECURSIVE_BIT_EXACT_WIRE_CLOSURE"
    for cell in reduced["cells"]:
        gates = cell["semantic_gates"]
        assert gates["teacher_forced_observation_exact_zero"] is True
        assert "teacher_forced_observation_at_most_1e_6" not in gates
        assert cell["semantic_max_abs_error"]["observation"] == 0.0


def test_reducer_refuses_changed_full_result(tmp_path: Path) -> None:
    changed = tmp_path / "changed.json"
    result = json.loads(FULL_RESULT.read_text(encoding="utf-8"))
    result["status"] = "HOLD_CHANGED"
    changed.write_text(json.dumps(result), encoding="utf-8")
    with pytest.raises(ValueError, match="SHA-256 changed"):
        reduce_frozen_result(changed)


def test_reducer_cli_writes_lf_only(tmp_path: Path) -> None:
    output = tmp_path / "reduced.json"
    assert main(["--full-result", str(FULL_RESULT), "--output", str(output)]) == 0
    payload = output.read_bytes()
    assert payload.endswith(b"\n")
    assert b"\r\n" not in payload
