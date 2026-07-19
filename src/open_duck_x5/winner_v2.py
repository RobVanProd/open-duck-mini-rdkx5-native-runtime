"""Default-disabled, offline contract for the 115-D winner-v2 policy.

This module deliberately has no serial, GPIO, I2C, torque, or runtime CLI
integration.  The frozen 101-D runtime remains the only deployed path.  The
classes here implement the reviewed policy handoff and make every state change
transactional: policy state, action history, target history, P30 observer, and
phase advance only after a caller confirms that the staged logical target was
sent successfully.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .constants import (
    ACTION_DIM,
    ACTION_SCALE_RAD,
    CONTROL_FREQUENCY_HZ,
    CONTROL_PERIOD_NS,
    HOME_RAD,
    JOINT_NAMES,
    LEGACY_TARGET_RATE_LIMIT_RAD_S,
)

WINNER_V2_CONTRACT_ID = "open-duck-mini.g1-t2.winner-v2.115x14.stateful.v1"
WINNER_V2_OBSERVATION_DIM = 115
WINNER_V2_PHASE_PERIOD_TICKS = 27
WINNER_V2_REFERENCE_TABLE_SHA256 = (
    "8102d9cd139584816d807ca635bcca6d37fa6b3c455848e00395b6d565968212"
)
WINNER_V2_P30_FIT_SHA256 = (
    "908ddb01e5d82e661d77b8f3cb186a84665695660b86b304c6d1ae89c79cdb0b"
)
WINNER_V2_HANDOFF_MANIFEST_SHA256 = (
    "d771d188218152c782c7d688440e2dd2083b47fd9b883749123f89226c6827c5"
)
WINNER_V2_HANDOFF_CORRECTION_COMMIT = (
    "e63226eb5b60a9a96cca4bfbb20ef231c0cada64"
)
WINNER_V2_POLICY_CANDIDATE_SHA256 = frozenset(
    {
        "99d3afce0dfac127816c6327665c35b3c403e005f25cd0a505dfcb37f01304de",
        "0dfc24bde5d839e4d346dd8c08d9a7d0222a3847764ec6738bfc7f8d947f4ece",
    }
)
WINNER_V2_SELECTED_POLICY_SHA256 = (
    "99d3afce0dfac127816c6327665c35b3c403e005f25cd0a505dfcb37f01304de"
)
WINNER_V2_POLICY_SELECTION_EVIDENCE_COMMIT = (
    "e0badd7aa79ff791212b8d3822f9eefdc4c162e0"
)
WINNER_V2_POLICY_SELECTION_RESULT_SHA256 = (
    "38b7fc13522844fc3fe7be848f50d68d5cb26064ddb391dbf5e17ff6f31d284f"
)
WINNER_V2_RATE_LIMITS_RAD_S = np.asarray(
    [
        5.24,
        5.24,
        1.50,
        1.50,
        1.50,
        5.24,
        5.24,
        5.24,
        5.24,
        5.24,
        5.24,
        1.25,
        1.00,
        1.25,
    ],
    dtype=np.float64,
)
WINNER_V2_HOME_RAD = HOME_RAD.astype(np.float32)
WINNER_V2_PHASE_TABLE = np.asarray(
    [
        [1.0, 0.0],
        [0.9730448722839355, 0.23061586916446686],
        [0.8936326503753662, 0.448799192905426],
        [0.7660444378852844, 0.6427875757217407],
        [0.5971586108207703, 0.8021231889724731],
        [0.3960797190666199, 0.9182161092758179],
        [0.17364822328090668, 0.9848077297210693],
        [-0.05814482271671295, 0.9983081817626953],
        [-0.2868032455444336, 0.957989513874054],
        [-0.5000000596046448, 0.8660253882408142],
        [-0.6862416863441467, 0.7273736000061035],
        [-0.8354879021644592, 0.5495088696479797],
        [-0.9396926164627075, 0.3420202136039734],
        [-0.9932383298873901, 0.11609296500682831],
        [-0.9932383298873901, -0.11609289795160294],
        [-0.9396926164627075, -0.3420201539993286],
        [-0.8354877829551697, -0.5495089888572693],
        [-0.6862415671348572, -0.7273737192153931],
        [-0.49999991059303284, -0.866025447845459],
        [-0.28680330514907837, -0.957989513874054],
        [-0.058144647628068924, -0.9983081817626953],
        [0.1736481487751007, -0.9848077297210693],
        [0.39607998728752136, -0.9182159900665283],
        [0.5971586108207703, -0.8021231889724731],
        [0.7660443186759949, -0.642787754535675],
        [0.893632709980011, -0.4487990736961365],
        [0.9730448722839355, -0.23061595857143402],
    ],
    dtype=np.float32,
)
WINNER_V2_PHASE_TABLE.setflags(write=False)


class WinnerV2ContractError(RuntimeError):
    """The reviewed winner-v2 contract was violated."""


class WinnerV2StateError(WinnerV2ContractError):
    """A staged/committed state transition was attempted out of order."""


class WinnerV2SendError(WinnerV2ContractError):
    """A staged target was not confirmed as sent."""


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _require_vector(
    value: np.ndarray,
    size: int,
    label: str,
    *,
    dtype: np.dtype | type | None = None,
) -> np.ndarray:
    array = np.asarray(value, dtype=dtype)
    if array.shape != (size,):
        raise WinnerV2ContractError(
            f"{label} must have shape ({size},), got {array.shape}"
        )
    if not bool(np.isfinite(array).all()):
        indices = np.flatnonzero(~np.isfinite(array)).tolist()
        raise WinnerV2ContractError(
            f"{label} contains non-finite values at indices {indices}"
        )
    return array


def validate_winner_v2_command(commands: np.ndarray) -> np.ndarray:
    command = _require_vector(commands, 7, "commands", dtype=np.float64)
    if bool(np.any(command[1:] != 0.0)):
        raise WinnerV2ContractError(
            "winner-v2 permits forward command only; y/yaw/head must be exactly zero"
        )
    x = float(command[0])
    if x != 0.0 and not 0.074 <= x <= 0.080:
        raise WinnerV2ContractError(
            f"winner-v2 forward command is outside the frozen support: {x}"
        )
    return command


class WinnerV2PhaseClock:
    """Integer, observe-current-then-advance 27-tick phase."""

    def __init__(self, *, frequency_factor_offset: float = 0.0) -> None:
        if not math.isfinite(frequency_factor_offset) or frequency_factor_offset != 0.0:
            raise WinnerV2ContractError(
                "winner-v2 requires phase_frequency_factor_offset=0.0 and one step per tick"
            )
        self.index = 0
        self.value = WINNER_V2_PHASE_TABLE[0].copy()

    def advance_confirmed(self) -> None:
        self.index = (self.index + 1) % WINNER_V2_PHASE_PERIOD_TICKS
        # The exact float32 values are pinned from the XLA-generated golden
        # traces.  Recomputing trig with host libm differs by up to two ULPs,
        # which accumulates through the recurrent action chain over 600 ticks.
        np.copyto(self.value, WINNER_V2_PHASE_TABLE[self.index])


class ProjectedReferenceTable:
    """Pinned 240-command by 27-phase projected-reference table."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).resolve()
        self.sha256 = sha256_file(self.path)
        if self.sha256 != WINNER_V2_REFERENCE_TABLE_SHA256:
            raise WinnerV2ContractError(
                f"uncontracted reference-table SHA-256: {self.sha256}"
            )
        with np.load(self.path, allow_pickle=False) as table:
            if not {"commands", "actions"}.issubset(table.files):
                raise WinnerV2ContractError(
                    "reference table must contain commands/actions, got "
                    f"{sorted(table.files)}"
                )
            self.commands = np.asarray(table["commands"], dtype=np.float32).copy()
            self.actions = np.asarray(table["actions"], dtype=np.float32).copy()
        if self.commands.shape != (240, 3) or self.actions.shape != (240, 27, 14):
            raise WinnerV2ContractError(
                "reference table shapes must be (240,3)/(240,27,14), got "
                f"{self.commands.shape}/{self.actions.shape}"
            )
        if not bool(np.isfinite(self.commands).all()) or not bool(
            np.isfinite(self.actions).all()
        ):
            raise WinnerV2ContractError("reference table contains non-finite values")
        self.commands.setflags(write=False)
        self.actions.setflags(write=False)
        self._command = np.zeros(3, dtype=np.float32)
        self._difference = np.zeros((240, 3), dtype=np.float32)
        self._distance = np.zeros(240, dtype=np.float32)
        self._command_finite = np.ones(3, dtype=np.bool_)

    def lookup_into(
        self,
        command3: np.ndarray,
        phase_index: int,
        output: np.ndarray,
    ) -> None:
        if command3.shape != (3,) or command3.dtype != np.float32:
            raise WinnerV2ContractError("command3 must be float32 shape (3,)")
        np.isfinite(command3, out=self._command_finite)
        if not bool(self._command_finite.all()):
            raise WinnerV2ContractError("command3 contains a non-finite value")
        if output.shape != (ACTION_DIM,) or output.dtype != np.float32:
            raise WinnerV2ContractError("reference output must be float32 shape (14,)")
        if isinstance(phase_index, (float, np.floating)) and not float(
            phase_index
        ).is_integer():
            raise WinnerV2ContractError(
                f"phase index must be an integer, got {phase_index}"
            )
        phase = int(phase_index) % WINNER_V2_PHASE_PERIOD_TICKS
        np.copyto(self._command, command3)
        # The frozen command validator permits only exact zero or x>=0.074;
        # avoid a temporary from linalg.norm in the control path.
        if (
            self._command[0] == 0.0
            and self._command[1] == 0.0
            and self._command[2] == 0.0
        ):
            output.fill(0.0)
            return
        np.subtract(self.commands, self._command, out=self._difference)
        np.abs(self._difference, out=self._difference)
        np.sum(self._difference, axis=1, out=self._distance)
        command_index = int(np.argmin(self._distance))
        np.copyto(output, self.actions[command_index, phase])


