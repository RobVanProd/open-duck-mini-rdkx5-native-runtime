from __future__ import annotations

import ast
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import open_duck_x5.winner_v2 as winner_v2
from open_duck_x5.constants import ACTION_DIM, CONTROL_PERIOD_NS, HOME_RAD
from open_duck_x5.winner_v2 import WinnerV2ContractError
from open_duck_x5.winner_v13_state_coherent import (
    CALIBRATION_TICKS,
    HOME_RETURN_TICKS,
    GraphAsset,
    GraphSpec,
    P30FitAsset,
    StateCoherentP30Observer,
    StateCoherentTargetPipeline,
    TensorSpec,
    WinnerV13ContractError,
    WinnerV13SendError,
    WinnerV13StateCoherentTransaction,
    WinnerV13StateError,
    exact_allowlist,
)
from tools.winner_v14_optimized import (
    WinnerV14X5OptimizedTransaction,
    X5OptimizedP30Observer,
    X5OptimizedTargetPipeline,
)
from tools.winner_v15_graph_host_optimized import (
    WinnerV15GraphHostOptimizedTransaction,
)
from tools.winner_v16_target_optimized import (
    WinnerV16TargetOptimizedTransaction,
    X5TrustedOffsetTargetPipeline,
)

FROZEN_SOURCE_SHA256 = {
    "winner_v2.py": "235d32eca034e4d7d5507337bb851b84ccb206d4ad499c86279381e82d38ae2b",
    "winner_v12_two_stage.py": "231d76ed15611447a9215b22252a3e8754dc8a378cc3166f870f81b5d7dca25d",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _calibrator_spec() -> GraphSpec:
    return GraphSpec(
        observation=TensorSpec("obs", (1, 115)),
        previous_action=TensorSpec("previous_action", (1, 14)),
        hidden_in=TensorSpec("h_in", (1, 64)),
        action=TensorSpec("calibration_actions", (1, 14)),
        previous_action_out=TensorSpec("previous_action_out", (1, 14)),
        hidden_out=TensorSpec("h_out", (1, 64)),
    )


def _locomotion_spec() -> GraphSpec:
    return GraphSpec(
        observation=TensorSpec("obs", (1, 115)),
        previous_action=TensorSpec("previous_action", (1, 14)),
        hidden_in=TensorSpec("h_in", (1, 64)),
        calibration_context=TensorSpec("calibration_context", (1, 64)),
        action=TensorSpec("continuous_actions", (1, 14)),
        previous_action_out=TensorSpec("previous_action_out", (1, 14)),
        hidden_out=TensorSpec("h_out", (1, 64)),
    )


class FakeNode:
    def __init__(self, tensor: TensorSpec) -> None:
        self.name = tensor.name
        self.shape = list(tensor.shape)
        self.type = tensor.dtype


class FakeBinding:
    def __init__(self) -> None:
        self.inputs: dict[str, np.ndarray] = {}
        self.outputs: dict[str, np.ndarray] = {}

    def bind_ortvalue_input(self, name: str, value: np.ndarray) -> None:
        self.inputs[name] = value

    def bind_ortvalue_output(self, name: str, value: np.ndarray) -> None:
        self.outputs[name] = value


class FakeSession:
    def __init__(self, spec: GraphSpec, *, stage: str) -> None:
        self.spec = spec
        self.stage = stage
        self.binding = FakeBinding()
        self.calls = 0
        self.action_override: float | None = None
        self.previous_action_out_delta = np.float32(0.0)
        self.hidden_out_override: float | None = None

    def get_inputs(self) -> list[FakeNode]:
        return [FakeNode(tensor) for tensor in self.spec.inputs]

    def get_outputs(self) -> list[FakeNode]:
        return [FakeNode(tensor) for tensor in self.spec.outputs]

    def get_providers(self) -> list[str]:
        return ["CPUExecutionProvider"]

    def io_binding(self) -> FakeBinding:
        return self.binding

    def run_with_iobinding(self, binding: FakeBinding) -> None:
        self.calls += 1
        previous = binding.inputs[self.spec.previous_action.name]
        hidden = binding.inputs[self.spec.hidden_in.name]
        action = binding.outputs[self.spec.action.name]
        previous_out = binding.outputs[self.spec.previous_action_out.name]
        hidden_out = binding.outputs[self.spec.hidden_out.name]
        increment = np.float32(0.001 if self.stage == "calibration" else 0.01)
        np.add(previous, increment, out=action)
        np.copyto(previous_out, action)
        np.add(hidden, np.float32(0.002), out=hidden_out)
        if self.action_override is not None:
            action[0, 0] = np.float32(self.action_override)
            previous_out[0, 0] = action[0, 0]
        previous_out[0, 0] += self.previous_action_out_delta
        if self.hidden_out_override is not None:
            hidden_out[0, 0] = np.float32(self.hidden_out_override)


def _install_fake_ort(monkeypatch: pytest.MonkeyPatch, sessions: dict[str, FakeSession]) -> None:
    class FakeOrtValue:
        @staticmethod
        def ortvalue_from_numpy(array: np.ndarray) -> np.ndarray:
            return array

    class FakeSessionOptions:
        def __init__(self) -> None:
            self.execution_mode = None
            self.graph_optimization_level = None
            self.intra_op_num_threads = 0
            self.inter_op_num_threads = 0

        def add_session_config_entry(self, _key: str, _value: str) -> None:
            return None

    def make_session(
        path: str,
        *,
        sess_options: FakeSessionOptions,
        providers: list[str],
    ) -> FakeSession:
        assert providers == ["CPUExecutionProvider"]
        assert sess_options.intra_op_num_threads == 1
        return sessions[Path(path).name]

    module = SimpleNamespace(
        InferenceSession=make_session,
        OrtValue=FakeOrtValue,
        SessionOptions=FakeSessionOptions,
        ExecutionMode=SimpleNamespace(ORT_SEQUENTIAL="ORT_SEQUENTIAL"),
        GraphOptimizationLevel=SimpleNamespace(ORT_ENABLE_ALL="ORT_ENABLE_ALL"),
    )
    monkeypatch.setitem(sys.modules, "onnxruntime", module)


def _reference(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "reference.npz"
    commands = np.zeros((240, 3), dtype=np.float32)
    commands[0, 0] = np.float32(0.074)
    actions = np.zeros((240, 27, ACTION_DIM), dtype=np.float32)
    actions[0] = np.float32(0.123)
    np.savez(path, commands=commands, actions=actions)
    monkeypatch.setattr(winner_v2, "WINNER_V2_REFERENCE_TABLE_SHA256", _sha256(path))
    return path


def _fit(tmp_path: Path) -> Path:
    path = tmp_path / "p30.json"
    path.write_text(json.dumps({"primary": {"joints": {}}}), encoding="utf-8")
    return path


def _make_host(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    enabled: bool = True,
    host_type: type[WinnerV13StateCoherentTransaction] = WinnerV13StateCoherentTransaction,
) -> tuple[WinnerV13StateCoherentTransaction, FakeSession, FakeSession]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    cal_spec = _calibrator_spec()
    loco_spec = _locomotion_spec()
    cal_session = FakeSession(cal_spec, stage="calibration")
    loco_session = FakeSession(loco_spec, stage="locomotion")
    calibrator_path = tmp_path / "calibrator.onnx"
    locomotion_path = tmp_path / "locomotion.onnx"
    calibrator_path.write_bytes(b"state-coherent calibrator")
    locomotion_path.write_bytes(b"state-coherent locomotion")
    _install_fake_ort(
        monkeypatch,
        {
            calibrator_path.name: cal_session,
            locomotion_path.name: loco_session,
        },
    )
    fit = _fit(tmp_path)
    host = host_type(
        calibrator=GraphAsset(
            calibrator_path,
            cal_spec,
            exact_allowlist(frozenset({_sha256(calibrator_path)})),
        ),
        locomotion=GraphAsset(
            locomotion_path,
            loco_spec,
            exact_allowlist(frozenset({_sha256(locomotion_path)})),
        ),
        p30_fit=P30FitAsset(
            fit,
            frozenset({_sha256(fit)}),
        ),
        reference_table_path=_reference(tmp_path, monkeypatch),
        enabled=enabled,
        warmup_runs=0,
    )
    return host, cal_session, loco_session


def _samples(command_x: float = 0.0) -> dict[str, object]:
    command = np.zeros(7, dtype=np.float64)
    command[0] = command_x
    return {
        "gyro_rad_s": np.zeros(3, dtype=np.float64),
        "acceleration_m_s2": np.asarray([0.0, 0.0, 9.81], dtype=np.float64),
        "commands": command,
        "positions_rad": HOME_RAD.copy(),
        "velocities_rad_s": np.zeros(ACTION_DIM, dtype=np.float64),
        "foot_contacts": np.ones(2, dtype=np.float64),
        "servo_stale": np.zeros(ACTION_DIM, dtype=np.bool_),
        "imu_stale": False,
        "contacts_stale": False,
        "soft_offsets_rad": np.zeros(ACTION_DIM, dtype=np.float64),
    }


def _stage(host: WinnerV13StateCoherentTransaction, tick: int, command: float = 0.0) -> np.ndarray:
    return host.stage_tick(
        tick_index=tick,
        logical_period_ns=CONTROL_PERIOD_NS,
        servo_sample_tick_index=tick,
        imu_sample_tick_index=tick,
        contacts_sample_tick_index=tick,
        **_samples(command),
    )


def _stage_samples(
    host: WinnerV13StateCoherentTransaction,
    tick: int,
    sample: dict[str, object],
) -> np.ndarray:
    return host.stage_tick(
        tick_index=tick,
        logical_period_ns=CONTROL_PERIOD_NS,
        servo_sample_tick_index=tick,
        imu_sample_tick_index=tick,
        contacts_sample_tick_index=tick,
        **sample,
    )


def _finish_calibration(host: WinnerV13StateCoherentTransaction) -> None:
    for tick in range(CALIBRATION_TICKS):
        _stage(host, tick)
        host.complete_send(write_succeeded=True)


def test_exact_250_tick_handoff_and_boundary_observations(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    host, _, _ = _make_host(monkeypatch, tmp_path)
    _finish_calibration(host)
    assert host.confirmed_calibration_ticks == 250
    assert host.confirmed_home_return_ticks == 0
    with pytest.raises(WinnerV13StateError, match="explicit state-coherent handoff"):
        _stage(host, 250, 0.074)

    host.confirm_calibration_handoff(True)
    assert host.handoff_complete
    np.testing.assert_allclose(
        host.locomotion_previous_action,
        np.full(ACTION_DIM, 0.25, dtype=np.float32),
        atol=2e-6,
    )
    np.testing.assert_array_equal(host.locomotion_hidden, np.zeros(64, dtype=np.float32))
    np.testing.assert_allclose(
        host.calibration_context,
        np.full(64, 0.5, dtype=np.float32),
        atol=2e-6,
    )

    _stage(host, 250, 0.074)
    first = host.observation_view.copy()
    np.testing.assert_allclose(first[41:55], 0.250, atol=2e-6)
    np.testing.assert_allclose(first[55:69], 0.249, atol=2e-6)
    np.testing.assert_allclose(first[69:83], 0.248, atol=2e-6)
    np.testing.assert_array_equal(first[99:101], np.asarray([1.0, 0.0], dtype=np.float32))
    np.testing.assert_allclose(first[101:115], 0.123, atol=2e-6)
    expected_observer = HOME_RAD + 0.25 * 0.25
    np.testing.assert_allclose(first[83:97], expected_observer, atol=2e-6)
    host.complete_send(write_succeeded=True)

    _stage(host, 251, 0.074)
    second = host.observation_view.copy()
    np.testing.assert_allclose(second[41:55], 0.250, atol=2e-6)
    np.testing.assert_allclose(second[55:69], 0.249, atol=2e-6)
    np.testing.assert_allclose(second[69:83], 0.248, atol=2e-6)
    assert not np.array_equal(second[99:101], np.asarray([1.0, 0.0], dtype=np.float32))
    host.discard_staged()


def test_calibration_uses_slew_and_locomotion_requires_identity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    host, _, _ = _make_host(monkeypatch, tmp_path)
    _stage(host, 0)
    first_sent = host.logical_target_view.copy()
    host.complete_send(write_succeeded=True)
    assert np.max(np.abs(first_sent - HOME_RAD)) < 0.001

    _finish_remaining = range(1, CALIBRATION_TICKS)
    for tick in _finish_remaining:
        _stage(host, tick)
        host.complete_send(write_succeeded=True)
    host.confirm_calibration_handoff(True)
    before = host.target_pipeline.previous_sent_logical_target_view.copy()
    _stage(host, 250, 0.074)
    np.testing.assert_array_equal(
        host.target_pipeline.sent_logical_target_rad,
        host.target_pipeline.desired_logical_target_rad,
    )
    assert np.max(np.abs(host.target_pipeline.sent_logical_target_rad - before)) <= 5.24 / 50.0


@pytest.mark.parametrize("confirmation", [False, None, 1, np.bool_(True)])
def test_ambiguous_send_faults_closed_without_committing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    confirmation: object,
) -> None:
    host, _, _ = _make_host(monkeypatch, tmp_path)
    initial_observer = host.observer.value_view.copy()
    initial_target = host.target_pipeline.previous_sent_logical_target_view.copy()
    _stage(host, 0)
    with pytest.raises(WinnerV13SendError, match="literal bool True"):
        host.complete_send(write_succeeded=confirmation)
    assert host.faulted
    assert host.confirmed_calibration_ticks == 0
    np.testing.assert_array_equal(host.observer.value_view, initial_observer)
    np.testing.assert_array_equal(
        host.target_pipeline.previous_sent_logical_target_view, initial_target
    )
    with pytest.raises(WinnerV13StateError, match="faulted closed"):
        _stage(host, 0)


def test_stale_sample_never_reaches_graph_and_faults_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    host, calibrator, _ = _make_host(monkeypatch, tmp_path)
    samples = _samples()
    stale = np.zeros(ACTION_DIM, dtype=np.bool_)
    stale[3] = True
    samples["servo_stale"] = stale
    with pytest.raises(WinnerV2ContractError, match="stale"):
        host.stage_tick(
            tick_index=0,
            logical_period_ns=CONTROL_PERIOD_NS,
            servo_sample_tick_index=0,
            imu_sample_tick_index=0,
            contacts_sample_tick_index=0,
            **samples,
        )
    assert calibrator.calls == 0
    assert host.faulted
    assert host.confirmed_calibration_ticks == 0


def test_discard_keeps_all_committed_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    host, _, _ = _make_host(monkeypatch, tmp_path)
    _stage(host, 0)
    staged = host.normalized_action_view.copy()
    assert np.count_nonzero(staged)
    host.discard_staged()
    assert host.confirmed_calibration_ticks == 0
    np.testing.assert_array_equal(host.observer.value_view, winner_v2.WINNER_V2_HOME_RAD)
    np.testing.assert_array_equal(
        host.target_pipeline.previous_sent_logical_target_view,
        winner_v2.WINNER_V2_HOME_RAD,
    )
    np.testing.assert_array_equal(
        host.assembler.last_action, np.zeros(ACTION_DIM, dtype=np.float32)
    )
    _stage(host, 0)


def test_disabled_by_default_and_not_imported_by_production(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    host, calibrator, locomotion = _make_host(monkeypatch, tmp_path, enabled=False)
    assert not host.enabled
    assert calibrator.calls == 0
    assert locomotion.calls == 0
    with pytest.raises(WinnerV13StateError, match="disabled"):
        _stage(host, 0)

    source_root = Path("src/open_duck_x5")
    forbidden = []
    for path in source_root.glob("*.py"):
        if path.name == "winner_v13_state_coherent.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(
                    alias.name == "open_duck_x5.winner_v13_state_coherent" for alias in node.names
                ):
                    forbidden.append(path.name)
            elif isinstance(node, ast.ImportFrom) and node.module in {
                ".winner_v13_state_coherent",
                "open_duck_x5.winner_v13_state_coherent",
            }:
                forbidden.append(path.name)
    assert forbidden == []


def test_frozen_predecessor_sources_are_unchanged() -> None:
    source_root = Path("src/open_duck_x5")
    for name, expected in FROZEN_SOURCE_SHA256.items():
        assert _sha256(source_root / name) == expected


def test_wrong_fit_hash_and_nonzero_phase_offset_fail_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cal_spec = _calibrator_spec()
    loco_spec = _locomotion_spec()
    calibrator_path = tmp_path / "cal.onnx"
    locomotion_path = tmp_path / "loco.onnx"
    calibrator_path.write_bytes(b"cal")
    locomotion_path.write_bytes(b"loco")
    _install_fake_ort(
        monkeypatch,
        {
            calibrator_path.name: FakeSession(cal_spec, stage="calibration"),
            locomotion_path.name: FakeSession(loco_spec, stage="locomotion"),
        },
    )
    fit = _fit(tmp_path)
    common = {
        "calibrator": GraphAsset(
            calibrator_path, cal_spec, exact_allowlist({_sha256(calibrator_path)})
        ),
        "locomotion": GraphAsset(
            locomotion_path, loco_spec, exact_allowlist({_sha256(locomotion_path)})
        ),
        "reference_table_path": _reference(tmp_path, monkeypatch),
        "enabled": True,
        "warmup_runs": 0,
    }
    with pytest.raises(WinnerV13ContractError, match="fit SHA-256"):
        WinnerV13StateCoherentTransaction(
            p30_fit=P30FitAsset(fit, frozenset({"0" * 64})),
            **common,
        )
    with pytest.raises(WinnerV2ContractError, match="requires phase_frequency"):
        WinnerV13StateCoherentTransaction(
            p30_fit=P30FitAsset(fit, frozenset({_sha256(fit)})),
            phase_frequency_factor_offset=0.1,
            **common,
        )


def test_home_return_is_structurally_absent() -> None:
    assert HOME_RETURN_TICKS == 0
    assert not hasattr(WinnerV13StateCoherentTransaction, "stage_home_return")
    assert not hasattr(WinnerV13StateCoherentTransaction, "commit_home_return")


def test_x5_optimized_transaction_is_bit_exact_to_winner_v13(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    baseline, _, _ = _make_host(monkeypatch, tmp_path / "baseline")
    optimized, _, _ = _make_host(
        monkeypatch,
        tmp_path / "optimized",
        host_type=WinnerV14X5OptimizedTransaction,
    )
    for tick in range(CALIBRATION_TICKS):
        baseline_target = _stage(baseline, tick)
        optimized_target = _stage(optimized, tick)
        np.testing.assert_array_equal(optimized.observation_view, baseline.observation_view)
        np.testing.assert_array_equal(
            optimized.normalized_action_view,
            baseline.normalized_action_view,
        )
        np.testing.assert_array_equal(optimized_target, baseline_target)
        baseline.complete_send(write_succeeded=True)
        optimized.complete_send(write_succeeded=True)
        np.testing.assert_array_equal(optimized.observer.value_view, baseline.observer.value_view)
    baseline.confirm_calibration_handoff(True)
    optimized.confirm_calibration_handoff(True)
    np.testing.assert_array_equal(optimized.calibration_context, baseline.calibration_context)
    for local_tick in range(50):
        tick = CALIBRATION_TICKS + local_tick
        baseline_target = _stage(baseline, tick, 0.074)
        optimized_target = _stage(optimized, tick, 0.074)
        np.testing.assert_array_equal(optimized.observation_view, baseline.observation_view)
        np.testing.assert_array_equal(
            optimized.normalized_action_view,
            baseline.normalized_action_view,
        )
        np.testing.assert_array_equal(optimized_target, baseline_target)
        baseline.complete_send(write_succeeded=True)
        optimized.complete_send(write_succeeded=True)
        np.testing.assert_array_equal(optimized.observer.value_view, baseline.observer.value_view)


def test_graph_host_optimized_transaction_is_bit_exact_and_switches_bound_input(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    baseline, _, _ = _make_host(
        monkeypatch,
        tmp_path / "baseline-v14",
        host_type=WinnerV14X5OptimizedTransaction,
    )
    optimized, _, _ = _make_host(
        monkeypatch,
        tmp_path / "optimized-v15",
        host_type=WinnerV15GraphHostOptimizedTransaction,
    )
    assert (
        optimized.assembler.observation
        is optimized._calibrator._trusted_bound_observation
    )
    assert np.shares_memory(
        optimized.assembler.observation,
        optimized._calibrator._observation,
    )
    assert not np.shares_memory(
        optimized.assembler.observation,
        optimized._locomotion._observation,
    )

    for tick in range(CALIBRATION_TICKS):
        baseline_target = _stage(baseline, tick)
        optimized_target = _stage(optimized, tick)
        np.testing.assert_array_equal(optimized.observation_view, baseline.observation_view)
        np.testing.assert_array_equal(
            optimized.normalized_action_view,
            baseline.normalized_action_view,
        )
        np.testing.assert_array_equal(optimized_target, baseline_target)
        baseline.complete_send(write_succeeded=True)
        optimized.complete_send(write_succeeded=True)

    baseline.confirm_calibration_handoff(True)
    optimized.confirm_calibration_handoff(True)
    assert (
        optimized.assembler.observation
        is optimized._locomotion._trusted_bound_observation
    )
    assert np.shares_memory(
        optimized.assembler.observation,
        optimized._locomotion._observation,
    )
    assert not np.shares_memory(
        optimized.assembler.observation,
        optimized._calibrator._observation,
    )
    np.testing.assert_array_equal(optimized.calibration_context, baseline.calibration_context)

    for local_tick in range(50):
        tick = CALIBRATION_TICKS + local_tick
        baseline_target = _stage(baseline, tick, 0.074)
        optimized_target = _stage(optimized, tick, 0.074)
        np.testing.assert_array_equal(optimized.observation_view, baseline.observation_view)
        np.testing.assert_array_equal(
            optimized.normalized_action_view,
            baseline.normalized_action_view,
        )
        np.testing.assert_array_equal(optimized_target, baseline_target)
        baseline.complete_send(write_succeeded=True)
        optimized.complete_send(write_succeeded=True)


@pytest.mark.parametrize("invalid_action", [float("nan"), 1.01, -1.01])
def test_graph_host_optimized_rejects_invalid_current_action_before_target_stage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    invalid_action: float,
) -> None:
    host, calibrator, _ = _make_host(
        monkeypatch,
        tmp_path,
        host_type=WinnerV15GraphHostOptimizedTransaction,
    )
    initial_target = host.target_pipeline.previous_sent_logical_target_view.copy()
    calibrator.action_override = invalid_action
    with pytest.raises(WinnerV13ContractError, match="non-finite or outside"):
        _stage(host, 0)
    assert host.faulted
    assert not host.target_pipeline.pending
    assert host.confirmed_calibration_ticks == 0
    np.testing.assert_array_equal(
        host.target_pipeline.previous_sent_logical_target_view,
        initial_target,
    )


@pytest.mark.parametrize(
    ("corruption", "expected"),
    [("previous_action", "chain diverged"), ("hidden", "non-finite h_out")],
)
def test_graph_host_optimized_validates_next_state_after_send_before_commit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    corruption: str,
    expected: str,
) -> None:
    host, calibrator, _ = _make_host(
        monkeypatch,
        tmp_path,
        host_type=WinnerV15GraphHostOptimizedTransaction,
    )
    initial_action = host._calibrator.committed_previous_action.copy()
    initial_hidden = host._calibrator.committed_hidden.copy()
    if corruption == "previous_action":
        calibrator.previous_action_out_delta = np.float32(0.01)
    else:
        calibrator.hidden_out_override = float("nan")

    _stage(host, 0)
    assert host.pending
    with pytest.raises(WinnerV13ContractError, match=expected):
        host.complete_send(write_succeeded=True)
    assert host.faulted
    assert host.confirmed_calibration_ticks == 0
    np.testing.assert_array_equal(host._calibrator.committed_previous_action, initial_action)
    np.testing.assert_array_equal(host._calibrator.committed_hidden, initial_hidden)


def test_graph_host_optimized_discard_does_not_advance_graph_or_host_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    host, _, _ = _make_host(
        monkeypatch,
        tmp_path,
        host_type=WinnerV15GraphHostOptimizedTransaction,
    )
    initial_action = host._calibrator.committed_previous_action.copy()
    initial_hidden = host._calibrator.committed_hidden.copy()
    _stage(host, 0)
    host.discard_staged()
    assert not host.pending
    assert host.confirmed_calibration_ticks == 0
    np.testing.assert_array_equal(host._calibrator.committed_previous_action, initial_action)
    np.testing.assert_array_equal(host._calibrator.committed_hidden, initial_hidden)


def test_target_optimized_transaction_is_byte_exact_across_handoff(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    baseline, _, _ = _make_host(
        monkeypatch,
        tmp_path / "baseline-v15",
        host_type=WinnerV15GraphHostOptimizedTransaction,
    )
    optimized, _, _ = _make_host(
        monkeypatch,
        tmp_path / "optimized-v16",
        host_type=WinnerV16TargetOptimizedTransaction,
    )
    sample = _samples(0.074)
    offsets = sample["soft_offsets_rad"]
    assert isinstance(offsets, np.ndarray)
    optimized.bind_soft_offsets(offsets)
    assert not offsets.flags.writeable

    for tick in range(CALIBRATION_TICKS):
        baseline_target = _stage_samples(baseline, tick, sample)
        optimized_target = _stage_samples(optimized, tick, sample)
        np.testing.assert_array_equal(optimized.observation_view, baseline.observation_view)
        np.testing.assert_array_equal(
            optimized.normalized_action_view,
            baseline.normalized_action_view,
        )
        np.testing.assert_array_equal(optimized_target, baseline_target)
        baseline.complete_send(write_succeeded=True)
        optimized.complete_send(write_succeeded=True)
    baseline.confirm_calibration_handoff(True)
    optimized.confirm_calibration_handoff(True)
    assert (
        optimized.target_pipeline.sent_logical_target_rad
        is optimized.target_pipeline.desired_logical_target_rad
    )

    for local_tick in range(50):
        tick = CALIBRATION_TICKS + local_tick
        baseline_target = _stage_samples(baseline, tick, sample)
        optimized_target = _stage_samples(optimized, tick, sample)
        np.testing.assert_array_equal(optimized.observation_view, baseline.observation_view)
        np.testing.assert_array_equal(
            optimized.normalized_action_view,
            baseline.normalized_action_view,
        )
        np.testing.assert_array_equal(optimized.logical_target_view, baseline.logical_target_view)
        np.testing.assert_array_equal(
            optimized.target_pipeline.implied_velocity_rad_s,
            baseline.target_pipeline.implied_velocity_rad_s,
        )
        np.testing.assert_array_equal(
            optimized.target_pipeline.graph_rate_excess_rad_s,
            baseline.target_pipeline.graph_rate_excess_rad_s,
        )
        np.testing.assert_array_equal(optimized_target, baseline_target)
        baseline.complete_send(write_succeeded=True)
        optimized.complete_send(write_succeeded=True)


@pytest.mark.parametrize(
    "offsets",
    [
        np.zeros(ACTION_DIM, dtype=np.float32),
        np.zeros(ACTION_DIM - 1, dtype=np.float64),
        np.concatenate(
            [np.zeros(ACTION_DIM - 1, dtype=np.float64), np.asarray([np.nan])]
        ),
    ],
)
def test_target_optimized_offset_binding_rejects_invalid_values(
    offsets: np.ndarray,
) -> None:
    pipeline = X5TrustedOffsetTargetPipeline()
    with pytest.raises(WinnerV13ContractError, match="bound soft offsets"):
        pipeline.bind_soft_offsets(offsets)


def test_target_optimized_offsets_are_immutable_and_identity_bound() -> None:
    pipeline = X5TrustedOffsetTargetPipeline()
    offsets = np.zeros(ACTION_DIM, dtype=np.float64)
    pipeline.bind_soft_offsets(offsets)
    assert not offsets.flags.writeable
    with pytest.raises(ValueError, match="read-only"):
        offsets[0] = 1.0
    pipeline.enter_locomotion_identity()
    with pytest.raises(WinnerV13ContractError, match="exact trusted"):
        pipeline.stage(
            np.zeros(ACTION_DIM, dtype=np.float32),
            offsets.copy(),
            mode="locomotion",
        )


def test_target_optimized_valid_and_violating_rate_vectors_match_predecessor() -> None:
    baseline = X5OptimizedTargetPipeline()
    optimized = X5TrustedOffsetTargetPipeline()
    offsets = np.linspace(-0.001, 0.001, ACTION_DIM, dtype=np.float64)
    optimized.bind_soft_offsets(offsets)
    optimized.enter_locomotion_identity()
    action = np.zeros(ACTION_DIM, dtype=np.float32)
    rng = np.random.default_rng(2515)
    normalized_step = winner_v2.WINNER_V2_RATE_LIMITS_RAD_S * np.float32(0.04)
    for _ in range(1_000):
        action += rng.uniform(-1.0, 1.0, ACTION_DIM).astype(np.float32) * normalized_step
        baseline_target = baseline.stage(action, offsets, mode="locomotion")
        optimized_target = optimized.stage(action, offsets, mode="locomotion")
        np.testing.assert_array_equal(
            optimized.desired_logical_target_rad,
            baseline.desired_logical_target_rad,
        )
        np.testing.assert_array_equal(
            optimized.sent_logical_target_rad,
            baseline.sent_logical_target_rad,
        )
        np.testing.assert_array_equal(
            optimized.implied_velocity_rad_s,
            baseline.implied_velocity_rad_s,
        )
        np.testing.assert_array_equal(
            optimized.graph_rate_excess_rad_s,
            baseline.graph_rate_excess_rad_s,
        )
        np.testing.assert_array_equal(optimized_target, baseline_target)
        baseline.commit_staged()
        optimized.commit_staged()

    violating = action.copy()
    violating[0] += np.float32(1.0)
    with pytest.raises(WinnerV13ContractError, match="measured-rate envelope"):
        baseline.stage(violating, offsets, mode="locomotion")
    with pytest.raises(WinnerV13ContractError, match="measured-rate envelope"):
        optimized.stage(violating, offsets, mode="locomotion")
    np.testing.assert_array_equal(
        optimized.graph_rate_excess_rad_s,
        baseline.graph_rate_excess_rad_s,
    )


def test_x5_optimized_p30_is_bit_exact_for_mixed_delay_tau_and_velocity(
    tmp_path: Path,
) -> None:
    joints: dict[str, object] = {}
    for index, name in enumerate(winner_v2.JOINT_NAMES):
        joints[name] = {
            "combined": {
                "delay_ticks": index % 4,
                "tau_s": 0.0 if index % 3 == 0 else 0.025 + index * 0.001,
                "velocity_limit_rad_s": 1.0 + index * 0.25,
            }
        }
    path = tmp_path / "mixed-p30.json"
    path.write_text(json.dumps({"primary": {"joints": joints}}), encoding="utf-8")
    asset = P30FitAsset(path, frozenset({_sha256(path)}))
    baseline = StateCoherentP30Observer(asset)
    optimized = X5OptimizedP30Observer(asset)
    rng = np.random.default_rng(251)
    for tick in range(2000):
        target = (
            winner_v2.WINNER_V2_HOME_RAD
            + rng.uniform(-0.2, 0.2, ACTION_DIM).astype(np.float32)
        )
        baseline.stage_confirmed_target(target)
        optimized.stage_confirmed_target(target)
        if tick % 17 == 0:
            baseline.discard_staged()
            optimized.discard_staged()
        else:
            baseline.commit_staged()
            optimized.commit_staged()
            np.testing.assert_array_equal(optimized.value_view, baseline.value_view)


def test_x5_optimized_target_pipeline_is_bit_exact() -> None:
    baseline = StateCoherentTargetPipeline()
    optimized = X5OptimizedTargetPipeline()
    rng = np.random.default_rng(252)
    offsets = np.linspace(-0.001, 0.001, ACTION_DIM, dtype=np.float64)
    for tick in range(2000):
        action = rng.uniform(-1.0, 1.0, ACTION_DIM).astype(np.float32)
        baseline_target = baseline.stage(action, offsets, mode="calibration")
        optimized_target = optimized.stage(action, offsets, mode="calibration")
        np.testing.assert_array_equal(optimized_target, baseline_target)
        np.testing.assert_array_equal(
            optimized.sent_logical_target_rad,
            baseline.sent_logical_target_rad,
        )
        np.testing.assert_array_equal(
            optimized.graph_rate_excess_rad_s,
            baseline.graph_rate_excess_rad_s,
        )
        if tick % 19 == 0:
            baseline.discard_staged()
            optimized.discard_staged()
        else:
            baseline.commit_staged()
            optimized.commit_staged()
