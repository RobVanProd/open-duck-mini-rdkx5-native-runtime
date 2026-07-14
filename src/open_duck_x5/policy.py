from __future__ import annotations

from pathlib import Path

import numpy as np

from .constants import ACTION_DIM, OBSERVATION_DIM


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
        self.session = ort.InferenceSession(str(self.path), providers=["CPUExecutionProvider"])
        inputs = self.session.get_inputs()
        outputs = self.session.get_outputs()
        if len(inputs) != 1 or inputs[0].name != "obs" or list(inputs[0].shape) != [1, 101]:
            raise PolicyContractError(
                f"expected one input obs [1,101], got {[(x.name, x.shape) for x in inputs]}"
            )
        if (
            len(outputs) != 1
            or outputs[0].name != "continuous_actions"
            or list(outputs[0].shape) != [1, 14]
        ):
            raise PolicyContractError(
                "expected one output continuous_actions [1,14], got "
                f"{[(x.name, x.shape) for x in outputs]}"
            )
        self.input_name = inputs[0].name
        self.output_name = outputs[0].name
        self._input = np.zeros((1, OBSERVATION_DIM), dtype=np.float32)
        self._output = np.zeros((1, ACTION_DIM), dtype=np.float32)
        self._input_ort = ort.OrtValue.ortvalue_from_numpy(self._input)
        self._output_ort = ort.OrtValue.ortvalue_from_numpy(self._output)
        self._binding = self.session.io_binding()
        self._binding.bind_ortvalue_input(self.input_name, self._input_ort)
        self._binding.bind_ortvalue_output(self.output_name, self._output_ort)
        for _ in range(max(1, int(warmup_runs))):
            self.session.run_with_iobinding(self._binding)

    @property
    def action(self) -> np.ndarray:
        return self._output[0]

    def infer(self, observation: np.ndarray) -> np.ndarray:
        if observation.shape != (OBSERVATION_DIM,):
            raise PolicyContractError(f"observation must have shape ({OBSERVATION_DIM},)")
        np.copyto(self._input[0], observation, casting="unsafe")
        self.session.run_with_iobinding(self._binding)
        return self._output[0]