@dataclass(frozen=True, slots=True)
class JointActuatorParams:
    delay_ticks: int
    tau_s: float
    velocity_limit_rad_s: float


def _params_from_fit(fit: Mapping[str, object]) -> tuple[JointActuatorParams, ...]:
    primary = fit.get("primary", fit)
    if not isinstance(primary, Mapping):
        raise WinnerV2ContractError("P30 fit primary entry must be an object")
    joints = primary.get("joints", {})
    if not isinstance(joints, Mapping):
        raise WinnerV2ContractError("P30 fit joints entry must be an object")
    result: list[JointActuatorParams] = []
    for name in JOINT_NAMES:
        record = joints.get(name, {})
        if not isinstance(record, Mapping):
            raise WinnerV2ContractError(f"P30 joint record {name} must be an object")
        combined = record.get("combined")
        if combined is None:
            result.append(JointActuatorParams(0, 0.0, math.inf))
            continue
        if not isinstance(combined, Mapping):
            raise WinnerV2ContractError(f"P30 combined record {name} must be an object")
        delay = int(combined.get("delay_ticks", 0))
        tau = float(combined.get("tau_s", 0.0))
        velocity = float(combined.get("velocity_limit_rad_s", math.inf))
        if delay < 0 or delay > 100:
            raise WinnerV2ContractError(f"invalid P30 delay for {name}: {delay}")
        if not math.isfinite(tau) or tau < 0.0:
            raise WinnerV2ContractError(f"invalid P30 tau for {name}: {tau}")
        if velocity < 0.0 or math.isnan(velocity):
            raise WinnerV2ContractError(
                f"invalid P30 velocity limit for {name}: {velocity}"
            )
        result.append(JointActuatorParams(delay, tau, velocity))
    return tuple(result)


