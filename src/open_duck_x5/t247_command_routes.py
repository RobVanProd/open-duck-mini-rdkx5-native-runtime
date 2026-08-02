"""Default-disabled, exact command-routed host for the unchanged T247 policy.

The calibration graph runs for the frozen 250 confirmed ticks.  Its immutable
context selects one of six exact context routes once.  During locomotion, four
exact command vectors use their specialized graph; every other command uses
the selected context graph without narrowing the policy's command support.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

import numpy as np

from .constants import ACTION_DIM, CONTROL_PERIOD_NS
from .t247_x5_optimized import T247X5OptimizedTransaction
from .winner_v13_state_coherent import (
    CONTEXT_DIM,
    GraphAsset,
    GraphSpec,
    P30FitAsset,
    TensorSpec,
    WinnerV13ContractError,
    WinnerV13StateError,
    _StateCoherentGraphSession,
)

CONTRACT_ID = "open-duck-mini.t247.command-routed.115x14.v1"
T247_POLICY_SHA256 = "dadfb446ea7c720f274a15bc65e9171c2e74d715ccfaf58adbb408b6c1365a54"
T247_CALIBRATOR_SHA256 = (
    "0f3aebfd9946a6271fdb14adec3d68d556648f270984639d372c973a7d7dc576"
)
T247_COMMAND_MANIFEST_SHA256 = (
    "5621f7c6782a8346bf25f05ce7f0bc002acbe8e98872cf658f0d44773511b4cd"
)
T247_CONTEXT_ROUTER_SHA256 = (
    "3b1f406fba5147a3f38ec59fc7f9c8d42dd27fa7eeb54344f447c060eb95b284"
)
T247_P30_SHA256 = "a58db8ffc505d2bb64cba7f5618d0e2c65904fc9f9ac37b560a1231e090f5f4f"
T247_REFERENCE_SHA256 = (
    "8102d9cd139584816d807ca635bcca6d37fa6b3c455848e00395b6d565968212"
)
COMMAND_MANIFEST_SCHEMA = "open_duck_x5.t247_command_route_variant_manifest.v1"
CONTEXT_MANIFEST_SCHEMA = "open_duck_x5.t247_context_route_variant_manifest.v1"
ROUTE_NAMES = (
    "lower-cond0",
    "lower-cond1",
    "positive-cond0",
    "positive-cond1",
    "tail-cond0",
    "tail-cond1",
)
COMMAND_TAGS = (
    (0.0, "x000"),
    (0.074, "x074"),
    (0.077, "x077"),
    (0.08, "x080"),
)
ROUTER_OUTPUTS = (
    "t243_home_negative_tail_condition",
    "t149_negative_condition",
    "t162_positive_condition",
    "conditional_path_negative_condition",
    "t156_positive_condition",
)
_HASH_RE = re.compile(r"[0-9a-f]{64}")


def calibrator_spec() -> GraphSpec:
    return GraphSpec(
        observation=TensorSpec("obs", (1, 115)),
        previous_action=TensorSpec("previous_action", (1, ACTION_DIM)),
        hidden_in=TensorSpec("h_in", (1, 64)),
        action=TensorSpec("calibration_actions", (1, ACTION_DIM)),
        previous_action_out=TensorSpec("previous_action_out", (1, ACTION_DIM)),
        hidden_out=TensorSpec("h_out", (1, 64)),
    )


def locomotion_spec() -> GraphSpec:
    return GraphSpec(
        observation=TensorSpec("obs", (1, 115)),
        previous_action=TensorSpec("previous_action", (1, ACTION_DIM)),
        hidden_in=TensorSpec("h_in", (1, 64)),
        calibration_context=TensorSpec("calibration_context", (1, CONTEXT_DIM)),
        action=TensorSpec("continuous_actions", (1, ACTION_DIM)),
        previous_action_out=TensorSpec("previous_action_out", (1, ACTION_DIM)),
        hidden_out=TensorSpec("h_out", (1, 64)),
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _exact_hash(value: str, label: str) -> str:
    if not isinstance(value, str) or _HASH_RE.fullmatch(value) is None:
        raise WinnerV13ContractError(f"{label} must be exact lowercase SHA-256")
    return value


def _confined_file(root: Path, name: object, label: str) -> Path:
    if not isinstance(name, str) or not name or Path(name).name != name:
        raise WinnerV13ContractError(f"{label} must be one plain file name")
    path = (root / name).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise WinnerV13ContractError(f"{label} is missing or outside its asset root")
    return path


def _receipt_matches(path: Path, entry: object, label: str) -> str:
    if not isinstance(entry, dict):
        raise WinnerV13ContractError(f"{label} manifest entry must be an object")
    expected_hash = _exact_hash(entry.get("sha256"), f"{label} hash")
    if entry.get("file") != path.name:
        raise WinnerV13ContractError(f"{label} manifest file name differs")
    if type(entry.get("bytes")) is not int or entry["bytes"] != path.stat().st_size:
        raise WinnerV13ContractError(f"{label} byte count differs")
    actual_hash = _sha256(path)
    if actual_hash != expected_hash:
        raise WinnerV13ContractError(f"{label} SHA-256 differs: {actual_hash}")
    return actual_hash


def route_from_predicates(values: tuple[bool, ...]) -> str:
    if len(values) != len(ROUTER_OUTPUTS):
        raise WinnerV13ContractError(
            f"expected {len(ROUTER_OUTPUTS)} route predicates, got {len(values)}"
        )
    tail, t149_conditional, t162_positive, t143_conditional, t156_positive = values
    if t149_conditional != t143_conditional:
        raise WinnerV13ContractError(
            "original conditional-path predicates disagree"
        )
    if t162_positive != t156_positive:
        raise WinnerV13ContractError(
            "original bounded-positive predicates disagree"
        )
    if tail and t162_positive:
        raise WinnerV13ContractError(
            "tail and bounded-positive predicates overlap"
        )
    regime = "tail" if tail else "positive" if t162_positive else "lower"
    return f"{regime}-cond{int(t149_conditional)}"


class T247CommandRouteCatalog:
    """Hash-verified external source and exact-command graph catalog."""

    def __init__(
        self,
        *,
        context_root: str | Path,
        command_root: str | Path,
        command_manifest_path: str | Path,
        command_manifest_sha256: str,
        context_router_sha256: str,
    ) -> None:
        self.context_root = Path(context_root).expanduser().resolve()
        self.command_root = Path(command_root).expanduser().resolve()
        self.command_manifest_path = Path(command_manifest_path).expanduser().resolve()
        if not self.context_root.is_dir() or not self.command_root.is_dir():
            raise WinnerV13ContractError("T247 route asset roots must be directories")
        if not self.command_manifest_path.is_file():
            raise FileNotFoundError(self.command_manifest_path)
        if not self.command_manifest_path.is_relative_to(self.command_root):
            raise WinnerV13ContractError(
                "command manifest must be inside the command asset root"
            )
        expected_manifest_hash = _exact_hash(
            command_manifest_sha256,
            "command manifest hash",
        )
        self.command_manifest_sha256 = _sha256(self.command_manifest_path)
        if self.command_manifest_sha256 != expected_manifest_hash:
            raise WinnerV13ContractError(
                "command manifest SHA-256 differs: "
                f"{self.command_manifest_sha256}"
            )
        expected_router_hash = _exact_hash(
            context_router_sha256,
            "context router hash",
        )
        with self.command_manifest_path.open(encoding="utf-8") as handle:
            command_manifest = json.load(handle)
        if not isinstance(command_manifest, dict):
            raise WinnerV13ContractError("command manifest root must be an object")
        if command_manifest.get("schema_version") != COMMAND_MANIFEST_SCHEMA:
            raise WinnerV13ContractError("command manifest schema differs")
        if command_manifest.get("source_policy_sha256") != T247_POLICY_SHA256:
            raise WinnerV13ContractError("command manifest source policy differs")
        if command_manifest.get("routes") != list(ROUTE_NAMES):
            raise WinnerV13ContractError("command manifest routes differ")
        if command_manifest.get("commands_m_s") != [value for value, _ in COMMAND_TAGS]:
            raise WinnerV13ContractError("command manifest command set differs")
        if command_manifest.get("generated_models") != 24:
            raise WinnerV13ContractError("command manifest must contain 24 models")
        if command_manifest.get("fallback_rule") != (
            "retain each source context route for every other valid command"
        ):
            raise WinnerV13ContractError("command manifest fallback rule differs")
        if command_manifest.get("policy_inputs") != [
            "obs",
            "previous_action",
            "h_in",
            "calibration_context",
        ] or command_manifest.get("policy_outputs") != [
            "continuous_actions",
            "previous_action_out",
            "h_out",
        ]:
            raise WinnerV13ContractError("command manifest policy ABI differs")

        context_receipt = command_manifest.get("context_manifest")
        if not isinstance(context_receipt, dict):
            raise WinnerV13ContractError("context manifest receipt is missing")
        context_manifest_path = _confined_file(
            self.context_root,
            context_receipt.get("file"),
            "context manifest",
        )
        expected_context_hash = _exact_hash(
            context_receipt.get("sha256"),
            "context manifest hash",
        )
        if _sha256(context_manifest_path) != expected_context_hash:
            raise WinnerV13ContractError("context manifest SHA-256 differs")
        with context_manifest_path.open(encoding="utf-8") as handle:
            context_manifest = json.load(handle)
        if not isinstance(context_manifest, dict):
            raise WinnerV13ContractError("context manifest root must be an object")
        if context_manifest.get("schema_version") != CONTEXT_MANIFEST_SCHEMA:
            raise WinnerV13ContractError("context manifest schema differs")
        if context_manifest.get("routes") != list(ROUTE_NAMES):
            raise WinnerV13ContractError("context manifest routes differ")
        source_policy = context_manifest.get("source_policy")
        if not isinstance(source_policy, dict) or (
            source_policy.get("sha256") != T247_POLICY_SHA256
        ):
            raise WinnerV13ContractError("context manifest source policy differs")
        context_entries = {
            entry.get("name"): entry
            for entry in context_manifest.get("generated", [])
            if isinstance(entry, dict) and isinstance(entry.get("name"), str)
        }
        if set(ROUTE_NAMES).difference(context_entries):
            raise WinnerV13ContractError("context manifest is missing source routes")
        router_entry = context_entries.get("router")
        if not isinstance(router_entry, dict):
            raise WinnerV13ContractError("context manifest router is missing")
        self.router_path = _confined_file(
            self.context_root,
            router_entry.get("file"),
            "context router",
        )
        router_hash = _receipt_matches(
            self.router_path,
            router_entry,
            "context router",
        )
        if router_hash != expected_router_hash:
            raise WinnerV13ContractError("context router allowlist hash differs")
        self.router_sha256 = router_hash

        sources = command_manifest.get("sources")
        generated = command_manifest.get("generated")
        if not isinstance(sources, dict) or not isinstance(generated, dict):
            raise WinnerV13ContractError("command model maps are missing")
        expected_generated = {
            f"{route}-{tag}" for route in ROUTE_NAMES for _, tag in COMMAND_TAGS
        }
        if set(sources) != set(ROUTE_NAMES) or set(generated) != expected_generated:
            raise WinnerV13ContractError("command model key set differs")

        spec = locomotion_spec()
        self._assets: dict[tuple[str, str], GraphAsset] = {}
        for route in ROUTE_NAMES:
            source_entry = sources[route]
            source_path = _confined_file(
                self.context_root,
                source_entry.get("file") if isinstance(source_entry, dict) else None,
                f"source route {route}",
            )
            source_hash = _receipt_matches(
                source_path,
                source_entry,
                f"source route {route}",
            )
            context_entry = context_entries[route]
            if (
                context_entry.get("file") != source_path.name
                or context_entry.get("sha256") != source_hash
                or context_entry.get("bytes") != source_path.stat().st_size
            ):
                raise WinnerV13ContractError(
                    f"source route {route} differs between manifests"
                )
            self._assets[(route, "fallback")] = GraphAsset(
                source_path,
                spec,
                frozenset({source_hash}),
            )
            for command, tag in COMMAND_TAGS:
                name = f"{route}-{tag}"
                entry = generated[name]
                command_path = _confined_file(
                    self.command_root,
                    entry.get("file") if isinstance(entry, dict) else None,
                    f"command route {name}",
                )
                command_hash = _receipt_matches(
                    command_path,
                    entry,
                    f"command route {name}",
                )
                if entry.get("route") != route or entry.get("command_x_m_s") != command:
                    raise WinnerV13ContractError(
                        f"command route {name} metadata differs"
                    )
                self._assets[(route, tag)] = GraphAsset(
                    command_path,
                    spec,
                    frozenset({command_hash}),
                )
        if len(self._assets) != 30:
            raise WinnerV13ContractError("exactly 30 route graph assets are required")

    @property
    def asset_count(self) -> int:
        return len(self._assets)

    def graph_asset(self, route: str, tag: str) -> GraphAsset:
        try:
            return self._assets[(route, tag)]
        except KeyError as exc:
            raise WinnerV13ContractError(
                f"unknown T247 command route: {route}/{tag}"
            ) from exc


class _T247ContextRouter:
    def __init__(
        self,
        catalog: T247CommandRouteCatalog,
        *,
        warmup_runs: int,
    ) -> None:
        if type(warmup_runs) is not int or warmup_runs < 0:
            raise WinnerV13ContractError("router warmup runs must be non-negative")
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
            str(catalog.router_path),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        if self.session.get_providers() != ["CPUExecutionProvider"]:
            raise WinnerV13ContractError("context router requires CPUExecutionProvider")
        inputs = [
            (value.name, tuple(value.shape), value.type)
            for value in self.session.get_inputs()
        ]
        outputs = [
            (value.name, tuple(value.shape), value.type)
            for value in self.session.get_outputs()
        ]
        expected_outputs = [
            (name, (1, 1), "tensor(bool)") for name in ROUTER_OUTPUTS
        ]
        if inputs != [("calibration_context", (1, CONTEXT_DIM), "tensor(float)")]:
            raise WinnerV13ContractError(f"context router input ABI differs: {inputs}")
        if outputs != expected_outputs:
            raise WinnerV13ContractError(f"context router output ABI differs: {outputs}")
        self._context = np.zeros((1, CONTEXT_DIM), dtype=np.float32)
        for _ in range(warmup_runs):
            self.session.run(
                list(ROUTER_OUTPUTS),
                {"calibration_context": self._context},
            )

    def select(self, context: np.ndarray) -> str:
        if (
            not isinstance(context, np.ndarray)
            or context.shape != (CONTEXT_DIM,)
            or context.dtype != np.dtype(np.float32)
            or not bool(np.isfinite(context).all())
        ):
            raise WinnerV13ContractError(
                "calibration context must be finite float32 shape (64,)"
            )
        np.copyto(self._context[0], context)
        outputs = self.session.run(
            list(ROUTER_OUTPUTS),
            {"calibration_context": self._context},
        )
        predicates = tuple(bool(output.item()) for output in outputs)
        return route_from_predicates(predicates)


class T247CommandRouteTransaction(T247X5OptimizedTransaction):
    """Transactional T247 host with exact context and command graph routing."""

    def __init__(
        self,
        *,
        calibrator: GraphAsset,
        catalog: T247CommandRouteCatalog,
        p30_fit: P30FitAsset,
        reference_table_path: str | Path,
        enabled: bool = False,
        warmup_runs: int = 1,
        phase_frequency_factor_offset: float = 0.0,
    ) -> None:
        if not isinstance(catalog, T247CommandRouteCatalog):
            raise WinnerV13ContractError("a verified T247 route catalog is required")
        super().__init__(
            calibrator=calibrator,
            locomotion=catalog.graph_asset("lower-cond0", "fallback"),
            p30_fit=p30_fit,
            reference_table_path=reference_table_path,
            enabled=enabled,
            warmup_runs=warmup_runs,
            phase_frequency_factor_offset=phase_frequency_factor_offset,
        )
        effective_warmup = warmup_runs if enabled else 0
        self.catalog = catalog
        self._router = _T247ContextRouter(
            catalog,
            warmup_runs=effective_warmup,
        )
        self._bootstrap_locomotion = self._locomotion
        self._sessions: dict[tuple[str, str], _StateCoherentGraphSession] = {}
        self._observation_views: dict[
            _StateCoherentGraphSession,
            np.ndarray,
        ] = {}
        for route in ROUTE_NAMES:
            for tag in ("fallback", *(value for _, value in COMMAND_TAGS)):
                key = (route, tag)
                if key == ("lower-cond0", "fallback"):
                    session = self._bootstrap_locomotion
                else:
                    session = _StateCoherentGraphSession(
                        catalog.graph_asset(route, tag),
                        stage="locomotion",
                        warmup_runs=effective_warmup,
                    )
                    observation = session._observation[0]
                    session.bind_trusted_observation(observation)
                    session.stage = session.stage_bound_action_validated
                    self._observation_views[session] = observation
                self._sessions[key] = session
        if len(self._sessions) != 30:
            raise WinnerV13ContractError("exactly 30 route sessions are required")
        self._selected_context_route: str | None = None
        self._selected_command_route: str | None = None
        self._route_switches = 0
        self._fallback_ticks = 0

    @property
    def selected_context_route(self) -> str | None:
        return self._selected_context_route

    @property
    def selected_command_route(self) -> str | None:
        return self._selected_command_route

    @property
    def route_switches(self) -> int:
        return self._route_switches

    @property
    def fallback_ticks(self) -> int:
        return self._fallback_ticks

    @staticmethod
    def _tag_for_commands(commands: np.ndarray) -> str:
        if (
            not isinstance(commands, np.ndarray)
            or commands.shape != (7,)
            or commands.dtype != np.dtype(np.float64)
        ):
            raise WinnerV13ContractError(
                "T247 routed commands must be float64 shape (7,)"
            )
        for index in range(1, 7):
            if float(commands[index]) != 0.0:
                return "fallback"
        x = float(commands[0])
        if x == 0.0:
            return "x000" if math.copysign(1.0, x) > 0.0 else "fallback"
        if x == 0.074:
            return "x074"
        if x == 0.077:
            return "x077"
        if x == 0.08:
            return "x080"
        return "fallback"

    def _select_command_session(self, commands: np.ndarray) -> None:
        route = self._selected_context_route
        if route is None:
            raise WinnerV13StateError("context route has not been selected")
        tag = self._tag_for_commands(commands)
        selected = self._sessions[(route, tag)]
        current = self._locomotion
        if selected is not current:
            if current._pending or selected._pending:
                raise WinnerV13StateError("cannot switch a staged route session")
            if not selected._handoff_initialized:
                raise WinnerV13StateError("selected route session has no handoff state")
            np.copyto(selected._previous_action, current._previous_action)
            np.copyto(selected._hidden_in, current._hidden_in)
            self._locomotion = selected
            self.assembler.observation = self._observation_views[selected]
            self._route_switches += 1
        self._selected_command_route = tag
        if tag == "fallback":
            self._fallback_ticks += 1

    def confirm_calibration_handoff(self, confirmed_success: object) -> None:
        try:
            super().confirm_calibration_handoff(confirmed_success)
            bootstrap_view = self.assembler.observation
            self._observation_views[self._bootstrap_locomotion] = bootstrap_view
            context = self._calibration_context
            route = self._router.select(context)
            previous_action = self._calibrator.committed_previous_action
            for tag in ("fallback", *(value for _, value in COMMAND_TAGS)):
                session = self._sessions[(route, tag)]
                if not session._handoff_initialized:
                    session.initialize_locomotion_handoff(previous_action, context)
            selected = self._sessions[(route, "fallback")]
            self._selected_context_route = route
            self._selected_command_route = "fallback"
            self._locomotion = selected
            self.assembler.observation = self._observation_views[selected]
        except Exception as exc:
            self._fault(f"command-route handoff failed: {exc}")
            raise

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
        if self._handoff_complete and not self.pending:
            try:
                self._select_command_session(commands)
            except Exception as exc:
                self._fault(f"command-route selection failed: {exc}")
                raise
        return super().stage_tick(
            tick_index=tick_index,
            logical_period_ns=logical_period_ns,
            servo_sample_tick_index=servo_sample_tick_index,
            imu_sample_tick_index=imu_sample_tick_index,
            contacts_sample_tick_index=contacts_sample_tick_index,
            gyro_rad_s=gyro_rad_s,
            acceleration_m_s2=acceleration_m_s2,
            commands=commands,
            positions_rad=positions_rad,
            velocities_rad_s=velocities_rad_s,
            foot_contacts=foot_contacts,
            servo_stale=servo_stale,
            imu_stale=imu_stale,
            contacts_stale=contacts_stale,
            soft_offsets_rad=soft_offsets_rad,
        )


def exact_control_period_ns() -> int:
    """Expose the frozen period without importing the hardware runtime."""

    return CONTROL_PERIOD_NS
