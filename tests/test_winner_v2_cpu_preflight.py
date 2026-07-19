from __future__ import annotations

import ast
import gc
from pathlib import Path

import numpy as np
import pytest

import open_duck_x5.winner_v2_cpu_preflight as preflight
from open_duck_x5.winner_v2_cpu_preflight import (
    GOLDEN_TICKS,
    GoldenInputs,
    TimingCell,
    WinnerV2CpuPreflightError,
    benchmark_cell,
    build_result,
    environment_gates,
)


class FakeTransaction:
    def __init__(self) -> None:
        self.committed_ticks = 0
        self.pending = False

    def stage_tick(self, **arguments: object) -> np.ndarray:
        assert arguments["tick_index"] == self.committed_ticks
        assert arguments["servo_sample_tick_index"] == self.committed_ticks
        assert arguments["imu_sample_tick_index"] == self.committed_ticks
        assert arguments["contacts_sample_tick_index"] == self.committed_ticks
        self.pending = True
        return np.zeros(14, dtype=np.float64)

    def complete_send(self, *, write_succeeded: bool) -> None:
        assert self.pending
        assert write_succeeded is True
        self.pending = False
        self.committed_ticks += 1


def _golden(command_x: float) -> GoldenInputs:
    commands = np.zeros((GOLDEN_TICKS, 7), dtype=np.float64)
    commands[:, 0] = command_x
    return GoldenInputs(
        gyro_rad_s=np.zeros((GOLDEN_TICKS, 3), dtype=np.float64),
        acceleration_m_s2=np.zeros((GOLDEN_TICKS, 3), dtype=np.float64),
        commands=commands,
        positions_rad=np.zeros((GOLDEN_TICKS, 14), dtype=np.float64),
        velocities_rad_s=np.zeros((GOLDEN_TICKS, 14), dtype=np.float64),
        foot_contacts=np.zeros((GOLDEN_TICKS, 2), dtype=np.float64),
    )


def test_benchmark_is_in_memory_and_resets_each_golden_episode() -> None:
    transactions: list[FakeTransaction] = []

    def factory() -> FakeTransaction:
        transaction = FakeTransaction()
        transactions.append(transaction)
        return transaction

    now = 0

    def clock() -> int:
        nonlocal now
        now += 100
        return now

    assert gc.isenabled()
    cell = benchmark_cell(
        command_x=0.08,
        inputs=_golden(0.08),
        soft_offsets_rad=np.zeros(14, dtype=np.float64),
        ticks=GOLDEN_TICKS + 1,
        make_transaction=factory,
        clock_ns=clock,
    )

    assert len(transactions) == 2
    assert [transaction.committed_ticks for transaction in transactions] == [600, 1]
    np.testing.assert_array_equal(cell.stage_ns, 100)
    np.testing.assert_array_equal(cell.commit_ns, 100)
    np.testing.assert_array_equal(cell.transaction_ns, 200)
    assert gc.isenabled()


def test_benchmark_restores_gc_after_transaction_failure() -> None:
    class BrokenTransaction(FakeTransaction):
        def stage_tick(self, **_arguments: object) -> np.ndarray:
            assert not gc.isenabled()
            raise RuntimeError("synthetic inference failure")

    with pytest.raises(RuntimeError, match="synthetic inference failure"):
        benchmark_cell(
            command_x=0.0,
            inputs=_golden(0.0),
            soft_offsets_rad=np.zeros(14, dtype=np.float64),
            ticks=1,
            make_transaction=BrokenTransaction,
        )
    assert gc.isenabled()


def test_environment_gate_requires_exact_x5_rt_shape() -> None:
    environment = {
        "system": "Linux",
        "affinity": [7],
        "scheduler": 1,
        "sched_fifo_value": 1,
        "priority": 80,
        "governor": "performance",
        "isolated_cpus": "2-3,7",
    }
    assert all(environment_gates(environment).values())

    environment["affinity"] = [6, 7]
    assert environment_gates(environment)["affinity_exact_cpu7"] is False
    environment["affinity"] = [7]
    environment["isolated_cpus"] = "malformed"
    assert environment_gates(environment)["cpu7_isolated"] is False


def test_result_cannot_claim_preflight_with_short_population(tmp_path: Path) -> None:
    envelope = tmp_path / "envelope.json"
    config = tmp_path / "duck_config.json"
    envelope.write_text("{}\n", encoding="utf-8")
    config.write_text("{}\n", encoding="utf-8")
    durations = np.full(9_999, 1_000_000, dtype=np.int64)
    cells = [
        TimingCell(command, durations.copy(), durations.copy(), durations.copy())
        for command in preflight.COMMANDS
    ]
    environment = {
        "system": "Linux",
        "affinity": [7],
        "scheduler": 1,
        "sched_fifo_value": 1,
        "priority": 80,
        "governor": "performance",
        "isolated_cpus": "7",
    }

    result = build_result(
        handoff_root=tmp_path,
        envelope_path=envelope,
        config_path=config,
        formal_result={"status": "PASS_RECURSIVE_BIT_EXACT_WIRE_CLOSURE"},
        cells=cells,
        environment=environment,
    )

    assert result["status"] == "HOLD_X5_CPU_ONLY_PREFLIGHT"
    assert result["gates"]["minimum_10000_ticks_per_command"] is False
    assert result["authority"] == {
        "robot_clearance": False,
        "gate5": False,
        "runtime_deployment": False,
        "motion": False,
        "serial": False,
        "torque": False,
    }


def test_invalid_envelope_identity_stops_before_formal_verifier(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    called = False

    def reject(**_arguments: object) -> tuple[dict[str, object], object]:
        raise WinnerV2CpuPreflightError("policy envelope SHA-256 differs")

    def forbidden(*_arguments: object, **_keywords: object) -> dict[str, object]:
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(preflight, "validate_preflight_inputs", reject)
    monkeypatch.setattr(preflight, "run_formal_verification", forbidden)
    summary = tmp_path / "summary.json"
    samples = tmp_path / "samples.jsonl"

    status = preflight.main(
        [
            "--handoff-root",
            str(tmp_path / "handoff"),
            "--envelope",
            str(tmp_path / "envelope.json"),
            "--expected-envelope-sha256",
            "0" * 64,
            "--config",
            str(tmp_path / "duck_config.json"),
            "--expected-config-sha256",
            "0" * 64,
            "--samples-output",
            str(samples),
            "--summary-output",
            str(summary),
        ]
    )

    assert status == 2
    assert called is False
    assert not samples.exists()
    assert not summary.exists()


def test_module_has_no_hardware_stack_imports() -> None:
    source = Path(preflight.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.append(node.module or "")
    joined = "\n".join(modules)
    for forbidden in ("serial", ".bus", ".sensors", "gpio", "smbus"):
        assert forbidden not in joined.lower()