class P30BridgeObserver:
    """Pinned P30 delay/tau/velocity observer with staged updates."""

    def __init__(self, fit_path: str | Path) -> None:
        self.path = Path(fit_path).resolve()
        self.sha256 = sha256_file(self.path)
        if self.sha256 != WINNER_V2_P30_FIT_SHA256:
            raise WinnerV2ContractError(f"uncontracted P30 fit SHA-256: {self.sha256}")
        with self.path.open(encoding="utf-8") as handle:
            fit = json.load(handle)
        if not isinstance(fit, Mapping):
            raise WinnerV2ContractError("P30 fit root must be an object")
        self.params = _params_from_fit(fit)
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

    @property
    def value_view(self) -> np.ndarray:
        return self._value

    @property
    def pending(self) -> bool:
        return self._pending

    def stage_confirmed_target(self, sent_logical_target_rad: np.ndarray) -> None:
        if self._pending:
            raise WinnerV2StateError("P30 observer already has a staged target")
        if sent_logical_target_rad.shape != (ACTION_DIM,):
            raise WinnerV2ContractError(
                "sent_logical_target_rad must have shape (14,)"
            )
        np.isfinite(sent_logical_target_rad, out=self._target_finite)
        if not bool(self._target_finite.all()):
            raise WinnerV2ContractError(
                "sent_logical_target_rad contains a non-finite value"
            )
        np.copyto(self._staged_target, sent_logical_target_rad, casting="unsafe")
        for index, param in enumerate(self.params):
            queue = self._queues[index]
            staged_queue = self._staged_queues[index]
            if len(queue) > 1:
                staged_queue[:-1] = queue[1:]
            staged_queue[-1] = self._staged_target[index]
            delayed_target = float(staged_queue[0])
            if param.tau_s > 0.0:
                alpha = 1.0 - math.exp(-0.02 / param.tau_s)
                desired = self._value[index] + alpha * (
                    delayed_target - self._value[index]
                )
            else:
                desired = delayed_target
            step = desired - self._value[index]
            max_step = param.velocity_limit_rad_s * 0.02
            if math.isfinite(max_step):
                step = max(-max_step, min(max_step, step))
            self._staged_value[index] = self._value[index] + step
        np.isfinite(self._staged_value, out=self._value_finite)
        if not bool(self._value_finite.all()):
            raise WinnerV2ContractError("P30 observer staged a non-finite value")
        self._pending = True

    def commit_staged(self) -> None:
        if not self._pending:
            raise WinnerV2StateError("P30 observer has no staged target")
        np.copyto(self._value, self._staged_value)
        for queue, staged in zip(self._queues, self._staged_queues, strict=True):
            np.copyto(queue, staged)
        self._pending = False

    def discard_staged(self) -> None:
        self._pending = False


