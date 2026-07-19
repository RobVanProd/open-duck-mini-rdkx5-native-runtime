from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import open_duck_x5.winner_v2 as winner_v2
from open_duck_x5.constants import ACTION_DIM, CONTROL_PERIOD_NS, HOME_RAD
from open_duck_x5.winner_v2 import (
    P30BridgeObserver,
    ProjectedReferenceTable,
    WinnerV2ActionPipeline,
    WinnerV2ContractError,
    WinnerV2OnnxPolicy,
    WinnerV2PhaseClock,
    WinnerV2SendError,
    WinnerV2StateError,
    WinnerV2TickTransaction,
    validate_winner_v2_command,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_fit(tmp_path: Path, *, combined: dict[str, object] | None = None) -> Path:
    joints: dict[str, object] = {}
    if combined is not None:
        joints["left_hip_yaw"] = {"combined": combined}
    path = tmp_path / "fit.json"
    path.write_text(json.dumps({"primary": {"joints": joints}}), encoding="utf-8")
    return path


def _make_reference(tmp_path: Path) -> Path:
    commands = np.full((240, 3), 10.0, dtype=np.float32)
    commands[0] = [0.08, 0.0, 0.0]
    actions = np.zeros((240, 27, 14), dtype=np.float32)
    for phase in range(27):
        actions[0, phase] = np.float32(phase / 100.0)
    path = tmp_path / "reference.npz"
    np.savez(path, commands=commands, actions=actions)
    return path


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
    def __init__(self, *, divergent_state: bool = False) -> None:
        self.binding = FakeBinding()
        self.divergent_state = divergent_state
        self.options = None
        self.calls = 0

    def get_inputs(self) -> list[FakeNode]:
        return [FakeNode("obs", [1, 115]), FakeNode("previous_action", [1, 14])]

    def get_outputs(self) -> list[FakeNode]:
        return [
            FakeNode("continuous_actions", [1, 14]),
            FakeNode("previous_action_out", [1, 14]),
        ]

    def get_providers(self) -> list[str]:
        return ["CPUExecutionProvider"]

    def io_binding(self) -> FakeBinding:
        return self.binding

    def run_with_iobinding(self, binding: FakeBinding) -> None:
        self.calls += 1
        obs = binding.inputs["obs"]
        previous = binding.inputs["previous_action"]
        action = binding.outputs["continuous_actions"]
        state = binding.outputs["previous_action_out"]
        if abs(float(obs[0, 6])) <= 0.01:
            action.fill(0.0)
        else:
            np.add(previous, np.float32(0.01), out=action)
        np.copyto(state, action)
        if self.divergent_state:
            state[0, 2] += np.float32(0.001)


def _install_fake_ort(
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
        _path: str,
        *,
        sess_options: FakeSessionOptions,
        providers: list[str],
    ) -> FakeSession:
        assert providers == ["CPUExecutionProvider"]
        session.options = sess_options
        return session

    module = SimpleNamespace(
        InferenceSession=make_session,
        OrtValue=FakeOrtValue,
        SessionOptions=FakeSessionOptions,
        ExecutionMode=SimpleNamespace(ORT_SEQUENTIAL="ORT_SEQUENTIAL"),
        GraphOptimizationLevel=SimpleNamespace(ORT_ENABLE_ALL="ORT_ENABLE_ALL"),
    )
    monkeypatch.setitem(sys.modules, "onnxruntime", module)


def _make_policy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    session: FakeSession | None = None,
) -> WinnerV2OnnxPolicy:
    model = tmp_path / "winner.onnx"
    model.write_bytes(b"fake winner-v2 policy")
    monkeypatch.setattr(
        winner_v2,
        "WINNER_V2_POLICY_CANDIDATE_SHA256",
        frozenset({_sha256(model)}),
    )
    monkeypatch.setattr(
        winner_v2,
        "WINNER_V2_SELECTED_POLICY_SHA256",
        _sha256(model),
    )
    _install_fake_ort(monkeypatch, session or FakeSession())
    return WinnerV2OnnxPolicy(model, warmup_runs=1)


