from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from open_duck_x5.policy import OnnxPolicy, PolicyContractError


@dataclass
class FakeNode:
    name: str
    shape: list[int]
    type: str = "tensor(float)"


class FakeBinding:
    def __init__(self) -> None:
        self.input_array: np.ndarray | None = None
        self.output_array: np.ndarray | None = None

    def bind_ortvalue_input(self, _name: str, value: np.ndarray) -> None:
        self.input_array = value

    def bind_ortvalue_output(self, _name: str, value: np.ndarray) -> None:
        self.output_array = value


class FakeSession:
    def __init__(
        self,
        *,
        input_type: str = "tensor(float)",
        output_type: str = "tensor(float)",
        nonfinite_call: int | None = None,
    ) -> None:
        self.input_node = FakeNode("obs", [1, 101], input_type)
        self.output_node = FakeNode("continuous_actions", [1, 14], output_type)
        self.binding = FakeBinding()
        self.calls = 0
        self.nonfinite_call = nonfinite_call
        self.session_options = None

    def get_inputs(self) -> list[FakeNode]:
        return [self.input_node]

    def get_outputs(self) -> list[FakeNode]:
        return [self.output_node]

    def io_binding(self) -> FakeBinding:
        return self.binding

    def run_with_iobinding(self, binding: FakeBinding) -> None:
        self.calls += 1
        assert binding.input_array is not None
        assert binding.output_array is not None
        binding.output_array.fill(float(self.calls))
        if self.nonfinite_call == self.calls:
            binding.output_array[0, 3] = np.nan


def install_fake_onnxruntime(
    monkeypatch: pytest.MonkeyPatch,
    session: FakeSession,
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
        path: str, *, sess_options: FakeSessionOptions, providers: list[str]
    ) -> FakeSession:
        assert Path(path).is_file()
        assert providers == ["CPUExecutionProvider"]
        session.session_options = sess_options
        return session

    module = SimpleNamespace(
        InferenceSession=make_session,
        OrtValue=FakeOrtValue,
        SessionOptions=FakeSessionOptions,
        ExecutionMode=SimpleNamespace(ORT_SEQUENTIAL="ORT_SEQUENTIAL"),
        GraphOptimizationLevel=SimpleNamespace(ORT_ENABLE_ALL="ORT_ENABLE_ALL"),
    )
    monkeypatch.setitem(sys.modules, "onnxruntime", module)


def make_model(tmp_path: Path) -> Path:
    path = tmp_path / "policy.onnx"
    path.write_bytes(b"offline fake model")
    return path


def test_policy_binds_float32_buffers_and_warms_before_first_inference(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    session = FakeSession()
    install_fake_onnxruntime(monkeypatch, session)

    policy = OnnxPolicy(make_model(tmp_path), warmup_runs=3)

    assert session.calls == 3
    assert session.binding.input_array is not None
    assert session.binding.output_array is not None
    assert session.binding.input_array.dtype == np.float32
    assert session.binding.output_array.dtype == np.float32
    assert session.session_options is not None
    assert session.session_options.execution_mode == "ORT_SEQUENTIAL"
    assert session.session_options.graph_optimization_level == "ORT_ENABLE_ALL"
    assert session.session_options.intra_op_num_threads == 1
    assert session.session_options.inter_op_num_threads == 1
    assert session.session_options.entries == {
        "session.intra_op.allow_spinning": "0",
        "session.inter_op.allow_spinning": "0",
    }
    result = policy.infer(np.zeros(101, dtype=np.float32))
    assert session.calls == 4
    np.testing.assert_array_equal(result, np.full(14, 4.0, dtype=np.float32))
    assert np.shares_memory(result, session.binding.output_array)


@pytest.mark.parametrize(
    ("input_type", "output_type"),
    [("tensor(double)", "tensor(float)"), ("tensor(float)", "tensor(double)")],
)
def test_policy_rejects_non_float32_onnx_contract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    input_type: str,
    output_type: str,
) -> None:
    session = FakeSession(input_type=input_type, output_type=output_type)
    install_fake_onnxruntime(monkeypatch, session)
    with pytest.raises(PolicyContractError, match="float32"):
        OnnxPolicy(make_model(tmp_path))


def test_policy_rejects_nonfinite_warmup_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    session = FakeSession(nonfinite_call=1)
    install_fake_onnxruntime(monkeypatch, session)
    with pytest.raises(PolicyContractError, match="warm-up.*indices.*3"):
        OnnxPolicy(make_model(tmp_path))


def test_policy_rejects_nonfinite_observation_without_running_model(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    session = FakeSession()
    install_fake_onnxruntime(monkeypatch, session)
    policy = OnnxPolicy(make_model(tmp_path), warmup_runs=1)
    observation = np.zeros(101, dtype=np.float32)
    observation[17] = np.inf

    with pytest.raises(PolicyContractError, match="observation.*indices.*17"):
        policy.infer(observation)
    assert session.calls == 1


def test_policy_rejects_nonfinite_inference_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    session = FakeSession(nonfinite_call=2)
    install_fake_onnxruntime(monkeypatch, session)
    policy = OnnxPolicy(make_model(tmp_path), warmup_runs=1)

    with pytest.raises(PolicyContractError, match="inference.*indices.*3"):
        policy.infer(np.zeros(101, dtype=np.float32))