class WinnerV2ObservationAssembler:
    """Preallocated exact 115-D observation assembler."""

    def __init__(self, reference: ProjectedReferenceTable) -> None:
        self.reference = reference
        self.observation = np.zeros(WINNER_V2_OBSERVATION_DIM, dtype=np.float32)
        self.last_action = np.zeros(ACTION_DIM, dtype=np.float32)
        self.action_minus_2 = np.zeros(ACTION_DIM, dtype=np.float32)
        self.action_minus_3 = np.zeros(ACTION_DIM, dtype=np.float32)
        # Training assembled the next observation before shifting last_act.
        # Consequently these visible slots are t-2/t-3/t-4; the separate
        # ONNX previous_action state remains t-1.  The extra deferred buffer
        # reproduces that exact golden-trace ordering.
        self._deferred_action = np.zeros(ACTION_DIM, dtype=np.float32)
        self._position_error = np.zeros(ACTION_DIM, dtype=np.float64)
        self._velocity_scaled = np.zeros(ACTION_DIM, dtype=np.float64)
        self._finite = np.ones(ACTION_DIM, dtype=np.bool_)

    @staticmethod
    def _shape(name: str, value: np.ndarray, shape: tuple[int, ...]) -> None:
        if value.shape != shape:
            raise WinnerV2ContractError(
                f"{name} must have shape {shape}, got {value.shape}"
            )

    def build(
        self,
        *,
        gyro_rad_s: np.ndarray,
        acceleration_m_s2: np.ndarray,
        commands: np.ndarray,
        positions_rad: np.ndarray,
        velocities_rad_s: np.ndarray,
        observer_target_rad: np.ndarray,
        foot_contacts: np.ndarray,
        phase: np.ndarray,
        phase_index: int,
        servo_stale: np.ndarray,
        imu_stale: bool,
        contacts_stale: bool,
    ) -> np.ndarray:
        self._shape("gyro", gyro_rad_s, (3,))
        self._shape("acceleration", acceleration_m_s2, (3,))
        self._shape("commands", commands, (7,))
        self._shape("positions", positions_rad, (ACTION_DIM,))
        self._shape("velocities", velocities_rad_s, (ACTION_DIM,))
        self._shape("observer_target", observer_target_rad, (ACTION_DIM,))
        self._shape("foot_contacts", foot_contacts, (2,))
        self._shape("phase", phase, (2,))
        self._shape("servo_stale", servo_stale, (ACTION_DIM,))
        if bool(servo_stale.any()) or imu_stale or contacts_stale:
            raise WinnerV2ContractError(
                "required winner-v2 sample is stale; refusing mixed-age observation"
            )
        finite_values = (
            ("gyro", gyro_rad_s),
            ("acceleration", acceleration_m_s2),
            ("commands", commands),
            ("positions", positions_rad),
            ("velocities", velocities_rad_s),
            ("observer_target", observer_target_rad),
            ("foot_contacts", foot_contacts),
            ("phase", phase),
        )
        for name, value in finite_values:
            finite = self._finite[: value.size].reshape(value.shape)
            np.isfinite(value, out=finite)
            if not bool(finite.all()):
                indices = np.flatnonzero(~finite).tolist()
                raise WinnerV2ContractError(
                    f"{name} contains non-finite values at indices {indices}"
                )
        command = validate_winner_v2_command(commands)
        if not isinstance(phase_index, (int, np.integer)):
            raise WinnerV2ContractError("phase index must be an integer")

        obs = self.observation
        obs[0:3] = gyro_rad_s
        obs[3:6] = acceleration_m_s2
        obs[6:13] = command
        np.subtract(positions_rad, HOME_RAD, out=self._position_error)
        obs[13:27] = self._position_error
        np.multiply(velocities_rad_s, 0.05, out=self._velocity_scaled)
        obs[27:41] = self._velocity_scaled
        obs[41:55] = self.last_action
        obs[55:69] = self.action_minus_2
        obs[69:83] = self.action_minus_3
        obs[83:97] = observer_target_rad
        obs[97:99] = foot_contacts
        obs[99:101] = phase
        self.reference.lookup_into(obs[6:9], int(phase_index), obs[101:115])
        return obs

    def commit_action(self, action: np.ndarray) -> None:
        action = _require_vector(action, ACTION_DIM, "action", dtype=np.float32)
        np.copyto(self.action_minus_3, self.action_minus_2)
        np.copyto(self.action_minus_2, self.last_action)
        np.copyto(self.last_action, self._deferred_action)
        np.copyto(self._deferred_action, action)