def _make_transaction(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> WinnerV2TickTransaction:
    fit = _make_fit(tmp_path)
    reference = _make_reference(tmp_path)
    monkeypatch.setattr(winner_v2, "WINNER_V2_P30_FIT_SHA256", _sha256(fit))
    monkeypatch.setattr(
        winner_v2, "WINNER_V2_REFERENCE_TABLE_SHA256", _sha256(reference)
    )
    return WinnerV2TickTransaction(
        policy=_make_policy(monkeypatch, tmp_path),
        observer=P30BridgeObserver(fit),
        reference=ProjectedReferenceTable(reference),
    )


def _tick_inputs(tick: int, *, command_x: float = 0.08) -> dict[str, object]:
    return {
        "tick_index": tick,
        "logical_period_ns": CONTROL_PERIOD_NS,
        "servo_sample_tick_index": tick,
        "imu_sample_tick_index": tick,
        "contacts_sample_tick_index": tick,
        "gyro_rad_s": np.zeros(3, dtype=np.float64),
        "acceleration_m_s2": np.asarray([0.0, 0.0, 9.81], dtype=np.float64),
        "commands": np.asarray(
            [command_x, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float64
        ),
        "positions_rad": HOME_RAD.copy(),
        "velocities_rad_s": np.zeros(ACTION_DIM, dtype=np.float64),
        "foot_contacts": np.ones(2, dtype=np.float64),
        "servo_stale": np.zeros(ACTION_DIM, dtype=np.bool_),
        "imu_stale": False,
        "contacts_stale": False,
        "soft_offsets_rad": np.zeros(ACTION_DIM, dtype=np.float64),
    }


def test_phase_resets_one_zero_and_observes_before_confirmed_advance() -> None:
    phase = WinnerV2PhaseClock()
    np.testing.assert_array_equal(phase.value, [1.0, 0.0])
    assert phase.index == 0
    phase.advance_confirmed()
    np.testing.assert_allclose(
        phase.value,
        [np.cos(2.0 * np.pi / 27.0), np.sin(2.0 * np.pi / 27.0)],
        atol=1e-7,
    )
    assert phase.index == 1
    with pytest.raises(WinnerV2ContractError, match="offset=0.0"):
        WinnerV2PhaseClock(frequency_factor_offset=0.01)


@pytest.mark.parametrize("x", [0.0, 0.074, 0.077, 0.080])
def test_command_support_accepts_only_frozen_forward_band(x: float) -> None:
    command = np.asarray([x, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    np.testing.assert_array_equal(validate_winner_v2_command(command), command)


@pytest.mark.parametrize(
    "command",
    [
        [0.01, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        [0.081, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        [0.08, 0.001, 0.0, 0.0, 0.0, 0.0, 0.0],
        [0.08, 0.0, 0.0, 0.1, 0.0, 0.0, 0.0],
    ],
)
def test_command_support_rejects_every_untrained_axis_or_gap(command: list[float]) -> None:
    with pytest.raises(WinnerV2ContractError):
        validate_winner_v2_command(np.asarray(command))


def test_reference_lookup_is_zero_at_x0_and_current_phase_at_x008(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = _make_reference(tmp_path)
    monkeypatch.setattr(
        winner_v2, "WINNER_V2_REFERENCE_TABLE_SHA256", _sha256(path)
    )
    table = ProjectedReferenceTable(path)
    output = np.empty(14, dtype=np.float32)
    table.lookup_into(np.zeros(3, dtype=np.float32), 7, output)
    np.testing.assert_array_equal(output, np.zeros(14, dtype=np.float32))
    table.lookup_into(np.asarray([0.08, 0.0, 0.0], dtype=np.float32), 7, output)
    np.testing.assert_array_equal(output, np.full(14, 0.07, dtype=np.float32))


def test_p30_observer_stages_without_mutation_then_commits_exact_model(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = _make_fit(
        tmp_path,
        combined={"delay_ticks": 0, "tau_s": 0.01, "velocity_limit_rad_s": 1.5},
    )
    monkeypatch.setattr(winner_v2, "WINNER_V2_P30_FIT_SHA256", _sha256(path))
    observer = P30BridgeObserver(path)
    before = observer.value_view.copy()
    target = before.copy()
    target[0] += 1.0

    observer.stage_confirmed_target(target)
    np.testing.assert_array_equal(observer.value_view, before)
    observer.commit_staged()

    alpha = 1.0 - np.exp(-0.02 / 0.01)
    expected_step = min(1.5 * 0.02, float(alpha))
    assert observer.value_view[0] == pytest.approx(before[0] + expected_step)
    np.testing.assert_array_equal(observer.value_view[1:], target[1:])


def test_policy_state_is_staged_and_committed_only_explicitly(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    policy = _make_policy(monkeypatch, tmp_path)
    observation = np.zeros(115, dtype=np.float32)
    observation[6] = 0.08
    action = policy.stage(observation)
    np.testing.assert_array_equal(action, np.full(14, 0.01, dtype=np.float32))
    np.testing.assert_array_equal(policy.previous_action_view, np.zeros(14))
    with pytest.raises(WinnerV2StateError, match="already"):
        policy.stage(observation)
    policy.commit_staged()
    np.testing.assert_array_equal(
        policy.previous_action_view, np.full(14, 0.01, dtype=np.float32)
    )


def test_policy_rejects_divergent_action_and_recurrent_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    with pytest.raises(WinnerV2ContractError, match="action/state chain diverged"):
        _make_policy(monkeypatch, tmp_path, session=FakeSession(divergent_state=True))


def test_transaction_matches_115_map_and_commits_all_state_after_send(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    transaction = _make_transaction(monkeypatch, tmp_path)
    home32 = HOME_RAD.astype(np.float32)
    target = transaction.stage_tick(**_tick_inputs(0))

    assert transaction.pending
    assert transaction.committed_ticks == 0
    assert transaction.phase.index == 0
    np.testing.assert_array_equal(transaction.observation_view[41:83], 0.0)
    np.testing.assert_array_equal(transaction.observation_view[83:97], home32)
    np.testing.assert_array_equal(transaction.observation_view[99:101], [1.0, 0.0])
    np.testing.assert_array_equal(transaction.observation_view[101:115], 0.0)
    np.testing.assert_allclose(target, home32 + np.float32(0.01 * 0.25))
    np.testing.assert_array_equal(transaction.policy.previous_action_view, 0.0)
    np.testing.assert_array_equal(transaction.observer.value_view, home32)

    transaction.complete_send(write_succeeded=True)
    assert transaction.committed_ticks == 1
    assert transaction.phase.index == 1
    np.testing.assert_array_equal(
        transaction.policy.previous_action_view, np.full(14, 0.01, dtype=np.float32)
    )
    np.testing.assert_array_equal(transaction.assembler.last_action, np.zeros(14))
    np.testing.assert_allclose(
        transaction.observer.value_view,
        home32.astype(np.float64) + 0.0025,
        atol=1e-8,
    )

    transaction.stage_tick(**_tick_inputs(1))
    np.testing.assert_array_equal(transaction.observation_view[41:83], np.zeros(42))
    np.testing.assert_allclose(
        transaction.observation_view[83:97], home32 + 0.0025, atol=1e-7
    )
    np.testing.assert_array_equal(
        transaction.observation_view[101:115], np.full(14, 0.01, dtype=np.float32)
    )
    transaction.complete_send(write_succeeded=True)
    transaction.stage_tick(**_tick_inputs(2))
    np.testing.assert_array_equal(
        transaction.observation_view[41:55], np.full(14, 0.01, dtype=np.float32)
    )
    np.testing.assert_array_equal(transaction.observation_view[55:83], np.zeros(28))


def test_failed_send_discards_every_staged_state_and_tick_can_be_retried(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    transaction = _make_transaction(monkeypatch, tmp_path)
    policy_before = transaction.policy.previous_action_view.copy()
    observer_before = transaction.observer.value_view.copy()
    target_before = transaction.action_pipeline.previous_logical_target_view.copy()
    phase_before = transaction.phase.value.copy()
    history_before = transaction.assembler.last_action.copy()

    transaction.stage_tick(**_tick_inputs(0))
    with pytest.raises(WinnerV2SendError, match="state unchanged"):
        transaction.complete_send(write_succeeded=False)

    assert not transaction.pending
    assert transaction.committed_ticks == 0
    np.testing.assert_array_equal(transaction.policy.previous_action_view, policy_before)
    np.testing.assert_array_equal(transaction.observer.value_view, observer_before)
    np.testing.assert_array_equal(
        transaction.action_pipeline.previous_logical_target_view, target_before
    )
    np.testing.assert_array_equal(transaction.phase.value, phase_before)
    np.testing.assert_array_equal(transaction.assembler.last_action, history_before)
    transaction.stage_tick(**_tick_inputs(0))


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("logical_period_ns", 10_000_000, "logical period"),
        ("imu_sample_tick_index", -1, "sample epochs"),
        ("contacts_sample_tick_index", 2, "sample epochs"),
        ("imu_stale", True, "stale"),
        ("contacts_stale", True, "stale"),
    ],
)
def test_transaction_fails_closed_on_timing_or_staleness(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    field: str,
    value: object,
    match: str,
) -> None:
    transaction = _make_transaction(monkeypatch, tmp_path)
    values = _tick_inputs(0)
    values[field] = value
    with pytest.raises(WinnerV2ContractError, match=match):
        transaction.stage_tick(**values)
    assert transaction.committed_ticks == 0
    assert not transaction.pending


def test_transaction_fails_closed_on_stale_servo_or_nonfinite_sensor(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    transaction = _make_transaction(monkeypatch, tmp_path)
    values = _tick_inputs(0)
    values["servo_stale"][4] = True
    with pytest.raises(WinnerV2ContractError, match="stale"):
        transaction.stage_tick(**values)

    values = _tick_inputs(0)
    values["gyro_rad_s"][1] = np.nan
    with pytest.raises(WinnerV2ContractError, match="non-finite"):
        transaction.stage_tick(**values)


def test_graph_rate_limit_and_legacy_limiter_are_assertions_not_filters() -> None:
    pipeline = WinnerV2ActionPipeline()
    offsets = np.zeros(14, dtype=np.float64)
    action = np.zeros(14, dtype=np.float32)
    action[2] = 0.2
    with pytest.raises(WinnerV2ContractError, match="graph-authoritative"):
        pipeline.stage(action, offsets)
    np.testing.assert_array_equal(
        pipeline.previous_logical_target_view, HOME_RAD.astype(np.float32)
    )

    pipeline = WinnerV2ActionPipeline()
    action.fill(1.0)
    with pytest.raises(WinnerV2ContractError, match="5.24.*not identity"):
        pipeline.stage(action, offsets)
    np.testing.assert_array_equal(
        pipeline.previous_logical_target_view, HOME_RAD.astype(np.float32)
    )


def test_wrong_fit_reference_and_policy_hashes_fail_before_use(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fit = _make_fit(tmp_path)
    with pytest.raises(WinnerV2ContractError, match="P30 fit SHA"):
        P30BridgeObserver(fit)

    reference = _make_reference(tmp_path)
    with pytest.raises(WinnerV2ContractError, match="reference-table SHA"):
        ProjectedReferenceTable(reference)

    model = tmp_path / "wrong.onnx"
    model.write_bytes(b"wrong")
    _install_fake_ort(monkeypatch, FakeSession())
    with pytest.raises(WinnerV2ContractError, match="policy SHA"):
        WinnerV2OnnxPolicy(model)


def test_audit_policy_hash_requires_explicit_offline_opt_in(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    model = tmp_path / "audit.onnx"
    model.write_bytes(b"audit-only winner-v2 policy")
    audit_hash = _sha256(model)
    monkeypatch.setattr(
        winner_v2, "WINNER_V2_POLICY_CANDIDATE_SHA256", frozenset({audit_hash})
    )
    monkeypatch.setattr(
        winner_v2, "WINNER_V2_SELECTED_POLICY_SHA256", "0" * 64
    )
    _install_fake_ort(monkeypatch, FakeSession())
    with pytest.raises(WinnerV2ContractError, match="unselected"):
        WinnerV2OnnxPolicy(model)
    policy = WinnerV2OnnxPolicy(model, warmup_runs=1, allow_audit_policy=True)
    assert policy.sha256 == audit_hash


def test_powered_off_com_template_is_exact_46_field_policy_packet() -> None:
    root = Path(__file__).resolve().parents[1]
    path = root / "docs" / "templates" / "real_build_torso_com_measurement_v2.json"
    assert _sha256(path) == (
        "d9abf072ec2e9123f5214c8678860a7e043e83d4fd6a0400f49c98e2f6f21137"
    )
    packet = json.loads(path.read_text(encoding="utf-8"))
    assert packet["schema_version"] == "real_build_torso_com_measurement.v2"
    assert [item["id"] for item in packet["components"]] == [
        "printed_torso_and_fasteners",
        "rdk_x5_board",
        "rdk_x5_thermal_and_mount",
        "rdk_x5_cables_and_adapters",
        "battery_cells_pack",
        "battery_bms_charger_wiring",
        "servo_bus_imu_power_hardware",
        "build_specific_covers_or_ballast",
    ]
    component_nulls = sum(
        value is None
        for component in packet["components"]
        for key, value in component.items()
        if key != "id"
    )
    coordinate_nulls = sum(
        value is None for value in packet["coordinate_contract"].values()
    )
    assert component_nulls == 40
    assert coordinate_nulls == 6


def test_direct_reaction_com_template_is_exact_policy_packet() -> None:
    root = Path(__file__).resolve().parents[1]
    path = (
        root
        / "docs"
        / "templates"
        / "real_build_torso_com_direct_reaction_template.json"
    )
    assert _sha256(path) == (
        "30229a80df15292bc36bcb143c28c46838bf826856ebd00cf156e2654c93af55"
    )
    packet = json.loads(path.read_text(encoding="utf-8"))
    assert packet["schema_version"] == (
        "real_build_torso_com_direct_reaction_measurement.v1"
    )
    assert packet["coordinate_contract"] == {
        "axis_sign_to_trunk_assembly_x": 1,
        "datum_description": "midpoint of the left and right hip-yaw rotation axes",
        "datum_origin_x_in_trunk_assembly_m": -0.019,
        "datum_origin_x_uncertainty_m": None,
        "physical_datum_evidence": None,
        "positive_x_description": (
            "robot forward/toe direction at deterministic home"
        ),
    }
    assert [trial["id"] for trial in packet["trials"]] == [
        "trial_1",
        "trial_2",
        "trial_3",
    ]
    missing = sum(
        value is None
        for section in (
            packet["apparatus"],
            packet["coordinate_contract"],
            packet["specimen_contract"],
        )
        for value in section.values()
    ) + sum(
        value is None
        for trial in packet["trials"]
        for key, value in trial.items()
        if key != "id"
    )
    assert missing == 30
