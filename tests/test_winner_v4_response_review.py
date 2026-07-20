from __future__ import annotations

import numpy as np
import pytest

from open_duck_x5.configuration_support import (
    AUTOMATIC_METHOD,
    PROFILE_SCHEMA_VERSION,
    ConfigurationSupportError,
)
from open_duck_x5.constants import CONTROL_FREQUENCY_HZ, JOINT_NAMES, SERVO_IDS
from open_duck_x5.response_context_review import (
    RESPONSE_CONTEXT_DIM,
    RESPONSE_CONTEXT_FIELDS,
    flatten_response_context,
)
from open_duck_x5.winner_v4_response_review import build_review


def _profile() -> dict[str, object]:
    return {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "source": {
            "method": AUTOMATIC_METHOD,
            "backend": "serial",
            "device": "/dev/ttyS1",
            "informational_only": False,
            "trace_sha256": "a" * 64,
            "metadata_sha256": "b" * 64,
            "configuration_sha256": "c" * 64,
            "policy_envelope_sha256": "d" * 64,
            "manual_measurements_used": False,
            "hardware_authorized": True,
            "motion_authorized": True,
            "configuration_calibration_authorized": True,
            "suspended_or_benched": True,
            "torque_off_confirmed": True,
        },
        "inventory": {
            "required_servo_ids": list(SERVO_IDS),
            "responding_servo_ids": list(SERVO_IDS),
            "imu_present": True,
            "contacts_present": True,
        },
        "sample_contract": {
            "frequency_hz": CONTROL_FREQUENCY_HZ,
            "tick_count": 2814,
            "complete": True,
            "stale_sample_count": 0,
            "transaction_failure_count": 0,
            "telemetry_drop_count": 0,
            "tick_period_p99_ms": 20.1,
            "tick_period_p99_9_ms": 20.2,
            "bus_total_max_ms": 4.0,
        },
        "joint_response": {
            name: {
                "delay_ticks": float(index),
                "gain_ratio": 0.90 + index * 0.001,
                "time_constant_s": 0.05 + index * 0.001,
                "tracking_p95_rad": 0.01 + index * 0.0001,
                "current_p95_a": 0.20 + index * 0.01,
            }
            for index, name in enumerate(JOINT_NAMES)
        },
        "body_response": {
            "pitch_rate_p95_rad_s": 0.2,
            "roll_rate_p95_rad_s": 0.3,
            "acceleration_norm_p95_m_s2": 9.81,
        },
    }


def test_field_order_and_values_match_policy_proposal() -> None:
    profile = _profile()
    context = flatten_response_context(profile)

    assert RESPONSE_CONTEXT_DIM == 73
    assert len(RESPONSE_CONTEXT_FIELDS) == 73
    assert context.dtype == np.float32
    assert context.flags.writeable is False
    assert context[:5].tolist() == pytest.approx([0.0, 0.9, 0.05, 0.01, 0.2])
    assert context[-3:].tolist() == pytest.approx([0.2, 0.3, 9.81])


def test_invalid_profile_cannot_form_context() -> None:
    profile = _profile()
    profile["sample_contract"]["stale_sample_count"] = 1
    with pytest.raises(ConfigurationSupportError, match="stale_sample_count=1"):
        flatten_response_context(profile)


def test_mock_or_manual_profile_cannot_form_context() -> None:
    profile = _profile()
    profile["source"]["backend"] = "mock"
    profile["source"]["device"] = "mock://sts3215"
    profile["source"]["informational_only"] = True
    profile["source"]["hardware_authorized"] = False
    profile["source"]["motion_authorized"] = False
    profile["source"]["configuration_calibration_authorized"] = False
    profile["source"]["suspended_or_benched"] = False
    profile["source"]["policy_envelope_sha256"] = None
    with pytest.raises(ConfigurationSupportError, match="informational_only_mock"):
        flatten_response_context(profile)


def test_review_accepts_map_but_holds_training() -> None:
    review = build_review()
    assert review["status"] == "PASS_RESPONSE73_FIELD_MAP_HOLD_POLICY_CONDITIONING_READINESS"
    assert review["accepted_schema"]["flatten_order"] == list(RESPONSE_CONTEXT_FIELDS)
    assert review["field_map_checks"]["manual_or_true_configuration_fields_present"] is False
    assert {item["id"] for item in review["readiness_holds"]} == {
        "SIGNED_RESPONSE_NOT_ENCODED_EXPLICITLY",
        "CALIBRATION_SUPPORT_MODE_UNDERSPECIFIED_FOR_POLICY_INPUT",
    }
    assert review["authority"]["training"] is False
    assert review["authority"]["rdkx5_or_robot"] is False