class WinnerV2OnnxPolicy:
    """Strict CPU-only stateful ONNX host with staged recurrent state."""

    def __init__(
        self,
        model_path: str | Path,
        *,
        warmup_runs: int = 10,
        allow_audit_policy: bool = False,
    ) -> None:
        try:
            import onnxruntime as ort
        except ImportError as exc:
            raise RuntimeError("install the 'policy' extra to use ONNX Runtime") from exc
        self.path = Path(model_path).resolve()
        if not self.path.is_file():
            raise FileNotFoundError(self.path)
        self.sha256 = sha256_file(self.path)
        accepted_hashes = (
            WINNER_V2_POLICY_CANDIDATE_SHA256
            if allow_audit_policy
            else frozenset({WINNER_V2_SELECTED_POLICY_SHA256})
        )
        if self.sha256 not in accepted_hashes:
            raise WinnerV2ContractError(
                "unselected/uncontracted winner-v2 policy SHA-256: "
                f"{self.sha256}"
            )
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
        if self.session.get_providers() != ["CPUExecutionProvider"]:
            raise WinnerV2ContractError(
                f"winner-v2 requires CPUExecutionProvider only, got "
                f"{self.session.get_providers()}"
            )
        inputs = [(node.name, list(node.shape), node.type) for node in self.session.get_inputs()]
        outputs = [
            (node.name, list(node.shape), node.type) for node in self.session.get_outputs()
        ]
        expected_inputs = [
            ("obs", [1, 115], "tensor(float)"),
            ("previous_action", [1, 14], "tensor(float)"),
        ]
        expected_outputs = [
            ("continuous_actions", [1, 14], "tensor(float)"),
            ("previous_action_out", [1, 14], "tensor(float)"),
        ]
        if inputs != expected_inputs or outputs != expected_outputs:
            raise WinnerV2ContractError(
                f"winner-v2 ONNX ABI mismatch: inputs={inputs}, outputs={outputs}"
            )

        self._observation = np.zeros((1, 115), dtype=np.float32)
        self._previous_action = np.zeros((1, 14), dtype=np.float32)
        self._action = np.zeros((1, 14), dtype=np.float32)
        self._staged_state = np.zeros((1, 14), dtype=np.float32)
        self._input_finite = np.ones(115, dtype=np.bool_)
        self._action_finite = np.ones(14, dtype=np.bool_)
        self._state_finite = np.ones(14, dtype=np.bool_)
        self._observation_ort = ort.OrtValue.ortvalue_from_numpy(self._observation)
        self._previous_action_ort = ort.OrtValue.ortvalue_from_numpy(
            self._previous_action
        )
        self._action_ort = ort.OrtValue.ortvalue_from_numpy(self._action)
        self._staged_state_ort = ort.OrtValue.ortvalue_from_numpy(self._staged_state)
        self._binding = self.session.io_binding()
        self._binding.bind_ortvalue_input("obs", self._observation_ort)
        self._binding.bind_ortvalue_input("previous_action", self._previous_action_ort)
        self._binding.bind_ortvalue_output("continuous_actions", self._action_ort)
        self._binding.bind_ortvalue_output(
            "previous_action_out", self._staged_state_ort
        )
        self._pending = False
        for _ in range(max(1, int(warmup_runs))):
            self.session.run_with_iobinding(self._binding)
            self._require_finite_and_equal("ONNX warm-up")
        self._action.fill(0.0)
        self._staged_state.fill(0.0)

    @property
    def previous_action_view(self) -> np.ndarray:
        return self._previous_action[0]

    @property
    def staged_state_view(self) -> np.ndarray:
        return self._staged_state[0]

    @property
    def action_view(self) -> np.ndarray:
        return self._action[0]

    @property
    def pending(self) -> bool:
        return self._pending

    def _require_finite_and_equal(self, operation: str) -> None:
        np.isfinite(self._action[0], out=self._action_finite)
        np.isfinite(self._staged_state[0], out=self._state_finite)
        if not bool(self._action_finite.all()) or not bool(self._state_finite.all()):
            raise WinnerV2ContractError(f"{operation} produced non-finite output/state")
        if not bool(np.array_equal(self._action, self._staged_state)):
            error = float(np.max(np.abs(self._action - self._staged_state)))
            raise WinnerV2ContractError(
                f"{operation} action/state chain diverged by {error}"
            )

    def stage(self, observation: np.ndarray) -> np.ndarray:
        if self._pending:
            raise WinnerV2StateError("winner-v2 policy already has staged state")
        if observation.shape != (WINNER_V2_OBSERVATION_DIM,):
            raise WinnerV2ContractError("winner-v2 observation must have shape (115,)")
        np.isfinite(observation, out=self._input_finite)
        if not bool(self._input_finite.all()):
            indices = np.flatnonzero(~self._input_finite).tolist()
            raise WinnerV2ContractError(
                f"winner-v2 observation contains non-finite values at indices {indices}"
            )
        np.copyto(self._observation[0], observation, casting="unsafe")
        self.session.run_with_iobinding(self._binding)
        self._require_finite_and_equal("ONNX inference")
        self._pending = True
        return self._action[0]

    def commit_staged(self) -> None:
        if not self._pending:
            raise WinnerV2StateError("winner-v2 policy has no staged state")
        np.copyto(self._previous_action, self._staged_state)
        self._pending = False

    def discard_staged(self) -> None:
        self._pending = False


