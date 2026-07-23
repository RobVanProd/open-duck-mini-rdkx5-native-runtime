"""Default-disabled host for the provisional Winner-v12 two-graph ABI.

This module is deliberately isolated from the runtime CLI and control loop.  It
does not select a policy asset: callers must supply the exact graph ABI and a
non-empty SHA-256 allowlist for each ONNX file.  The learned calibration
context exists only in this object for the lifetime of the process; there is no
load, save, or serialization API for it.

The host is transactional.  Inference writes only staged buffers.  Confirming
a successful external transaction commits action and recurrent state together;
discarding leaves committed state untouched.  After calibration it requires the
reviewed 250-tick zero-action home return before locomotion starts with exact
zero previous action and recurrent state.  False or ambiguous confirmation
faults the complete two-graph host closed.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

OBSERVATION_DIM = 115
ACTION_DIM = 14
HIDDEN_DIM = 64
CONTEXT_DIM = 64
CALIBRATION_TICKS = 250
HOME_RETURN_TICKS = 250
CONTEXT_MIN = np.float32(-1.0)
CONTEXT_MAX = np.float32(1.0)
_FLOAT_TENSOR = "tensor(float)"
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_CALIBRATOR_INPUT_NAMES = ("obs", "previous_action", "h_in")
_CALIBRATOR_OUTPUT_NAMES = (
    "calibration_actions",
    "previous_action_out",
    "h_out",
)


class WinnerV12ContractError(RuntimeError):
    """A graph, tensor, asset, or two-stage contract was violated."""


class WinnerV12StateError(WinnerV12ContractError):
    """A staged or handoff operation was attempted out of order."""


class WinnerV12CommitError(WinnerV12ContractError):
    """A staged action did not receive an unambiguous success confirmation."""


@dataclass(frozen=True)
class TensorSpec:
    """One exact ONNX tensor declaration supplied by the policy handoff."""

    name: str
    shape: tuple[int, ...]
    dtype: str = _FLOAT_TENSOR

    def __post_init__(self) -> None:
        if not self.name or not isinstance(self.name, str):
            raise WinnerV12ContractError("tensor name must be a non-empty string")
        if (
            not isinstance(self.shape, tuple)
            or not self.shape
            or any(type(value) is not int or value <= 0 for value in self.shape)
        ):
            raise WinnerV12ContractError(
                f"{self.name} requires a fixed positive-integer shape"
            )
        if self.dtype != _FLOAT_TENSOR:
            raise WinnerV12ContractError(
                f"{self.name} must use {_FLOAT_TENSOR}, got {self.dtype}"
            )


@dataclass(frozen=True)
class GraphSpec:
    """Exact graph ABI with semantic roles kept separate from tensor names.

    The final locomotion graph is not selected.  Requiring this object from the
    caller lets a future reviewed handoff bind its exact names and ordering
    without changing or guessing the runtime contract today.
    """

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
            raise WinnerV12ContractError(f"unknown Winner-v12 graph stage: {stage}")
        expected_context = stage == "locomotion"
        if (self.calibration_context is not None) is not expected_context:
            requirement = "requires" if expected_context else "must not have"
            raise WinnerV12ContractError(
                f"{stage} graph {requirement} a calibration-context input"
            )
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
                raise WinnerV12ContractError(
                    f"{stage} role {tensor.name} must have shape {expected_shape}, "
                    f"got {tensor.shape}"
                )
        input_names = [tensor.name for tensor in self.inputs]
        output_names = [tensor.name for tensor in self.outputs]
        if stage == "calibration" and (
            tuple(input_names) != _CALIBRATOR_INPUT_NAMES
            or tuple(output_names) != _CALIBRATOR_OUTPUT_NAMES
        ):
            raise WinnerV12ContractError(
                "calibration graph names differ from the reviewed provisional ABI"
            )
        if len(set(input_names)) != len(input_names):
            raise WinnerV12ContractError(f"{stage} input names are not unique")
        if len(set(output_names)) != len(output_names):
            raise WinnerV12ContractError(f"{stage} output names are not unique")


@dataclass(frozen=True)
class GraphAsset:
    """One caller-selected ONNX file, exact ABI, and accepted byte hashes."""

    path: str | Path
    spec: GraphSpec
    allowed_sha256: frozenset[str]

    def __post_init__(self) -> None:
        if not isinstance(self.spec, GraphSpec):
            raise WinnerV12ContractError("graph asset requires an exact GraphSpec")
        if isinstance(self.allowed_sha256, str):
            raise WinnerV12ContractError("SHA-256 allowlist must not be a string")
        try:
            hashes = frozenset(self.allowed_sha256)
        except TypeError as exc:
            raise WinnerV12ContractError("SHA-256 allowlist is not iterable") from exc
        if not hashes:
            raise WinnerV12ContractError("SHA-256 allowlist must be non-empty")
        if any(
            not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None
            for value in hashes
        ):
            raise WinnerV12ContractError(
                "SHA-256 allowlist entries must be exact lowercase 64-hex strings"
            )
        object.__setattr__(self, "allowed_sha256", hashes)


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _exact_float32_vector(value: np.ndarray, size: int, label: str) -> np.ndarray:
    if not isinstance(value, np.ndarray):
        raise WinnerV12ContractError(f"{label} must be a numpy.ndarray")
    if value.shape != (size,):
        raise WinnerV12ContractError(
            f"{label} must have shape ({size},), got {value.shape}"
        )
    if value.dtype != np.dtype(np.float32):
        raise WinnerV12ContractError(
            f"{label} must have dtype float32, got {value.dtype}"
        )
    if not bool(np.isfinite(value).all()):
        indices = np.flatnonzero(~np.isfinite(value)).tolist()
        raise WinnerV12ContractError(
            f"{label} contains non-finite values at indices {indices}"
        )
    return value


def _require_unit_range(value: np.ndarray, label: str) -> None:
    if bool(np.any(value < CONTEXT_MIN)) or bool(np.any(value > CONTEXT_MAX)):
        minimum = float(np.min(value))
        maximum = float(np.max(value))
        raise WinnerV12ContractError(
            f"{label} is outside [-1, 1]: min={minimum}, max={maximum}"
        )


class _BoundGraphSession:
    """One preallocated, staged CPU-only ONNX session."""

    def __init__(
        self,
        asset: GraphAsset,
        *,
        stage: str,
        warmup_runs: int,
    ) -> None:
        if type(warmup_runs) is not int or warmup_runs < 0:
            raise WinnerV12ContractError("warmup_runs must be a non-negative integer")
        asset.spec.validate_semantics(stage=stage)
        self.stage_name = stage
        self.spec = asset.spec
        self.path = Path(asset.path).resolve()
        if not self.path.is_file():
            raise FileNotFoundError(self.path)
        self.sha256 = sha256_file(self.path)
        if self.sha256 not in asset.allowed_sha256:
            raise WinnerV12ContractError(
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
            raise WinnerV12ContractError(
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
            raise WinnerV12ContractError(
                f"{stage} ONNX ABI mismatch: inputs={actual_inputs}, "
                f"outputs={actual_outputs}"
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
            ort, self.spec.previous_action_out.name, self._previous_action_out
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
    def pending(self) -> bool:
        return self._pending

    @property
    def committed_previous_action(self) -> np.ndarray:
        return self._previous_action[0]

    @property
    def committed_hidden(self) -> np.ndarray:
        return self._hidden_in[0]

    @property
    def staged_action(self) -> np.ndarray:
        return self._staged_action_view

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
                raise WinnerV12ContractError(
                    f"{operation} produced non-finite {label}"
                )
        for label, value in (
            ("action", self._action),
            ("previous_action_out", self._previous_action_out),
        ):
            np.less(value, CONTEXT_MIN, out=self._action_range_bad)
            below = bool(self._action_range_bad.any())
            np.greater(value, CONTEXT_MAX, out=self._action_range_bad)
            if below or bool(self._action_range_bad.any()):
                minimum = float(np.min(value))
                maximum = float(np.max(value))
                raise WinnerV12ContractError(
                    f"{operation} {label} is outside [-1, 1]: "
                    f"min={minimum}, max={maximum}"
                )
        if not bool(np.array_equal(self._action, self._previous_action_out)):
            error = float(np.max(np.abs(self._action - self._previous_action_out)))
            raise WinnerV12ContractError(
                f"{operation} action/previous-action chain diverged by {error}"
            )

    def stage(self, observation: np.ndarray) -> np.ndarray:
        if self._pending:
            raise WinnerV12StateError(f"{self.stage_name} graph already has staged state")
        if not isinstance(observation, np.ndarray):
            raise WinnerV12ContractError(
                f"{self.stage_name} observation must be a numpy.ndarray"
            )
        if observation.shape != (OBSERVATION_DIM,):
            raise WinnerV12ContractError(
                f"{self.stage_name} observation must have shape "
                f"({OBSERVATION_DIM},), got {observation.shape}"
            )
        if observation.dtype != np.dtype(np.float32):
            raise WinnerV12ContractError(
                f"{self.stage_name} observation must have dtype float32, "
                f"got {observation.dtype}"
            )
        np.isfinite(observation, out=self._observation_finite)
        if not bool(self._observation_finite.all()):
            indices = np.flatnonzero(~self._observation_finite).tolist()
            raise WinnerV12ContractError(
                f"{self.stage_name} observation contains non-finite values "
                f"at indices {indices}"
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
        return self.staged_action

    def commit(self, confirmed_success: object) -> None:
        if not self._pending:
            raise WinnerV12StateError(f"{self.stage_name} graph has no staged state")
        if confirmed_success is not True:
            self.discard()
            raise WinnerV12CommitError(
                f"{self.stage_name} commit requires the literal bool True"
            )
        self._validate_staged_outputs(f"{self.stage_name} commit")
        np.copyto(self._previous_action, self._previous_action_out)
        np.copyto(self._hidden_in, self._hidden_out)
        self._pending = False
        self._scrub_staged()

    def discard(self) -> None:
        self._pending = False
        self._scrub_staged()

    def initialize_locomotion_handoff(
        self, previous_action: np.ndarray, context: np.ndarray
    ) -> None:
        if self.stage_name != "locomotion" or self._context is None:
            raise WinnerV12StateError("handoff target is not a locomotion graph")
        if self._handoff_initialized:
            raise WinnerV12StateError("locomotion handoff is already initialized")
        if self._pending:
            raise WinnerV12StateError("locomotion graph has staged state during handoff")
        previous_action = _exact_float32_vector(
            previous_action, ACTION_DIM, "handoff previous_action"
        )
        context = _exact_float32_vector(context, CONTEXT_DIM, "calibration context")
        _require_unit_range(context, "calibration context")
        np.copyto(self._previous_action[0], previous_action)
        self._hidden_in.fill(0.0)
        np.copyto(self._context[0], context)
        self._context.setflags(write=False)
        self._handoff_initialized = True


class WinnerV12TwoStageHost:
    """Default-off transactional host for calibration, home return, locomotion.

    ``enabled`` defaults to ``False`` and there is intentionally no method that
    changes it after construction.  No runtime integration or hardware access
    exists in this module.
    """

    def __init__(
        self,
        calibrator: GraphAsset,
        locomotion: GraphAsset,
        *,
        enabled: bool = False,
        warmup_runs: int = 1,
    ) -> None:
        if type(enabled) is not bool:
            raise WinnerV12ContractError("enabled must be a literal bool")
        self._enabled = enabled
        effective_warmup_runs = warmup_runs if enabled else 0
        self._calibrator = _BoundGraphSession(
            calibrator, stage="calibration", warmup_runs=effective_warmup_runs
        )
        self._locomotion = _BoundGraphSession(
            locomotion, stage="locomotion", warmup_runs=effective_warmup_runs
        )
        self._calibration_context = np.zeros(CONTEXT_DIM, dtype=np.float32)
        self._home_return_action = np.zeros(ACTION_DIM, dtype=np.float32)
        self._home_return_action.setflags(write=False)
        self._confirmed_calibration_ticks = 0
        self._confirmed_home_return_ticks = 0
        self._calibration_complete = False
        self._home_return_pending = False
        self._handoff_complete = False
        self._faulted = False
        self._fault_reason: str | None = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def faulted(self) -> bool:
        return self._faulted

    @property
    def fault_reason(self) -> str | None:
        return self._fault_reason

    @property
    def confirmed_calibration_ticks(self) -> int:
        return self._confirmed_calibration_ticks

    @property
    def confirmed_home_return_ticks(self) -> int:
        return self._confirmed_home_return_ticks

    @property
    def calibration_complete(self) -> bool:
        return self._calibration_complete

    @property
    def handoff_complete(self) -> bool:
        return self._handoff_complete

    @property
    def calibration_context(self) -> np.ndarray:
        if not self._handoff_complete:
            raise WinnerV12StateError("calibration context is not available")
        value = self._calibration_context.copy()
        value.setflags(write=False)
        return value

    @property
    def locomotion_previous_action(self) -> np.ndarray:
        value = self._locomotion.committed_previous_action.copy()
        value.setflags(write=False)
        return value

    @property
    def locomotion_hidden(self) -> np.ndarray:
        value = self._locomotion.committed_hidden.copy()
        value.setflags(write=False)
        return value

    def _require_active(self) -> None:
        if not self._enabled:
            raise WinnerV12StateError("Winner-v12 two-stage host is disabled")
        if self._faulted:
            raise WinnerV12StateError(
                f"Winner-v12 two-stage host is faulted closed: {self._fault_reason}"
            )

    def _fault(self, reason: str) -> None:
        self._calibrator.discard()
        self._locomotion.discard()
        self._home_return_pending = False
        self._faulted = True
        self._fault_reason = reason

    def stage_calibration(self, observation: np.ndarray) -> np.ndarray:
        self._require_active()
        if self._calibration_complete:
            raise WinnerV12StateError("calibration sequence is already complete")
        if self._confirmed_calibration_ticks >= CALIBRATION_TICKS:
            raise WinnerV12StateError("calibration sequence awaits explicit handoff")
        try:
            return self._calibrator.stage(observation)
        except Exception as exc:
            self._fault(f"calibration stage failed: {exc}")
            raise

    def commit_calibration(self, confirmed_success: object) -> None:
        self._require_active()
        try:
            self._calibrator.commit(confirmed_success)
        except WinnerV12ContractError as exc:
            self._fault(str(exc))
            raise
        self._confirmed_calibration_ticks += 1

    def discard_calibration(self) -> None:
        self._require_active()
        self._calibrator.discard()

    def confirm_calibration_sequence(self, confirmed_success: object) -> None:
        self._require_active()
        if self._calibration_complete:
            raise WinnerV12StateError("calibration sequence is already complete")
        if self._calibrator.pending:
            raise WinnerV12StateError("cannot hand off a pending calibration tick")
        if self._confirmed_calibration_ticks != CALIBRATION_TICKS:
            raise WinnerV12StateError(
                f"handoff requires exactly {CALIBRATION_TICKS} confirmed ticks, got "
                f"{self._confirmed_calibration_ticks}"
            )
        if confirmed_success is not True:
            error = WinnerV12CommitError(
                "calibration-sequence handoff requires the literal bool True"
            )
            self._fault(str(error))
            raise error
        context = self._calibrator.committed_hidden
        try:
            _exact_float32_vector(context, CONTEXT_DIM, "final calibration context")
            _require_unit_range(context, "final calibration context")
            np.copyto(self._calibration_context, context)
            self._calibration_context.setflags(write=False)
        except Exception as exc:
            self._fault(f"calibration completion failed: {exc}")
            raise
        self._calibration_complete = True

    def stage_home_return(self) -> np.ndarray:
        """Stage the exact zero action used by the reviewed reset prefix."""

        self._require_active()
        if not self._calibration_complete:
            raise WinnerV12StateError(
                "home return cannot stage before successful calibration"
            )
        if self._handoff_complete:
            raise WinnerV12StateError("home return already handed off")
        if self._confirmed_home_return_ticks >= HOME_RETURN_TICKS:
            raise WinnerV12StateError("home-return sequence awaits explicit handoff")
        if self._home_return_pending:
            raise WinnerV12StateError("home return already has a staged action")
        self._home_return_pending = True
        return self._home_return_action

    def commit_home_return(self, confirmed_success: object) -> None:
        self._require_active()
        if not self._home_return_pending:
            raise WinnerV12StateError("home return has no staged action")
        self._home_return_pending = False
        if confirmed_success is not True:
            error = WinnerV12CommitError(
                "home-return commit requires the literal bool True"
            )
            self._fault(str(error))
            raise error
        self._confirmed_home_return_ticks += 1

    def discard_home_return(self) -> None:
        self._require_active()
        self._home_return_pending = False

    def confirm_home_return_sequence(self, confirmed_success: object) -> None:
        self._require_active()
        if not self._calibration_complete:
            raise WinnerV12StateError(
                "home-return handoff requires completed calibration"
            )
        if self._handoff_complete:
            raise WinnerV12StateError("home-return handoff already completed")
        if self._home_return_pending:
            raise WinnerV12StateError("cannot hand off a pending home-return tick")
        if self._confirmed_home_return_ticks != HOME_RETURN_TICKS:
            raise WinnerV12StateError(
                f"handoff requires exactly {HOME_RETURN_TICKS} confirmed home-return "
                f"ticks, got {self._confirmed_home_return_ticks}"
            )
        if confirmed_success is not True:
            error = WinnerV12CommitError(
                "home-return sequence handoff requires the literal bool True"
            )
            self._fault(str(error))
            raise error
        try:
            self._locomotion.initialize_locomotion_handoff(
                np.zeros(ACTION_DIM, dtype=np.float32),
                self._calibration_context,
            )
        except Exception as exc:
            self._fault(f"home-return handoff failed: {exc}")
            raise
        self._handoff_complete = True

    def stage_locomotion(self, observation: np.ndarray) -> np.ndarray:
        self._require_active()
        if not self._handoff_complete:
            raise WinnerV12StateError(
                "locomotion cannot stage before successful calibration and "
                "home-return handoff"
            )
        try:
            return self._locomotion.stage(observation)
        except Exception as exc:
            self._fault(f"locomotion stage failed: {exc}")
            raise

    def commit_locomotion(self, confirmed_success: object) -> None:
        self._require_active()
        if not self._handoff_complete:
            raise WinnerV12StateError("locomotion handoff is incomplete")
        try:
            self._locomotion.commit(confirmed_success)
        except WinnerV12ContractError as exc:
            self._fault(str(exc))
            raise

    def discard_locomotion(self) -> None:
        self._require_active()
        self._locomotion.discard()


def exact_allowlist(values: Iterable[str]) -> frozenset[str]:
    """Return a copied exact allowlist, primarily for configuration adapters."""

    if isinstance(values, str):
        raise WinnerV12ContractError("SHA-256 allowlist must not be a string")
    result = frozenset(values)
    if not result or any(
        not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None
        for value in result
    ):
        raise WinnerV12ContractError(
            "SHA-256 allowlist entries must be exact lowercase 64-hex strings"
        )
    return result
