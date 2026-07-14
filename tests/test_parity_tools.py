from __future__ import annotations

import json
from pathlib import Path

from open_duck_x5.tools.check_motors import main as check_motors
from open_duck_x5.tools.configure_motor import main as configure_motor
from open_duck_x5.tools.find_soft_offsets import main as find_soft_offsets
from open_duck_x5.tools.set_servo_mid import main as set_servo_mid


def test_script_parity_tools_complete_against_mock(tmp_path: Path) -> None:
    root = Path(__file__).parents[1]
    config = root / "duck_config.example.json"
    candidate = tmp_path / "candidate.json"

    assert check_motors(["--bus", "mock"]) == 0
    assert (
        configure_motor(
            ["--bus", "mock", "--current-id", "20", "--id", "20"]
        )
        == 0
    )
    assert (
        find_soft_offsets(
            [
                "--bus",
                "mock",
                "--config",
                str(config),
                "--output",
                str(candidate),
            ]
        )
        == 0
    )
    assert candidate.is_file()
    assert len(json.loads(candidate.read_text(encoding="utf-8"))["joints_offsets"]) == 14
    assert (
        set_servo_mid(
            ["--bus", "mock", "--id", "20", "--confirm-at-midpoint"]
        )
        == 0
    )