class WinnerV2ActionPipeline:
    """Graph-authoritative target conversion with legacy limiter assertion."""

    def __init__(self) -> None:
        self.logical_target_rad = WINNER_V2_HOME_RAD.copy()
        self.physical_target_rad = HOME_RAD.copy()
        self.implied_velocity_rad_s = np.zeros(ACTION_DIM, dtype=np.float64)
        self.graph_rate_excess_rad_s = np.zeros(ACTION_DIM, dtype=np.float64)
        self._absolute_velocity_rad_s = np.zeros(ACTION_DIM, dtype=np.float64)
        self._previous_logical_target_rad = WINNER_V2_HOME_RAD.copy()
        self._lower_bound = np.zeros(ACTION_DIM, dtype=np.float32)
        self._upper_bound = np.zeros(ACTION_DIM, dtype=np.float32)
        self._legacy_limited_target = WINNER_V2_HOME_RAD.copy()
        self._pending = False

    @property
    def previous_logical_target_view(self) -> np.ndarray:
        return self._previous_logical_target_rad

    @property
    def pending(self) -> bool:
        return self._pending

    def stage(self, action: np.ndarray, soft_offsets_rad: np.ndarray) -> np.ndarray:
        if self._pending:
            raise WinnerV2StateError("winner-v2 action pipeline already has a staged target")
        action = _require_vector(action, ACTION_DIM, "action", dtype=np.float32)
        offsets = _require_vector(
            soft_offsets_rad, ACTION_DIM, "soft_offsets_rad", dtype=np.float64
        )
        np.multiply(action, np.float32(ACTION_SCALE_RAD), out=self.logical_target_rad)
        np.add(
            self.logical_target_rad,
            WINNER_V2_HOME_RAD,
            out=self.logical_target_rad,
        )
        max_step = np.float32(
            LEGACY_TARGET_RATE_LIMIT_RAD_S / CONTROL_FREQUENCY_HZ
        )
        np.subtract(
            self._previous_logical_target_rad,
            max_step,
            out=self._lower_bound,
        )
        np.add(
            self._previous_logical_target_rad,
            max_step,
            out=self._upper_bound,
        )
        np.clip(
            self.logical_target_rad,
            self._lower_bound,
            self._upper_bound,
            out=self._legacy_limited_target,
        )
        if not bool(np.array_equal(self._legacy_limited_target, self.logical_target_rad)):
            error = np.abs(
                self._legacy_limited_target.astype(np.float64)
                - self.logical_target_rad.astype(np.float64)
            )
            indices = np.flatnonzero(error > 0.0).tolist()
            raise WinnerV2ContractError(
                "legacy 5.24 rad/s limiter is not identity; changed joints "
                f"{indices}, max change {float(error.max())} rad"
            )
        np.subtract(
            self.logical_target_rad,
            self._previous_logical_target_rad,
            out=self.implied_velocity_rad_s,
        )
        self.implied_velocity_rad_s *= CONTROL_FREQUENCY_HZ
        np.abs(self.implied_velocity_rad_s, out=self._absolute_velocity_rad_s)
        np.subtract(
            self._absolute_velocity_rad_s,
            WINNER_V2_RATE_LIMITS_RAD_S,
            out=self.graph_rate_excess_rad_s,
        )
        np.maximum(self.graph_rate_excess_rad_s, 0.0, out=self.graph_rate_excess_rad_s)
        self.graph_rate_excess_rad_s[self.graph_rate_excess_rad_s <= 1.0e-5] = 0.0
        if bool(np.any(self.graph_rate_excess_rad_s > 0.0)):
            indices = np.flatnonzero(self.graph_rate_excess_rad_s > 0.0).tolist()
            raise WinnerV2ContractError(
                f"graph-authoritative rate limit exceeded at joints {indices}"
            )
        np.add(
            self.logical_target_rad,
            offsets,
            out=self.physical_target_rad,
        )
        self._pending = True
        return self.physical_target_rad

    def commit_staged(self) -> None:
        if not self._pending:
            raise WinnerV2StateError("winner-v2 action pipeline has no staged target")
        np.copyto(self._previous_logical_target_rad, self.logical_target_rad)
        self._pending = False

    def discard_staged(self) -> None:
        self._pending = False


