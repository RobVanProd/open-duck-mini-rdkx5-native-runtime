from __future__ import annotations

import math

import numpy as np
import pytest

from open_duck_x5.constants import ACTION_DIM, CONTROL_FREQUENCY_HZ, HOME_RAD
from open_duck_x5.contract import (
    ActionPipeline,
    ObservationAssembler,
    PhaseClock,
    StaleObservationError,
)


def _inputs() -> dict[str, object]:
    return {
        "gyro_rad_s": np.array([1.0, 2.0, 3.0]),
        "acceleration_m_s2": np.array([4.0, 5.0, 6.0]),
        "commands": np.arange(7, dtype=np.float64) + 7,
        "positions_rad": HOME_RAD + np.arange(ACTION_DIM) / 10.0,
        "velocities_rad_s": np.arange(ACTION_DIM, dtype=np.float64) + 20,
        "previous_motor_target_rad": np.arange(ACTION_DIM, dtype=np.float64) + 30,
        "foot_contacts": np.array([1.0, 0.0]),
        "phase": np.array([0.25, -0.75]),
        "servo_stale": np.zeros(ACTION_DIM, dtype=np.bool_),
        "imu_stale": False,
        "contacts_stale": False,
    }


def test_observation_field_map_is_exactly_101_elements() -> None:
    assembler = ObservationAssembler()
    action_3 = np.arange(ACTION_DIM, dtype=np.float32) + 100
    action_2 = np.arange(ACTION_DIM, dtype=np.float32) + 200
    action_1 = np.arange(ACTION_DIM, dtype=np.float32) + 300
    assembler.commit_action(action_3)
    assembler.commit_action(action_2)
    assembler.commit_action(action_1)

    values = _inputs()
    obs = assembler.build(**values)
    assert obs.shape == (101,)
    np.testing.assert_array_equal(obs[0:3], values["gyro_rad_s"])
    np.testing.assert_array_equal(obs[3:6], values["acceleration_m_s2"])
    np.testing.assert_array_equal(obs[6:13], values["commands"])
    np.testing.assert_allclose(obs[13:27], np.arange(ACTION_DIM) / 10.0)
    np.testing.assert_allclose(obs[27:41], np.arange(ACTION_DIM) * 0.05 + 1.0)
    np.testing.assert_array_equal(obs[41:55], action_1)
    np.testing.assert_array_equal(obs[55:69], action_2)
    np.testing.assert_array_equal(obs[69:83], action_3)
    np.testing.assert_array_equal(obs[83:97], values["previous_motor_target_rad"])
    np.testing.assert_array_equal(obs[97:99], values["foot_contacts"])
    np.testing.assert_array_equal(obs[99:101], values["phase"])


@pytest.mark.parametrize("field", ["servo_stale", "imu_stale", "contacts_stale"])
def test_observation_rejects_every_stale_required_source(field: str) -> None:
    values = _inputs()
    if field == "servo_stale":
        values[field][4] = True
    else:
        values[field] = True
    with pytest.raises(StaleObservationError):
        ObservationAssembler().build(**values)


def test_action_pipeline_preserves_slew_head_overlay_offsets_and_monitor() -> None:
    pipeline = ActionPipeline()
    action = np.ones(ACTION_DIM, dtype=np.float32)
    commands = np.zeros(7, dtype=np.float64)
    commands[3:7] = [0.01, 0.02, 0.03, 0.04]
    offsets = np.arange(ACTION_DIM, dtype=np.float64) / 1000.0
    physical = pipeline.apply(action, commands, offsets)

    max_step = 5.24 / CONTROL_FREQUENCY_HZ
    expected_sent = HOME_RAD + max_step
    expected_sent[5:9] += commands[3:7]
    np.testing.assert_allclose(pipeline.rate_limited_target_rad, HOME_RAD + max_step)
    np.testing.assert_allclose(pipeline.sent_target_rad, expected_sent)
    np.testing.assert_allclose(physical, expected_sent + offsets)
    np.testing.assert_allclose(pipeline.previous_motor_target_rad, expected_sent)
    np.testing.assert_allclose(
        pipeline.implied_velocity_rad_s, (expected_sent - HOME_RAD) * CONTROL_FREQUENCY_HZ
    )
    assert pipeline.over_envelope.all()


def test_phase_starts_at_legacy_zero_vector_then_advances_27_tick_period() -> None:
    phase = PhaseClock()
    np.testing.assert_array_equal(phase.value, [0.0, 0.0])
    phase.advance()
    np.testing.assert_allclose(
        phase.value, [math.cos(2 * math.pi / 27), math.sin(2 * math.pi / 27)]
    )
    for _ in range(26):
        phase.advance()
    np.testing.assert_allclose(phase.value, [1.0, 0.0], atol=1e-12)
