from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

VERIFIER = Path("tools/verify_winner_v13_state_coherent.py")


def test_verifier_is_offline_exact_asset_execution() -> None:
    source = VERIFIER.read_text(encoding="utf-8")
    assert "PREREGISTRATION_SHA256" in source
    assert "LOCOMOTION_TICKS = 8" in source
    assert '"exact_250_calibration_ticks"' in source
    assert '"real_graph_chain_bit_exact"' in source
    assert '"independent_p30_observer_exact"' in source
    assert '"cpu_only_no_hardware_execution": True' in source
    assert '"rdkx5_or_robot_access": 0' in source
    assert '"gate5": False' in source
    assert "serial.Serial" not in source
    assert '"smbus2"' in source  # forbidden-import declaration, never an import


def test_verifier_does_not_import_robot_interfaces() -> None:
    tree = ast.parse(VERIFIER.read_text(encoding="utf-8"), filename=str(VERIFIER))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add("." * node.level + (node.module or ""))
    forbidden = {
        "serial",
        "smbus2",
        "pygame",
        "open_duck_x5.runtime",
        "open_duck_x5.servo_bus",
    }
    assert imported.isdisjoint(forbidden)


def test_verifier_help_requires_explicit_assets_and_outputs() -> None:
    completed = subprocess.run(
        [sys.executable, str(VERIFIER), "--help"],
        check=True,
        capture_output=True,
        text=True,
    )
    for flag in (
        "--calibrator",
        "--policy",
        "--p30-fit",
        "--reference-table",
        "--output",
        "--markdown",
    ):
        assert flag in completed.stdout
