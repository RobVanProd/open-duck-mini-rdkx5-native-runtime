from __future__ import annotations

from pathlib import Path

import numpy as np

from .constants import ACTION_DIM, OBSERVATION_DIM

ONNX_SESSION_CONTRACT = {
    "execution_mode": "ORT_SEQUENTIAL",
    "graph_optimization_level": "ORT_ENABLE_ALL",
    "intra_op_num_threads": 1,
    "inter_op_num_threads": 1,
    "intra_op_allow_spinning": False,
    "inter_op_allow_spinning": False,
}


class PolicyContractError(RuntimeError):
    pass


class OnnxPolicy:
    """ONNX Runtime host with bound preallocated CPU input and output buffers."""

    def __init__(self, model_path: str | Path, *, warmup_runs: int = 10) -> None:
        try:
            import onnxruntime as ort
        except ImportError as exc:
            raise RuntimeError("install the 'policy' extra to use ONNX Runtime") from exc
        self.path = Path(model_path)
        if not self.path.is_file():
            raise FileNotFoundError(self.path)
        session_options = ort.SessionOptions()
        session_options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        session_options.graph_optimization_level = (
            ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        )
        session_options.intra_op_num_threads = 1
        session_options.inter_op_num_threads = 1
        session_options.add_session_config_entry(
            "session.intra_op.allow_spinning", "0"
        )
        session_options.add_session_config_entry(
            "session.inter_op.allow_spinning", "0"
        )
        self.session = ort.InferenceSession(
            str(self.path),
            sess_options=session_options,
            providers=["CPUExecutionProvider"],
        )
        inputs = self.session.get_inputs()
        outputs = self.session.get_outputs()
        if (
            len(inputs) != 1
            or inputs[0].name != "obs"
            or list(inputs[0].shape) != [1, 101]
            or inputs[0].type != "tensor(float)"
        ):
            raise PolicyContractError(
                "expected one float32 input obs [1,101], got "
                f"{[(x.name, x.shape, x.type) for x in inputs]}"
            )
        if (
            len(outputs) != 1
            or outputs[0].name != "continuous_actions"
            or list(outputs[0].shape) != [1, 14]
            or outputs[0].type != "tensor(float)"
        ):
            raise PolicyContractError(
                "expected one float32 output continuous_actions [1,14], got "
                f"{[(x.name, x.shape, x.type) for x in outputs]}"
            )
        self.input_name = inputs[0].name
        self.output_name = outputs[0].name
        self._input = np.zeros((1, OBSERVATION_DIM), dtype=np.float32)
        self._output = np.zeros((1, ACTION_DIM), dtype=np.float32)
        self._input_finite = np.ones(OBSERVATION_DIM, dtype=np.bool_)
        self._output_finite = np.ones(ACTION_DIM, dtype=np.bool_)
        self._input_ort = ort.OrtValue.ortvalue_from_numpy(self._input)
        self._output_ort = ort.OrtValue.ortvalue_from_numpy(self._output)
        self._binding = self.session.io_binding()
        self._binding.bind_ortvalue_input(self.input_name, self._input_ort)
        self._binding.bind_ortvalue_output(self.output_name, self._output_ort)
        for _ in range(max(1, int(warmup_runs))):
            self.session.run_with_iobinding(self._binding)
            self._require_finite_output("ONNX warm-up")

    @property
    def action(self) -> np.ndarray:
        return self._output[0]

    def _require_finite_output(self, operation: str) -> None:
        np.isfinite(self._output[0], out=self._output_finite)
        if not bool(self._output_finite.all()):
            bad_indices = np.flatnonzero(~self._output_finite).tolist()
            raise PolicyContractError(
                f"{operation} produced non-finite actions at indices {bad_indices}"
            )

    def infer(self, observation: np.ndarray) -> np.ndarray:
        if observation.shape != (OBSERVATION_DIM,):
            raise PolicyContractError(f"observation must have shape ({OBSERVATION_DIM},)")
        np.isfinite(observation, out=self._input_finite)
        if not bool(self._input_finite.all()):
            bad_indices = np.flatnonzero(~self._input_finite).tolist()
            raise PolicyContractError(
                f"observation contains non-finite values at indices {bad_indices}"
            )
        np.copyto(self._input[0], observation, casting="unsafe")
        self.session.run_with_iobinding(self._binding)
        self._require_finite_output("ONNX inference")
        return self._output[0]
