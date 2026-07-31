"""Default-disabled state-coherent host for the T250 115-D policy handoff.

This module has no production-runtime, serial, GPIO, I2C, torque, or CLI
integration.  It is a versioned offline contract beside, not a replacement for,
the frozen 101-D runtime and the older Winner-v12 reset-aligned experiment.

Every tick is transactional.  Graph recurrence, action history, sent-target
history, the fixed-P30 observer, and locomotion phase advance only after the
caller confirms a successful external send with the literal bool ``True``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .constants import (
    ACTION_DIM,
    ACTION_SCALE_RAD,
    CONTROL_FREQUENCY_HZ,
    CONTROL_PERIOD_NS,
    HOME_RAD,
    LEGACY_TARGET_RATE_LIMIT_RAD_S,
)
from .winner_v2 import (
    WINNER_V2_HOME_RAD,
    WINNER_V2_RATE_LIMITS_RAD_S,
    P30BridgeObserver,
    ProjectedReferenceTable,
    WinnerV2ContractError,
    WinnerV2ObservationAssembler,
    WinnerV2PhaseClock,
    _params_from_fit,
    _require_vector,
    sha256_file,
)

CONTRACT_ID = "open-duck-mini.t250.winner-v13.state-coherent.115x14.v1"
OBSERVATION_DIM = 115
HIDDEN_DIM = 64
CONTEXT_DIM = 64
CALIBRATION_TICKS = 250
HOME_RETURN_TICKS = 0
_FLOAT_TENSOR = "tensor(float)"
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_CALIBRATOR_INPUT_NAMES = ("obs", "previous_action", "h_in")
_CALIBRATOR_OUTPUT_NAMES = (
    "calibration_actions",
    "previous_action_out",
    "h_out",
)
_LOCOMOTION_INPUT_NAMES = (
    "obs",
    "previous_action",
    "h_in",
    "calibration_context",
)
_LOCOMOTION_OUTPUT_NAMES = (
    "continuous_actions",
    "previous_action_out",
    "h_out",
)
CALIBRATION_COMMAND = np.zeros(7, dtype=np.float64)
CALIBRATION_PHASE = np.asarray([1.0, 0.0], dtype=np.float32)
CALIBRATION_COMMAND.setflags(write=False)
CALIBRATION_PHASE.setflags(write=False)


class WinnerV13ContractError(RuntimeError):
    """The T250 state-coherent runtime contract was violated."""


class WinnerV13StateError(WinnerV13ContractError):
    """A versioned runtime transition was attempted out of order."""


class WinnerV13SendError(WinnerV13ContractError):
    """A staged target did not receive an unambiguous send confirmation."""


@dataclass(frozen=True)
class TensorSpec:
    """One exact tensor declaration for a T250 graph asset."""

    name: str
    shape: tuple[int, ...]
    dtype: str = _FLOAT_TENSOR

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise WinnerV13ContractError("tensor name must be a non-empty string")
        if (
            not isinstance(self.shape, tuple)
            or not self.shape
            or any(type(value) is not int or value <= 0 for value in self.shape)
        ):
            raise WinnerV13ContractError(f"{self.name} requires a fixed positive-integer shape")
        if self.dtype != _FLOAT_TENSOR:
            raise WinnerV13ContractError(f"{self.name} must use {_FLOAT_TENSOR}, got {self.dtype}")


@dataclass(frozen=True)
class GraphSpec:
    """Exact T250 calibrator or locomotion graph ABI."""

    observation: TensorSpec
    previous_action: TensorSpec
    hidden_in: TensorSpec
    action: TensorSpec
    previous_action_out: TensorSpec
    hidden_out: TensorSpec
    calibration_context: TensorSpec | None = None

    @property
    def inputs(self) -> tuple[TensorSpec, ...]:
        values = (self.observation, self.previous_action, self.hidden_in)
        if self.calibration_context is not None:
            values += (self.calibration_context,)
        return values

    @property
    def outputs(self) -> tuple[TensorSpec, ...]:
        return (self.action, self.previous_action_out, self.hidden_out)

    def validate_semantics(self, *, stage: str) -> None:
        if stage not in {"calibration", "locomotion"}:
            raise WinnerV13ContractError(f"unknown graph stage: {stage}")
        expected_context = stage == "locomotion"
        if (self.calibration_context is not None) is not expected_context:
            requirement = "requires" if expected_context else "must not have"
            raise WinnerV13ContractError(f"{stage} graph {requirement} a calibration-context input")
        expected_inputs = [
            (self.observation, (1, OBSERVATION_DIM)),
            (self.previous_action, (1, ACTION_DIM)),
            (self.hidden_in, (1, HIDDEN_DIM)),
        ]
        if self.calibration_context is not None:
            expected_inputs.append((self.calibration_context, (1, CONTEXT_DIM)))
        expected_outputs = [
            (self.action, (1, ACTION_DIM)),
            (self.previous_action_out, (1, ACTION_DIM)),
            (self.hidden_out, (1, HIDDEN_DIM)),
        ]
        for tensor, expected_shape in (*expected_inputs, *expected_outputs):
            if tensor.shape != expected_shape:
                raise WinnerV13ContractError(
                    f"{stage} role {tensor.name} must have shape {expected_shape}, "
                    f"got {tensor.shape}"
                )
        input_names = tuple(tensor.name for tensor in self.inputs)
        output_names = tuple(tensor.name for tensor in self.outputs)
        expected_names = (
            (_CALIBRATOR_INPUT_NAMES, _CALIBRATOR_OUTPUT_NAMES)
            if stage == "calibration"
            else (_LOCOMOTION_INPUT_NAMES, _LOCOMOTION_OUTPUT_NAMES)
        )
        if (input_names, output_names) != expected_names:
            raise WinnerV13ContractError(
                f"{stage} graph names differ from the frozen T250 ABI: "
                f"inputs={input_names}, outputs={output_names}"
            )


def exact_allowlist(values: Iterable[str]) -> frozenset[str]:
    """Validate and copy a non-empty exact SHA-256 allowlist."""

    if isinstance(values, str):
        raise WinnerV13ContractError("SHA-256 allowlist must not be a string")
    try:
        hashes = frozenset(values)
    except TypeError as exc:
        raise WinnerV13ContractError("SHA-256 allowlist is not iterable") from exc
    if not hashes:
        raise WinnerV13ContractError("SHA-256 allowlist must be non-empty")
    if any(not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None for value in hashes):
        raise WinnerV13ContractError(
            "SHA-256 allowlist entries must be exact lowercase 64-hex strings"
        )
    return hashes


@dataclass(frozen=True)
class GraphAsset:
    """One caller-selected T250 ONNX graph and its exact accepted bytes."""

    path: str | Path
    spec: GraphSpec
    allowed_sha256: frozenset[str]

    def __post_init__(self) -> None:
        if not isinstance(self.spec, GraphSpec):
            raise WinnerV13ContractError("graph asset requires an exact GraphSpec")
        object.__setattr__(
            self,
            "allowed_sha256",
            exact_allowlist(self.allowed_sha256),
        )


def _exact_float32_vector(value: np.ndarray, size: int, label: str) -> np.ndarray:
    if not isinstance(value, np.ndarray):
        raise WinnerV13ContractError(f"{label} must be a numpy.ndarray")
    if value.shape != (size,):
        raise WinnerV13ContractError(f"{label} must have shape ({size},), got {value.shape}")
    if value.dtype != np.dtype(np.float32):
        raise WinnerV13ContractError(f"{label} must have dtype float32, got {value.dtype}")
    if not bool(np.isfinite(value).all()):
        indices = np.flatnonzero(~np.isfinite(value)).tolist()
        raise WinnerV13ContractError(f"{label} contains non-finite values at indices {indices}")
    return value


def _require_unit_range(value: np.ndarray, label: str) -> None:
    if bool(np.any(value < -1.0)) or bool(np.any(value > 1.0)):
        raise WinnerV13ContractError(
            f"{label} is outside [-1, 1]: min={float(np.min(value))}, max={float(np.max(value))}"
        )


class _StateCoherentGraphSession:
    """One preallocated, staged, CPU-only T250 ONNX session."""

    def __init__(
        self,
        asset: GraphAsset,
        *,
        stage: str,
        warmup_runs: int,
    ) -> None:
        if type(warmup_runs) is not int or warmup_runs < 0:
            raise WinnerV13ContractError("warmup_runs must be a non-negative integer")
        asset.spec.validate_semantics(stage=stage)
        self.stage_name = stage
        self.spec = asset.spec
        self.path = Path(asset.path).resolve()
        if not self.path.is_file():
            raise FileNotFoundError(self.path)
        self.sha256 = sha256_file(self.path)
        if self.sha256 not in asset.allowed_sha256:
            raise WinnerV13ContractError(
                f"{stage} graph SHA-256 is not in the caller allowlist: {self.sha256}"
            )
        try:
            import onnxruntime as ort
        except ImportError as exc:
            raise RuntimeError("install the 'policy' extra to use ONNX Runtime") from exc

        options = ort.SessionOptions()
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        options.add_session_config_entry("session.intra_op.allow_spinning", "0")
        options.add_session_config_entry("session.inter_op.allow_spinning", "0")
        self.session = ort.InferenceSession(
            str(self.path),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        providers = self.session.get_providers()
        if providers != ["CPUExecutionProvider"]:
            raise WinnerV13ContractError(
                f"{stage} graph requires CPUExecutionProvider only, got {providers}"
            )
        actual_inputs = tuple(
            (node.name, tuple(node.shape), node.type) for node in self.session.get_inputs()
        )
        actual_outputs = tuple(
            (node.name, tuple(node.shape), node.type) for node in self.session.get_outputs()
        )
        expected_inputs = tuple(
            (tensor.name, tensor.shape, tensor.dtype) for tensor in self.spec.inputs
        )
        expected_outputs = tuple(
            (tensor.name, tensor.shape, tensor.dtype) for tensor in self.spec.outputs
        )
        if actual_inputs != expected_inputs or actual_outputs != expected_outputs:
            raise WinnerV13ContractError(
                f"{stage} ONNX ABI mismatch: inputs={actual_inputs}, outputs={actual_outputs}"
            )

        self._observation = np.zeros((1, OBSERVATION_DIM), dtype=np.float32)
        self._previous_action = np.zeros((1, ACTION_DIM), dtype=np.float32)
        self._hidden_in = np.zeros((1, HIDDEN_DIM), dtype=np.float32)
        self._context = (
            np.zeros((1, CONTEXT_DIM), dtype=np.float32)
            if self.spec.calibration_context is not None
            else None
        )
        self._action = np.zeros((1, ACTION_DIM), dtype=np.float32)
        self._previous_action_out = np.zeros((1, ACTION_DIM), dtype=np.float32)
        self._hidden_out = np.zeros((1, HIDDEN_DIM), dtype=np.float32)
        self._observation_finite = np.ones(OBSERVATION_DIM, dtype=np.bool_)
        self._action_finite = np.ones((1, ACTION_DIM), dtype=np.bool_)
        self._previous_action_out_finite = np.ones((1, ACTION_DIM), dtype=np.bool_)
        self._hidden_out_finite = np.ones((1, HIDDEN_DIM), dtype=np.bool_)
        self._action_range_bad = np.zeros((1, ACTION_DIM), dtype=np.bool_)
        self._staged_action_view = self._action[0].view()
        self._staged_action_view.setflags(write=False)
        self._pending = False
        self._handoff_initialized = False

        self._binding = self.session.io_binding()
        self._ort_values: list[object] = []
        self._bind_input(ort, self.spec.observation.name, self._observation)
        self._bind_input(ort, self.spec.previous_action.name, self._previous_action)
        self._bind_input(ort, self.spec.hidden_in.name, self._hidden_in)
        if self.spec.calibration_context is not None:
            assert self._context is not None
            self._bind_input(ort, self.spec.calibration_context.name, self._context)
        self._bind_output(ort, self.spec.action.name, self._action)
        self._bind_output(
            ort,
            self.spec.previous_action_out.name,
            self._previous_action_out,
        )
        self._bind_output(ort, self.spec.hidden_out.name, self._hidden_out)

        for _ in range(warmup_runs):
            self.session.run_with_iobinding(self._binding)
            self._validate_staged_outputs("ONNX warm-up")
        self._scrub_staged()

    def _bind_input(self, ort: object, name: str, array: np.ndarray) -> None:
        value = ort.OrtValue.ortvalue_from_numpy(array)
        self._ort_values.append(value)
        self._binding.bind_ortvalue_input(name, value)

    def _bind_output(self, ort: object, name: str, array: np.ndarray) -> None:
        value = ort.OrtValue.ortvalue_from_numpy(array)
        self._ort_values.append(value)
        self._binding.bind_ortvalue_output(name, value)

    @property
    def committed_previous_action(self) -> np.ndarray:
        return self._previous_action[0]

    @property
    def committed_hidden(self) -> np.ndarray:
        return self._hidden_in[0]

    def _scrub_staged(self) -> None:
        self._action.fill(0.0)
        self._previous_action_out.fill(0.0)
        self._hidden_out.fill(0.0)

    def _validate_staged_outputs(self, operation: str) -> None:
        arrays = (
            ("action", self._action, self._action_finite),
            (
                "previous_action_out",
                self._previous_action_out,
                self._previous_action_out_finite,
            ),
            ("h_out", self._hidden_out, self._hidden_out_finite),
        )
        for label, value, finite in arrays:
            np.isfinite(value, out=finite)
            if not bool(finite.all()):
                raise WinnerV13ContractError(f"{operation} produced non-finite {label}")
        for label, value in (
            ("action", self._action),
            ("previous_action_out", self._previous_action_out),
        ):
            np.less(value, -1.0, out=self._action_range_bad)
            below = bool(self._action_range_bad.any())
            np.greater(value, 1.0, out=self._action_range_bad)
            if below or bool(self._action_range_bad.any()):
                raise WinnerV13ContractError(
                    f"{operation} {label} is outside [-1, 1]: "
                    f"min={float(np.min(value))}, max={float(np.max(value))}"
                )
        if not bool(np.array_equal(self._action, self._previous_action_out)):
            error = float(np.max(np.abs(self._action - self._previous_action_out)))
            raise WinnerV13ContractError(
                f"{operation} action/previous-action chain diverged by {error}"
            )

    def stage(self, observation: np.ndarray) -> np.ndarray:
        if self._pending:
            raise WinnerV13StateError(f"{self.stage_name} graph already has staged state")
        observation = _exact_float32_vector(
            observation,
            OBSERVATION_DIM,
            f"{self.stage_name} observation",
        )
        return self.stage_prevalidated(observation)

    def stage_prevalidated(self, observation: np.ndarray) -> np.ndarray:
        """Stage a caller-validated exact observation without a second finite scan."""

        if self._pending:
            raise WinnerV13StateError(f"{self.stage_name} graph already has staged state")
        if not isinstance(observation, np.ndarray):
            raise WinnerV13ContractError(
                f"{self.stage_name} prevalidated observation must be a numpy.ndarray"
            )
        if observation.shape != (OBSERVATION_DIM,) or observation.dtype != np.dtype(np.float32):
            raise WinnerV13ContractError(
                f"{self.stage_name} prevalidated observation must be float32 shape "
                f"({OBSERVATION_DIM},), got {observation.dtype} {observation.shape}"
            )
        np.copyto(self._observation[0], observation)
        self._scrub_staged()
        try:
            self.session.run_with_iobinding(self._binding)
            self._validate_staged_outputs(f"{self.stage_name} inference")
        except Exception:
            self._scrub_staged()
            self._pending = False
            raise
        self._pending = True
        return self._staged_action_view

    def stage_prevalidated_fast(self, observation: np.ndarray) -> np.ndarray:
        """Stage an exact trusted observation with the minimal equivalent checks."""

        if self._pending:
            raise WinnerV13StateError(f"{self.stage_name} graph already has staged state")
        if (
            not isinstance(observation, np.ndarray)
            or observation.shape != (OBSERVATION_DIM,)
            or observation.dtype != np.dtype(np.float32)
        ):
            raise WinnerV13ContractError(
                f"{self.stage_name} trusted observation must be float32 shape "
                f"({OBSERVATION_DIM},)"
            )
        np.copyto(self._observation[0], observation)
        self._scrub_staged()
        try:
            self.session.run_with_iobinding(self._binding)
            if not bool(np.array_equal(self._action, self._previous_action_out)):
                error = float(np.max(np.abs(self._action - self._previous_action_out)))
                raise WinnerV13ContractError(
                    f"{self.stage_name} inference action/previous-action chain "
                    f"diverged by {error}"
                )
            np.isfinite(self._action, out=self._action_finite)
            np.isfinite(self._hidden_out, out=self._hidden_out_finite)
            if not bool(self._action_finite.all()) or not bool(self._hidden_out_finite.all()):
                raise WinnerV13ContractError(
                    f"{self.stage_name} inference produced a non-finite output"
                )
            np.less(self._action, -1.0, out=self._action_range_bad)
            below = bool(self._action_range_bad.any())
            np.greater(self._action, 1.0, out=self._action_range_bad)
            if below or bool(self._action_range_bad.any()):
                raise WinnerV13ContractError(
                    f"{self.stage_name} inference action is outside [-1, 1]: "
                    f"min={float(np.min(self._action))}, max={float(np.max(self._action))}"
                )
        except Exception:
            self._scrub_staged()
            self._pending = False
            raise
        self._pending = True
        return self._staged_action_view

    def commit(self, confirmed_success: object) -> None:
        if not self._pending:
            raise WinnerV13StateError(f"{self.stage_name} graph has no staged state")
        if confirmed_success is not True:
            self.discard()
            raise WinnerV13SendError(f"{self.stage_name} commit requires the literal bool True")
        self._validate_staged_outputs(f"{self.stage_name} commit")
        np.copyto(self._previous_action, self._previous_action_out)
        np.copyto(self._hidden_in, self._hidden_out)
        self._pending = False
        self._scrub_staged()

    def discard(self) -> None:
        self._pending = False
        self._scrub_staged()

    def initialize_locomotion_handoff(
        self,
        previous_action: np.ndarray,
        context: np.ndarray,
    ) -> None:
        if self.stage_name != "locomotion" or self._context is None:
            raise WinnerV13StateError("handoff target is not a locomotion graph")
        if self._handoff_initialized:
            raise WinnerV13StateError("locomotion handoff is already initialized")
        if self._pending:
            raise WinnerV13StateError("locomotion graph has staged state during handoff")
        previous_action = _exact_float32_vector(
            previous_action,
            ACTION_DIM,
            "handoff previous_action",
        )
        context = _exact_float32_vector(
            context,
            CONTEXT_DIM,
            "calibration context",
        )
        _require_unit_range(context, "calibration context")
        np.copyto(self._previous_action[0], previous_action)
        self._hidden_in.fill(0.0)
        np.copyto(self._context[0], context)
        self._context.setflags(write=False)
        self._handoff_initialized = True


@dataclass(frozen=True)
class P30FitAsset:
    """Caller-selected P30 observer fit with an exact SHA-256 allowlist."""

    path: str | Path
    allowed_sha256: frozenset[str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "allowed_sha256", exact_allowlist(self.allowed_sha256))


class StateCoherentP30Observer(P30BridgeObserver):
    """P30 observer implementation with a handoff-selected hash allowlist."""

    def __init__(self, asset: P30FitAsset) -> None:
        self.path = Path(asset.path).resolve()
        if not self.path.is_file():
            raise FileNotFoundError(self.path)
        self.sha256 = sha256_file(self.path)
        if self.sha256 not in asset.allowed_sha256:
            raise WinnerV13ContractError(
                f"P30 fit SHA-256 is not in the caller allowlist: {self.sha256}"
            )
        with self.path.open(encoding="utf-8") as handle:
            fit = json.load(handle)
        if not isinstance(fit, dict):
            raise WinnerV13ContractError("P30 fit root must be an object")
        try:
            self.params = _params_from_fit(fit)
        except WinnerV2ContractError as exc:
            raise WinnerV13ContractError(str(exc)) from exc
        self._value = WINNER_V2_HOME_RAD.astype(np.float64)
        self._staged_value = self._value.copy()
        self._queues = [
            np.full(param.delay_ticks + 1, self._value[index], dtype=np.float64)
            for index, param in enumerate(self.params)
        ]
        self._staged_queues = [queue.copy() for queue in self._queues]
        self._staged_target = self._value.copy()
        self._target_finite = np.ones(ACTION_DIM, dtype=np.bool_)
        self._value_finite = np.ones(ACTION_DIM, dtype=np.bool_)
        self._pending = False


class StateCoherentTargetPipeline:
    """Shared calibration/locomotion target state with exact 5.24-rad/s slew."""

    def __init__(self) -> None:
        self.desired_logical_target_rad = WINNER_V2_HOME_RAD.copy()
        self.sent_logical_target_rad = WINNER_V2_HOME_RAD.copy()
        self.physical_target_rad = HOME_RAD.copy()
        self.implied_velocity_rad_s = np.zeros(ACTION_DIM, dtype=np.float64)
        self.graph_rate_excess_rad_s = np.zeros(ACTION_DIM, dtype=np.float64)
        self._previous_sent_logical_target_rad = WINNER_V2_HOME_RAD.copy()
        self._lower_bound = np.zeros(ACTION_DIM, dtype=np.float32)
        self._upper_bound = np.zeros(ACTION_DIM, dtype=np.float32)
        self._absolute_velocity_rad_s = np.zeros(ACTION_DIM, dtype=np.float64)
        self._pending = False
        self._staged_mode: str | None = None

    @property
    def previous_sent_logical_target_view(self) -> np.ndarray:
        return self._previous_sent_logical_target_rad

    @property
    def pending(self) -> bool:
        return self._pending

    def stage(
        self,
        action: np.ndarray,
        soft_offsets_rad: np.ndarray,
        *,
        mode: str,
    ) -> np.ndarray:
        if self._pending:
            raise WinnerV13StateError("target pipeline already has a staged target")
        if mode not in {"calibration", "locomotion"}:
            raise WinnerV13ContractError(f"unknown target-pipeline mode: {mode}")
        try:
            normalized = _require_vector(action, ACTION_DIM, "action", dtype=np.float32)
            offsets = _require_vector(
                soft_offsets_rad,
                ACTION_DIM,
                "soft_offsets_rad",
                dtype=np.float64,
            )
        except WinnerV2ContractError as exc:
            raise WinnerV13ContractError(str(exc)) from exc
        np.multiply(
            normalized,
            np.float32(ACTION_SCALE_RAD),
            out=self.desired_logical_target_rad,
        )
        np.add(
            self.desired_logical_target_rad,
            WINNER_V2_HOME_RAD,
            out=self.desired_logical_target_rad,
        )
        max_step = np.float32(LEGACY_TARGET_RATE_LIMIT_RAD_S / CONTROL_FREQUENCY_HZ)
        np.subtract(
            self._previous_sent_logical_target_rad,
            max_step,
            out=self._lower_bound,
        )
        np.add(
            self._previous_sent_logical_target_rad,
            max_step,
            out=self._upper_bound,
        )
        np.clip(
            self.desired_logical_target_rad,
            self._lower_bound,
            self._upper_bound,
            out=self.sent_logical_target_rad,
        )
        if mode == "locomotion" and not bool(
            np.array_equal(self.sent_logical_target_rad, self.desired_logical_target_rad)
        ):
            error = np.abs(
                self.sent_logical_target_rad.astype(np.float64)
                - self.desired_logical_target_rad.astype(np.float64)
            )
            indices = np.flatnonzero(error > 0.0).tolist()
            raise WinnerV13ContractError(
                "locomotion graph failed inherited 5.24 rad/s identity at joints "
                f"{indices}; max change {float(error.max())} rad"
            )
        np.subtract(
            self.sent_logical_target_rad,
            self._previous_sent_logical_target_rad,
            out=self.implied_velocity_rad_s,
        )
        self.implied_velocity_rad_s *= CONTROL_FREQUENCY_HZ
        np.abs(self.implied_velocity_rad_s, out=self._absolute_velocity_rad_s)
        np.subtract(
            self._absolute_velocity_rad_s,
            WINNER_V2_RATE_LIMITS_RAD_S,
            out=self.graph_rate_excess_rad_s,
        )
        np.maximum(
            self.graph_rate_excess_rad_s,
            0.0,
            out=self.graph_rate_excess_rad_s,
        )
        self.graph_rate_excess_rad_s[self.graph_rate_excess_rad_s <= 1.0e-5] = 0.0
        if mode == "locomotion" and bool(np.any(self.graph_rate_excess_rad_s > 0.0)):
            indices = np.flatnonzero(self.graph_rate_excess_rad_s > 0.0).tolist()
            raise WinnerV13ContractError(
                f"locomotion graph measured-rate envelope exceeded at joints {indices}"
            )
        np.add(
            self.sent_logical_target_rad,
            offsets,
            out=self.physical_target_rad,
        )
        self._pending = True
        self._staged_mode = mode
        return self.physical_target_rad

    def commit_staged(self) -> None:
        if not self._pending:
            raise WinnerV13StateError("target pipeline has no staged target")
        np.copyto(
            self._previous_sent_logical_target_rad,
            self.sent_logical_target_rad,
        )
        self._pending = False
        self._staged_mode = None

    def discard_staged(self) -> None:
        self._pending = False
        self._staged_mode = None


class WinnerV13StateCoherentTransaction:
    """All-or-nothing 250-tick calibration and immediate locomotion host."""

    def __init__(
        self,
        *,
        calibrator: GraphAsset,
        locomotion: GraphAsset,
        p30_fit: P30FitAsset,
        reference_table_path: str | Path,
        enabled: bool = False,
        warmup_runs: int = 1,
        phase_frequency_factor_offset: float = 0.0,
    ) -> None:
        if type(enabled) is not bool:
            raise WinnerV13ContractError("enabled must be a literal bool")
        self._enabled = enabled
        effective_warmup = warmup_runs if enabled else 0
        self._calibrator = _StateCoherentGraphSession(
            calibrator,
            stage="calibration",
            warmup_runs=effective_warmup,
        )
        self._locomotion = _StateCoherentGraphSession(
            locomotion,
            stage="locomotion",
            warmup_runs=effective_warmup,
        )
        self.reference = ProjectedReferenceTable(reference_table_path)
        self.observer = StateCoherentP30Observer(p30_fit)
        self.assembler = WinnerV2ObservationAssembler(self.reference)
        self.phase = WinnerV2PhaseClock(frequency_factor_offset=phase_frequency_factor_offset)
        self.target_pipeline = StateCoherentTargetPipeline()
        self._calibration_context = np.zeros(CONTEXT_DIM, dtype=np.float32)
        self._calibration_action_history = np.zeros((3, ACTION_DIM), dtype=np.float32)
        self._staged_action = np.zeros(ACTION_DIM, dtype=np.float32)
        self._staged_stage: str | None = None
        self._staged_tick: int | None = None
        self._confirmed_calibration_ticks = 0
        self._confirmed_locomotion_ticks = 0
        self._handoff_complete = False
        self._first_locomotion_observation = True
        self._faulted = False
        self._fault_reason: str | None = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def pending(self) -> bool:
        return self._staged_stage is not None

    @property
    def faulted(self) -> bool:
        return self._faulted

    @property
    def fault_reason(self) -> str | None:
        return self._fault_reason

    @property
    def handoff_complete(self) -> bool:
        return self._handoff_complete

    @property
    def confirmed_calibration_ticks(self) -> int:
        return self._confirmed_calibration_ticks

    @property
    def confirmed_home_return_ticks(self) -> int:
        return HOME_RETURN_TICKS

    @property
    def confirmed_locomotion_ticks(self) -> int:
        return self._confirmed_locomotion_ticks

    @property
    def committed_ticks(self) -> int:
        return self._confirmed_calibration_ticks + self._confirmed_locomotion_ticks

    @property
    def observation_view(self) -> np.ndarray:
        return self.assembler.observation

    @property
    def normalized_action_view(self) -> np.ndarray:
        return self._staged_action

    @property
    def logical_target_view(self) -> np.ndarray:
        return self.target_pipeline.sent_logical_target_rad

    @property
    def physical_target_view(self) -> np.ndarray:
        return self.target_pipeline.physical_target_rad

    @property
    def calibration_context(self) -> np.ndarray:
        if not self._handoff_complete:
            raise WinnerV13StateError("calibration context is not available")
        value = self._calibration_context.copy()
        value.setflags(write=False)
        return value

    @property
    def locomotion_previous_action(self) -> np.ndarray:
        if not self._handoff_complete:
            raise WinnerV13StateError("locomotion handoff is incomplete")
        value = self._locomotion.committed_previous_action.copy()
        value.setflags(write=False)
        return value

    @property
    def locomotion_hidden(self) -> np.ndarray:
        if not self._handoff_complete:
            raise WinnerV13StateError("locomotion handoff is incomplete")
        value = self._locomotion.committed_hidden.copy()
        value.setflags(write=False)
        return value

    def _require_active(self) -> None:
        if not self._enabled:
            raise WinnerV13StateError("Winner-v13 state-coherent host is disabled")
        if self._faulted:
            raise WinnerV13StateError(
                f"Winner-v13 state-coherent host is faulted closed: {self._fault_reason}"
            )

    def _discard_all(self) -> None:
        self._calibrator.discard()
        self._locomotion.discard()
        self.target_pipeline.discard_staged()
        self.observer.discard_staged()
        self._staged_stage = None
        self._staged_tick = None

    def _fault(self, reason: str) -> None:
        self._discard_all()
        self._faulted = True
        self._fault_reason = reason

    @staticmethod
    def _validate_tick_indices(
        *,
        tick_index: int,
        expected_tick: int,
        logical_period_ns: int,
        servo_sample_tick_index: int,
        imu_sample_tick_index: int,
        contacts_sample_tick_index: int,
    ) -> None:
        if not isinstance(tick_index, (int, np.integer)):
            raise WinnerV13ContractError("tick index must be an integer")
        if int(tick_index) != expected_tick:
            raise WinnerV13ContractError(
                f"non-contiguous Winner-v13 tick: expected {expected_tick}, got {int(tick_index)}"
            )
        if logical_period_ns != CONTROL_PERIOD_NS:
            raise WinnerV13ContractError(
                f"Winner-v13 logical period must be {CONTROL_PERIOD_NS} ns"
            )
        sample_ticks = (
            servo_sample_tick_index,
            imu_sample_tick_index,
            contacts_sample_tick_index,
        )
        if sample_ticks != (expected_tick, expected_tick, expected_tick):
            raise WinnerV13ContractError(
                f"ambiguous/mixed sample epochs for tick {expected_tick}: {sample_ticks}"
            )

    def stage_tick(
        self,
        *,
        tick_index: int,
        logical_period_ns: int,
        servo_sample_tick_index: int,
        imu_sample_tick_index: int,
        contacts_sample_tick_index: int,
        gyro_rad_s: np.ndarray,
        acceleration_m_s2: np.ndarray,
        commands: np.ndarray,
        positions_rad: np.ndarray,
        velocities_rad_s: np.ndarray,
        foot_contacts: np.ndarray,
        servo_stale: np.ndarray,
        imu_stale: bool,
        contacts_stale: bool,
        soft_offsets_rad: np.ndarray,
    ) -> np.ndarray:
        self._require_active()
        if self.pending:
            raise WinnerV13StateError("Winner-v13 transaction already has a staged tick")
        self._validate_tick_indices(
            tick_index=tick_index,
            expected_tick=self.committed_ticks,
            logical_period_ns=logical_period_ns,
            servo_sample_tick_index=servo_sample_tick_index,
            imu_sample_tick_index=imu_sample_tick_index,
            contacts_sample_tick_index=contacts_sample_tick_index,
        )
        if self._confirmed_calibration_ticks < CALIBRATION_TICKS:
            stage = "calibration"
        elif not self._handoff_complete:
            raise WinnerV13StateError(
                "250 calibration ticks are complete; explicit state-coherent handoff required"
            )
        else:
            stage = "locomotion"
        try:
            observation = self.assembler.build(
                gyro_rad_s=gyro_rad_s,
                acceleration_m_s2=acceleration_m_s2,
                commands=(CALIBRATION_COMMAND if stage == "calibration" else commands),
                positions_rad=positions_rad,
                velocities_rad_s=velocities_rad_s,
                observer_target_rad=self.observer.value_view,
                foot_contacts=foot_contacts,
                phase=(CALIBRATION_PHASE if stage == "calibration" else self.phase.value),
                phase_index=(0 if stage == "calibration" else self.phase.index),
                servo_stale=servo_stale,
                imu_stale=imu_stale,
                contacts_stale=contacts_stale,
            )
            if stage == "calibration":
                observation[6:13] = 0.0
                observation[99:101] = CALIBRATION_PHASE
                observation[101:115] = 0.0
                action = self._calibrator.stage(observation)
            else:
                if self._first_locomotion_observation:
                    observation[41:55] = self._calibration_action_history[0]
                    observation[55:69] = self._calibration_action_history[1]
                    observation[69:83] = self._calibration_action_history[2]
                action = self._locomotion.stage(observation)
            np.copyto(self._staged_action, action)
            physical_target = self.target_pipeline.stage(
                self._staged_action,
                soft_offsets_rad,
                mode=stage,
            )
            self.observer.stage_confirmed_target(self.target_pipeline.sent_logical_target_rad)
        except Exception as exc:
            self._fault(f"{stage} stage failed: {exc}")
            raise
        self._staged_stage = stage
        self._staged_tick = int(tick_index)
        return physical_target

    def discard_staged(self) -> None:
        self._require_active()
        if not self.pending:
            raise WinnerV13StateError("Winner-v13 transaction has no staged tick")
        self._discard_all()

    def complete_send(self, *, write_succeeded: object) -> None:
        self._require_active()
        if not self.pending or self._staged_stage is None:
            raise WinnerV13StateError("Winner-v13 transaction has no staged tick")
        stage = self._staged_stage
        tick = self._staged_tick
        if write_succeeded is not True:
            error = WinnerV13SendError(
                f"Winner-v13 target send for tick {tick} requires literal bool True"
            )
            self._fault(str(error))
            raise error
        try:
            if stage == "calibration":
                self._calibrator.commit(True)
            else:
                self._locomotion.commit(True)
            self.target_pipeline.commit_staged()
            self.observer.commit_staged()
            self.assembler.commit_action(self._staged_action)
            if stage == "calibration":
                np.copyto(
                    self._calibration_action_history[2],
                    self._calibration_action_history[1],
                )
                np.copyto(
                    self._calibration_action_history[1],
                    self._calibration_action_history[0],
                )
                np.copyto(self._calibration_action_history[0], self._staged_action)
                self._confirmed_calibration_ticks += 1
            else:
                self.phase.advance_confirmed()
                self._confirmed_locomotion_ticks += 1
                self._first_locomotion_observation = False
        except Exception as exc:
            self._fault(f"{stage} commit failed after confirmed send: {exc}")
            raise
        self._staged_stage = None
        self._staged_tick = None

    def confirm_calibration_handoff(self, confirmed_success: object) -> None:
        self._require_active()
        if self.pending:
            raise WinnerV13StateError("cannot hand off a pending calibration tick")
        if self._handoff_complete:
            raise WinnerV13StateError("calibration handoff already completed")
        if self._confirmed_calibration_ticks != CALIBRATION_TICKS:
            raise WinnerV13StateError(
                f"handoff requires exactly {CALIBRATION_TICKS} confirmed ticks, got "
                f"{self._confirmed_calibration_ticks}"
            )
        if confirmed_success is not True:
            error = WinnerV13SendError("calibration handoff requires the literal bool True")
            self._fault(str(error))
            raise error
        previous_action = self._calibrator.committed_previous_action
        context = self._calibrator.committed_hidden
        try:
            _exact_float32_vector(
                previous_action,
                ACTION_DIM,
                "final calibration previous_action",
            )
            _exact_float32_vector(
                context,
                CONTEXT_DIM,
                "final calibration context",
            )
            _require_unit_range(context, "final calibration context")
            np.copyto(self._calibration_context, context)
            self._calibration_context.setflags(write=False)
            self._locomotion.initialize_locomotion_handoff(
                previous_action,
                self._calibration_context,
            )
        except Exception as exc:
            self._fault(f"state-coherent handoff failed: {exc}")
            raise
        self._handoff_complete = True


def exact_fit_allowlist(values: frozenset[str]) -> frozenset[str]:
    """Return an exact copied fit allowlist using the graph hash validator."""

    return exact_allowlist(values)