class WinnerV2TickTransaction:
    """Own one all-or-nothing winner-v2 policy transition.

    The caller may write ``physical_target_view`` to a mock or bus only after
    :meth:`stage_tick` succeeds.  It must then call :meth:`complete_send` with
    an unambiguous boolean result.  A false/ambiguous result discards all staged
    state and raises; a true result commits all state exactly once.
    """

    def __init__(
        self,
        *,
        policy: WinnerV2OnnxPolicy,
        observer: P30BridgeObserver,
        reference: ProjectedReferenceTable,
        phase_frequency_factor_offset: float = 0.0,
    ) -> None:
        self.policy = policy
        self.observer = observer
        self.phase = WinnerV2PhaseClock(
            frequency_factor_offset=phase_frequency_factor_offset
        )
        self.assembler = WinnerV2ObservationAssembler(reference)
        self.action_pipeline = WinnerV2ActionPipeline()
        self.committed_ticks = 0
        self._staged_tick: int | None = None

    @property
    def pending(self) -> bool:
        return self._staged_tick is not None

    @property
    def observation_view(self) -> np.ndarray:
        return self.assembler.observation

    @property
    def logical_target_view(self) -> np.ndarray:
        return self.action_pipeline.logical_target_rad

    @property
    def normalized_action_view(self) -> np.ndarray:
        return self.policy.action_view

    @property
    def physical_target_view(self) -> np.ndarray:
        return self.action_pipeline.physical_target_rad

    def _discard_all(self) -> None:
        self.policy.discard_staged()
        self.action_pipeline.discard_staged()
        self.observer.discard_staged()
        self._staged_tick = None

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
        if self.pending:
            raise WinnerV2StateError("winner-v2 transaction already has a staged tick")
        if not isinstance(tick_index, (int, np.integer)):
            raise WinnerV2ContractError("tick index must be an integer")
        tick = int(tick_index)
        if tick != self.committed_ticks:
            raise WinnerV2ContractError(
                f"non-contiguous winner-v2 tick: expected {self.committed_ticks}, got {tick}"
            )
        if logical_period_ns != CONTROL_PERIOD_NS:
            raise WinnerV2ContractError(
                f"winner-v2 logical period must be {CONTROL_PERIOD_NS} ns"
            )
        sample_ticks = (
            servo_sample_tick_index,
            imu_sample_tick_index,
            contacts_sample_tick_index,
        )
        if sample_ticks != (tick, tick, tick):
            raise WinnerV2ContractError(
                f"ambiguous/mixed sample epochs for tick {tick}: {sample_ticks}"
            )
        try:
            observation = self.assembler.build(
                gyro_rad_s=gyro_rad_s,
                acceleration_m_s2=acceleration_m_s2,
                commands=commands,
                positions_rad=positions_rad,
                velocities_rad_s=velocities_rad_s,
                observer_target_rad=self.observer.value_view,
                foot_contacts=foot_contacts,
                phase=self.phase.value,
                phase_index=self.phase.index,
                servo_stale=servo_stale,
                imu_stale=imu_stale,
                contacts_stale=contacts_stale,
            )
            action = self.policy.stage(observation)
            physical_target = self.action_pipeline.stage(action, soft_offsets_rad)
            self.observer.stage_confirmed_target(
                self.action_pipeline.logical_target_rad
            )
        except BaseException:
            self._discard_all()
            raise
        self._staged_tick = tick
        return physical_target

    def complete_send(self, *, write_succeeded: bool) -> None:
        if not self.pending:
            raise WinnerV2StateError("winner-v2 transaction has no staged tick")
        if write_succeeded is not True:
            tick = self._staged_tick
            self._discard_all()
            raise WinnerV2SendError(
                f"winner-v2 target send for tick {tick} was not confirmed; state unchanged"
            )
        action = self.policy.action_view
        self.policy.commit_staged()
        self.action_pipeline.commit_staged()
        self.observer.commit_staged()
        self.assembler.commit_action(action)
        self.phase.advance_confirmed()
        self.committed_ticks += 1
        self._staged_tick = None
