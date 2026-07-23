from __future__ import annotations

import ast
import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from open_duck_x5.winner_v12_two_stage import (
    ACTION_DIM,
    CALIBRATION_TICKS,
    CONTEXT_DIM,
    HIDDEN_DIM,
    OBSERVATION_DIM,
    GraphAsset,
    GraphSpec,
    TensorSpec,
    WinnerV12CommitError,
    WinnerV12ContractError,
    WinnerV12StateError,
    WinnerV12TwoStageHost,
    exact_allowlist,
)


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


@dataclass
class FakeNode:
    name: str
    shape: list[int]
    type: str = "tensor(float)"


class FakeBinding:
    def __init__(self) -> None:
        self.inputs: dict[str, np.ndarray] = {}
        self.outputs: dict[str, np.ndarray] = {}

    def bind_ortvalue_input(self, name: str, value: np.ndarray) -> None:
        self.inputs[name] = value

    def bind_ortvalue_output(self, name: str, value: np.ndarray) -> None:
        self.outputs[name] = value


class FakeSession:
    def __init__(
        self,
        spec: GraphSpec,
        *,
        stage: str,
        providers: list[str] | None = None,
        hidden_step: float = 0.002,
        action_increment: float | None = None,
        divergent_action_state: bool = False,
        nonfinite_call: int | None = None,
    ) -> None:
        self.spec = spec
        self.stage = stage
        self.providers = providers or ["CPUExecutionProvider"]
        self.hidden_step = np.float32(hidden_step)
        self.action_increment = (
            None if action_increment is None else np.float32(action_increment)
        )
        self.divergent_action_state = divergent_action_state
        self.nonfinite_call = nonfinite_call
        self.binding = FakeBinding()
        self.calls = 0
        self.requested_providers: list[str] | None = None
        self.options = None

    def get_inputs(self) -> list[FakeNode]:
        return [FakeNode(item.name, list(item.shape), item.dtype) for item in self.spec.inputs]

    def get_outputs(self) -> list[FakeNode]:
        return [FakeNode(item.name, list(item.shape), item.dtype) for item in self.spec.outputs]

    def get_providers(self) -> list[str]:
        return self.providers

    def io_binding(self) -> FakeBinding:
        return self.binding

    def run_with_iobinding(self, binding: FakeBinding) -> None:
        self.calls += 1
        previous = binding.inputs[self.spec.previous_action.name]
        hidden = binding.inputs[self.spec.hidden_in.name]
        action = binding.outputs[self.spec.action.name]
        previous_out = binding.outputs[self.spec.previous_action_out.name]
        hidden_out = binding.outputs[self.spec.hidden_out.name]
        increment = (
            self.action_increment
            if self.action_increment is not None
            else np.float32(0.001 if self.stage == "calibration" else 0.01)
        )
        np.add(previous, increment, out=action)
        np.copyto(previous_out, action)
        np.add(hidden, self.hidden_step, out=hidden_out)
        if self.divergent_action_state:
            previous_out[0, 0] += np.float32(0.1)
        if self.nonfinite_call == self.calls:
            hidden_out[0, 0] = np.float32(np.nan)


def _install_fake_ort(
    monkeypatch: pytest.MonkeyPatch,
    sessions: dict[str, FakeSession],
) -> None:
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
            self.entries: dict[str, str] = {}

        def add_session_config_entry(self, key: str, value: str) -> None:
            self.entries[key] = value

    def make_session(
        path: str,
        *,
        sess_options: FakeSessionOptions,
        providers: list[str],
    ) -> FakeSession:
        session = sessions[Path(path).name]
        session.options = sess_options
        session.requested_providers = providers
        return session

    module = SimpleNamespace(
        InferenceSession=make_session,
        OrtValue=FakeOrtValue,
        SessionOptions=FakeSessionOptions,
        ExecutionMode=SimpleNamespace(ORT_SEQUENTIAL="ORT_SEQUENTIAL"),
        GraphOptimizationLevel=SimpleNamespace(ORT_ENABLE_ALL="ORT_ENABLE_ALL"),
    )
    monkeypatch.setitem(sys.modules, "onnxruntime", module)


