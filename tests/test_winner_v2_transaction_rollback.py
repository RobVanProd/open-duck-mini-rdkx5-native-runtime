from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from open_duck_x5.constants import ACTION_DIM, CONTROL_PERIOD_NS, HOME_RAD
from open_duck_x5.winner_v2 import (
    WinnerV2ContractError,
    WinnerV2SendError,
    WinnerV2TickTransaction,
)


class _Reference:
    def lookup_into(
        self,
        command3: np.ndarray,
        phase_index: int,
        output: np.ndarray,
    ) -> None:
        del command3
        output.fill(np.float32(phase_index / 100.0))


class _Policy:
    def __init__(self) -> None:
        self.previous_action = np.zeros(ACTION_DIM, dtype=np.float32)
        self.action = np.zeros(ACTION_DIM, dtype=np.float32)
        self.staged_state = np.zeros(ACTION_DIM, dtype=np.float32)
        self.pending = False

    @property
    def action_view(self) -> np.ndarray:
        return self.action

    def stage(self, observation: np.ndarray) -> np.ndarray:
        assert observation.shape == (115,)
        assert not self.pending
        np.add(self.previous_action, np.float32(0.01), out=self.action)
        np.copyto(self.staged_state, self.action)
        self.pending = True
        return self.action

    def commit_staged(self) -> None:
        assert self.pending
        np.copyto(self.previous_action, self.staged_state)
        self.pending = False

    def discard_staged(self) -> None:
        self.pending = False


class _Observer:
    def __init__(self) -> None:
        self.value = HOME_RAD.astype(np.float64).copy()
        self.staged_value = self.value.copy()
        self.pending = False
        self.fail_next_stage = False

    @property
    def value_view(self) -> np.ndarray:
        return self.value

    def stage_confirmed_target(self, sent_logical_target_rad: np.ndarray) -> None:
        assert not self.pending
        np.copyto(self.staged_value, sent_logical_target_rad)
        self.pending = True
        if self.fail_next_stage:
            self.fail_next_stage = False
            raise WinnerV2ContractError("injected observer staging failure")

    def commit_staged(self) -> None:
        assert self.pending
        np.copyto(self.value, self.staged_value)
        self.pending = False

    def discard_staged(self) -> None:
        self.pending = False


def _transaction() -> WinnerV2TickTransaction:
    return WinnerV2TickTransaction(
        policy=_Policy(),  # type: ignore[arg-type]
        observer=_Observer(),  # type: ignore[arg-type]
        reference=_Reference(),  # type: ignore[arg-type]
    )


def _tick_inputs(tick: int) -> dict[str, Any]:
    return {
        "tick_index": tick,
        "logical_period_ns": CONTROL_PERIOD_NS,
        "servo_sample_tick_index": tick,
        "imu_sample_tick_index": tick,
        "contacts_sample_tick_index": tick,
        "gyro_rad_s": np.zeros(3, dtype=np.float64),
        "acceleration_m_s2": np.asarray([0.0, 0.0, 9.81], dtype=np.float64),
        "commands": np.asarray(
            [0.08, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float64
        ),
        "positions_rad": HOME_RAD.copy(),
        "velocities_rad_s": np.zeros(ACTION_DIM, dtype=np.float64),
        "foot_contacts": np.ones(2, dtype=np.float64),
        "servo_stale": np.zeros(ACTION_DIM, dtype=np.bool_),
        "imu_stale": False,
        "contacts_stale": False,
        "soft_offsets_rad": np.zeros(ACTION_DIM, dtype=np.float64),
    }


def _advance(transaction: WinnerV2TickTransaction, ticks: int) -> None:
    for tick in range(ticks):
        transaction.stage_tick(**_tick_inputs(tick))
        transaction.complete_send(write_succeeded=True)


def _committed_snapshot(transaction: WinnerV2TickTransaction) -> dict[str, Any]:
    policy = transaction.policy
    observer = transaction.observer
    return {
        "ticks": transaction.committed_ticks,
        "phase_index": transaction.phase.index,
        "phase": transaction.phase.value.copy(),
        "last_action": transaction.assembler.last_action.copy(),
        "action_minus_2": transaction.assembler.action_minus_2.copy(),
        "action_minus_3": transaction.assembler.action_minus_3.copy(),
        "deferred_action": transaction.assembler._deferred_action.copy(),
        "policy_previous": policy.previous_action.copy(),
        "logical_target": (
            transaction.action_pipeline.previous_logical_target_view.copy()
        ),
        "observer": observer.value_view.copy(),
    }


def _assert_snapshot_equal(left: dict[str, Any], right: dict[str, Any]) -> None:
    assert left.keys() == right.keys()
    for key in left:
        if isinstance(left[key], np.ndarray):
            np.testing.assert_array_equal(left[key], right[key], err_msg=key)
        else:
            assert left[key] == right[key], key


def _assert_staged_equal(
    transaction: WinnerV2TickTransaction,
    control: WinnerV2TickTransaction,
) -> None:
    np.testing.assert_array_equal(
        transaction.observation_view,
        control.observation_view,
    )
    np.testing.assert_array_equal(
        transaction.normalized_action_view,
        control.normalized_action_view,
    )
    np.testing.assert_array_equal(
        transaction.logical_target_view,
        control.logical_target_view,
    )
    np.testing.assert_array_equal(
        transaction.physical_target_view,
        control.physical_target_view,
    )


@pytest.mark.parametrize("acknowledgement", [False, None, 1, np.bool_(True)])
def test_failed_or_ambiguous_send_rolls_back_mature_nonzero_chain(
    acknowledgement: object,
) -> None:
    transaction = _transaction()
    control = _transaction()
    _advance(transaction, 6)
    _advance(control, 6)
    before = _committed_snapshot(transaction)

    transaction.stage_tick(**_tick_inputs(6))
    with pytest.raises(WinnerV2SendError, match="was not confirmed"):
        transaction.complete_send(write_succeeded=acknowledgement)  # type: ignore[arg-type]

    assert transaction.pending is False
    _assert_snapshot_equal(before, _committed_snapshot(transaction))

    transaction.stage_tick(**_tick_inputs(6))
    control.stage_tick(**_tick_inputs(6))
    _assert_staged_equal(transaction, control)
    transaction.complete_send(write_succeeded=True)
    control.complete_send(write_succeeded=True)
    _assert_snapshot_equal(
        _committed_snapshot(transaction),
        _committed_snapshot(control),
    )


def test_post_inference_observer_failure_discards_every_staged_subsystem() -> None:
    transaction = _transaction()
    control = _transaction()
    _advance(transaction, 6)
    _advance(control, 6)
    before = _committed_snapshot(transaction)
    observer = transaction.observer
    observer.fail_next_stage = True

    with pytest.raises(WinnerV2ContractError, match="observer staging failure"):
        transaction.stage_tick(**_tick_inputs(6))

    assert transaction.pending is False
    assert transaction.policy.pending is False
    assert transaction.action_pipeline.pending is False
    assert observer.pending is False
    _assert_snapshot_equal(before, _committed_snapshot(transaction))

    transaction.stage_tick(**_tick_inputs(6))
    control.stage_tick(**_tick_inputs(6))
    _assert_staged_equal(transaction, control)
    transaction.complete_send(write_succeeded=True)
    control.complete_send(write_succeeded=True)
    _assert_snapshot_equal(
        _committed_snapshot(transaction),
        _committed_snapshot(control),
    )