def _make_host(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    enabled: bool = True,
    calibrator_session: FakeSession | None = None,
    locomotion_session: FakeSession | None = None,
    calibrator_spec: GraphSpec | None = None,
    locomotion_spec: GraphSpec | None = None,
    warmup_runs: int = 0,
) -> tuple[WinnerV12TwoStageHost, FakeSession, FakeSession]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    cal_spec = calibrator_spec or _calibrator_spec()
    loco_spec = locomotion_spec or _locomotion_spec()
    cal_session = calibrator_session or FakeSession(cal_spec, stage="calibration")
    loco_session = locomotion_session or FakeSession(loco_spec, stage="locomotion")
    calibrator_path = tmp_path / "calibrator.onnx"
    locomotion_path = tmp_path / "locomotion.onnx"
    calibrator_path.write_bytes(b"caller-selected calibrator")
    locomotion_path.write_bytes(b"caller-selected locomotion")
    _install_fake_ort(
        monkeypatch,
        {
            calibrator_path.name: cal_session,
            locomotion_path.name: loco_session,
        },
    )
    host = WinnerV12TwoStageHost(
        GraphAsset(
            calibrator_path,
            cal_spec,
            exact_allowlist([_sha256(calibrator_path)]),
        ),
        GraphAsset(
            locomotion_path,
            loco_spec,
            exact_allowlist([_sha256(locomotion_path)]),
        ),
        enabled=enabled,
        warmup_runs=warmup_runs,
    )
    return host, cal_session, loco_session


def _observation(value: float = 0.0) -> np.ndarray:
    result = np.full(OBSERVATION_DIM, value, dtype=np.float32)
    return result


def _finish_calibration(host: WinnerV12TwoStageHost) -> None:
    observation = _observation()
    for _ in range(CALIBRATION_TICKS):
        host.stage_calibration(observation)
        host.commit_calibration(True)
    host.confirm_calibration_sequence(True)


def test_host_is_default_disabled_and_uses_only_prebound_cpu_sessions(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    host, calibrator, locomotion = _make_host(
        monkeypatch, tmp_path, enabled=False, warmup_runs=1
    )
    assert host.enabled is False
    assert calibrator.calls == 0
    assert locomotion.calls == 0
    with pytest.raises(WinnerV12StateError, match="disabled"):
        host.stage_calibration(_observation())
    assert calibrator.requested_providers == ["CPUExecutionProvider"]
    assert locomotion.requested_providers == ["CPUExecutionProvider"]
    assert set(calibrator.binding.inputs) == {"obs", "previous_action", "h_in"}
    assert set(calibrator.binding.outputs) == {
        "calibration_actions",
        "previous_action_out",
        "h_out",
    }
    assert set(locomotion.binding.inputs) == {
        "obs",
        "previous_action",
        "h_in",
        "calibration_context",
    }
    assert set(locomotion.binding.outputs) == {
        "continuous_actions",
        "previous_action_out",
        "h_out",
    }

    enabled_host, enabled_calibrator, enabled_locomotion = _make_host(
        monkeypatch, tmp_path / "explicitly-enabled", enabled=True, warmup_runs=1
    )
    assert enabled_host.enabled is True
    assert enabled_calibrator.calls == 1
    assert enabled_locomotion.calls == 1


def test_two_stage_host_is_not_imported_by_production_or_hardware_modules() -> None:
    source_root = Path("src/open_duck_x5")
    consumers: list[str] = []
    for path in sorted(source_root.rglob("*.py")):
        if path.name == "winner_v12_two_stage.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any(
                alias.name == "open_duck_x5.winner_v12_two_stage"
                for alias in node.names
            ):
                consumers.append(path.name)
                break
            if isinstance(node, ast.ImportFrom):
                target = "." * node.level + (node.module or "")
                if target in {
                    ".winner_v12_two_stage",
                    "open_duck_x5.winner_v12_two_stage",
                }:
                    consumers.append(path.name)
                    break
    assert consumers == []

    host_path = source_root / "winner_v12_two_stage.py"
    host_tree = ast.parse(
        host_path.read_text(encoding="utf-8"), filename=str(host_path)
    )
    imported_roots: set[str] = set()
    for node in ast.walk(host_tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])
    assert imported_roots.isdisjoint({"gpiod", "serial", "smbus2"})


def test_assets_require_exact_caller_hashes_and_exact_graph_abi(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cal_spec = _calibrator_spec()
    loco_spec = _locomotion_spec()
    calibrator_path = tmp_path / "calibrator.onnx"
    locomotion_path = tmp_path / "locomotion.onnx"
    calibrator_path.write_bytes(b"calibrator")
    locomotion_path.write_bytes(b"locomotion")
    sessions = {
        calibrator_path.name: FakeSession(cal_spec, stage="calibration"),
        locomotion_path.name: FakeSession(loco_spec, stage="locomotion"),
    }
    _install_fake_ort(monkeypatch, sessions)
    with pytest.raises(WinnerV12ContractError, match="caller allowlist"):
        WinnerV12TwoStageHost(
            GraphAsset(calibrator_path, cal_spec, frozenset({"0" * 64})),
            GraphAsset(locomotion_path, loco_spec, frozenset({_sha256(locomotion_path)})),
            enabled=True,
            warmup_runs=0,
        )

    wrong_calibrator = FakeSession(cal_spec, stage="calibration")
    wrong_calibrator.spec = GraphSpec(
        observation=TensorSpec("wrong_obs", (1, 115)),
        previous_action=cal_spec.previous_action,
        hidden_in=cal_spec.hidden_in,
        action=cal_spec.action,
        previous_action_out=cal_spec.previous_action_out,
        hidden_out=cal_spec.hidden_out,
    )
    _install_fake_ort(
        monkeypatch,
        {
            calibrator_path.name: wrong_calibrator,
            locomotion_path.name: sessions[locomotion_path.name],
        },
    )
    with pytest.raises(WinnerV12ContractError, match="ABI mismatch"):
        WinnerV12TwoStageHost(
            GraphAsset(calibrator_path, cal_spec, frozenset({_sha256(calibrator_path)})),
            GraphAsset(locomotion_path, loco_spec, frozenset({_sha256(locomotion_path)})),
            enabled=True,
            warmup_runs=0,
        )


def test_non_cpu_provider_and_invalid_caller_specs_fail_closed_at_load(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cal_spec = _calibrator_spec()
    with pytest.raises(WinnerV12ContractError, match="calibration-context"):
        cal_spec.validate_semantics(stage="locomotion")
    with pytest.raises(WinnerV12ContractError, match="shape"):
        GraphSpec(
            observation=TensorSpec("obs", (1, 114)),
            previous_action=cal_spec.previous_action,
            hidden_in=cal_spec.hidden_in,
            action=cal_spec.action,
            previous_action_out=cal_spec.previous_action_out,
            hidden_out=cal_spec.hidden_out,
        ).validate_semantics(stage="calibration")
    with pytest.raises(WinnerV12ContractError, match="reviewed provisional ABI"):
        GraphSpec(
            observation=TensorSpec("renamed_obs", (1, 115)),
            previous_action=cal_spec.previous_action,
            hidden_in=cal_spec.hidden_in,
            action=cal_spec.action,
            previous_action_out=cal_spec.previous_action_out,
            hidden_out=cal_spec.hidden_out,
        ).validate_semantics(stage="calibration")

    non_cpu = FakeSession(
        cal_spec,
        stage="calibration",
        providers=["CPUExecutionProvider", "CUDAExecutionProvider"],
    )
    with pytest.raises(WinnerV12ContractError, match="CPUExecutionProvider only"):
        _make_host(monkeypatch, tmp_path, calibrator_session=non_cpu)


@pytest.mark.parametrize(
    "observation",
    [
        np.zeros(OBSERVATION_DIM, dtype=np.float64),
        np.zeros(OBSERVATION_DIM - 1, dtype=np.float32),
        np.full(OBSERVATION_DIM, np.nan, dtype=np.float32),
    ],
)
def test_calibration_input_checks_fault_without_staging_or_commit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    observation: np.ndarray,
) -> None:
    host, _, _ = _make_host(monkeypatch, tmp_path)
    with pytest.raises(WinnerV12ContractError):
        host.stage_calibration(observation)
    assert host.faulted is True
    assert host.confirmed_calibration_ticks == 0
    assert host.handoff_complete is False


def test_calibration_stage_discard_and_commit_are_atomic(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    host, _, _ = _make_host(monkeypatch, tmp_path)
    staged = host.stage_calibration(_observation())
    assert staged.flags.writeable is False
    np.testing.assert_allclose(staged, np.full(ACTION_DIM, 0.001, dtype=np.float32))
    host.discard_calibration()
    assert host.confirmed_calibration_ticks == 0

    staged_again = host.stage_calibration(_observation())
    assert staged_again is staged
    np.testing.assert_allclose(
        staged_again, np.full(ACTION_DIM, 0.001, dtype=np.float32)
    )
    host.commit_calibration(True)
    assert host.confirmed_calibration_ticks == 1


@pytest.mark.parametrize("confirmation", [False, None, 1, np.bool_(True)])
def test_failed_or_ambiguous_calibration_commit_faults_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    confirmation: object,
) -> None:
    host, _, _ = _make_host(monkeypatch, tmp_path)
    host.stage_calibration(_observation())
    with pytest.raises(WinnerV12CommitError, match="literal bool True"):
        host.commit_calibration(confirmation)
    assert host.faulted is True
    assert host.confirmed_calibration_ticks == 0
    with pytest.raises(WinnerV12StateError, match="faulted closed"):
        host.stage_calibration(_observation())


def test_handoff_captures_immutable_context_carries_action_and_resets_hidden_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    host, _, _ = _make_host(monkeypatch, tmp_path)
    with pytest.raises(WinnerV12StateError, match="before successful"):
        host.stage_locomotion(_observation())
    with pytest.raises(WinnerV12StateError, match="exactly 250"):
        host.confirm_calibration_sequence(True)

    _finish_calibration(host)
    assert host.handoff_complete is True
    assert host.confirmed_calibration_ticks == CALIBRATION_TICKS
    expected_context = np.full(CONTEXT_DIM, 0.5, dtype=np.float32)
    np.testing.assert_allclose(host.calibration_context, expected_context, atol=2e-6)
    np.testing.assert_allclose(
        host.locomotion_previous_action,
        np.full(ACTION_DIM, 0.25, dtype=np.float32),
        atol=2e-6,
    )
    np.testing.assert_array_equal(
        host.locomotion_hidden, np.zeros(HIDDEN_DIM, dtype=np.float32)
    )
    external_context = host.calibration_context
    assert external_context.flags.writeable is False
    external_context.setflags(write=True)
    external_context.fill(-1.0)
    np.testing.assert_allclose(host.calibration_context, expected_context, atol=2e-6)
    with pytest.raises(WinnerV12StateError, match="already completed"):
        host.confirm_calibration_sequence(True)
    assert not hasattr(host, "save_context")
    assert not hasattr(host, "load_context")


def test_locomotion_stage_discard_commit_preserve_transactional_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    host, _, _ = _make_host(monkeypatch, tmp_path)
    _finish_calibration(host)
    carried = host.locomotion_previous_action.copy()
    staged = host.stage_locomotion(_observation())
    np.testing.assert_allclose(staged, carried + np.float32(0.01), atol=2e-6)
    host.discard_locomotion()
    np.testing.assert_array_equal(host.locomotion_previous_action, carried)
    np.testing.assert_array_equal(
        host.locomotion_hidden, np.zeros(HIDDEN_DIM, dtype=np.float32)
    )

    host.stage_locomotion(_observation())
    host.commit_locomotion(True)
    np.testing.assert_allclose(
        host.locomotion_previous_action, carried + np.float32(0.01), atol=2e-6
    )
    np.testing.assert_allclose(
        host.locomotion_hidden,
        np.full(HIDDEN_DIM, 0.002, dtype=np.float32),
        atol=2e-6,
    )


def test_nonfinite_stage_output_and_out_of_range_context_never_arm_locomotion(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cal_spec = _calibrator_spec()
    nonfinite = FakeSession(
        cal_spec,
        stage="calibration",
        nonfinite_call=1,
    )
    host, _, _ = _make_host(
        monkeypatch, tmp_path / "nonfinite", calibrator_session=nonfinite
    )
    with pytest.raises(WinnerV12ContractError, match="non-finite h_out"):
        host.stage_calibration(_observation())
    assert host.faulted is True
    assert host.handoff_complete is False

    out_of_range = FakeSession(
        cal_spec,
        stage="calibration",
        hidden_step=0.005,
    )
    second, _, _ = _make_host(
        monkeypatch, tmp_path / "out-of-range", calibrator_session=out_of_range
    )
    for _ in range(CALIBRATION_TICKS):
        second.stage_calibration(_observation())
        second.commit_calibration(True)
    with pytest.raises(WinnerV12ContractError, match=r"outside \[-1, 1\]"):
        second.confirm_calibration_sequence(True)
    assert second.faulted is True
    assert second.handoff_complete is False
    with pytest.raises(WinnerV12StateError, match="faulted closed"):
        second.stage_locomotion(_observation())


def test_graph_actions_are_never_deadbanded_or_clipped_by_the_host(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    host, _, _ = _make_host(monkeypatch, tmp_path / "delegated")
    action = host.stage_calibration(_observation())
    np.testing.assert_array_equal(
        action, np.full(ACTION_DIM, 0.001, dtype=np.float32)
    )
    host.discard_calibration()

    cal_spec = _calibrator_spec()
    out_of_range = FakeSession(
        cal_spec,
        stage="calibration",
        action_increment=1.5,
    )
    rejected, _, _ = _make_host(
        monkeypatch,
        tmp_path / "out-of-range-action",
        calibrator_session=out_of_range,
    )
    with pytest.raises(WinnerV12ContractError, match=r"action is outside \[-1, 1\]"):
        rejected.stage_calibration(_observation())
    assert rejected.faulted is True
    assert rejected.confirmed_calibration_ticks == 0


def test_divergent_action_state_and_ambiguous_locomotion_commit_fail_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    loco_spec = _locomotion_spec()
    divergent = FakeSession(
        loco_spec,
        stage="locomotion",
        divergent_action_state=True,
    )
    host, _, _ = _make_host(
        monkeypatch, tmp_path / "divergent", locomotion_session=divergent
    )
    _finish_calibration(host)
    with pytest.raises(WinnerV12ContractError, match="chain diverged"):
        host.stage_locomotion(_observation())
    assert host.faulted is True

    second, _, _ = _make_host(monkeypatch, tmp_path / "ambiguous")
    _finish_calibration(second)
    second.stage_locomotion(_observation())
    with pytest.raises(WinnerV12CommitError, match="literal bool True"):
        second.commit_locomotion(None)
    assert second.faulted is True
