from __future__ import annotations

import math

import numpy as np

CONTRACT_ID = "open-duck-mini.best-walk.101x14.v1"
CONTROL_FREQUENCY_HZ = 50.0
CONTROL_PERIOD_NS = 20_000_000
OBSERVATION_DIM = 101
ACTION_DIM = 14
ACTION_SCALE_RAD = 0.25
LEGACY_TARGET_RATE_LIMIT_RAD_S = 5.24
ENVELOPE_MONITOR_RAD_S = 3.75
PHASE_PERIOD_TICKS = 27.0

JOINT_NAMES = (
    "left_hip_yaw",
    "left_hip_roll",
    "left_hip_pitch",
    "left_knee",
    "left_ankle",
    "neck_pitch",
    "head_pitch",
    "head_yaw",
    "head_roll",
    "right_hip_yaw",
    "right_hip_roll",
    "right_hip_pitch",
    "right_knee",
    "right_ankle",
)

SERVO_IDS = (20, 21, 22, 23, 24, 30, 31, 32, 33, 10, 11, 12, 13, 14)

# Wire-only response order. ID 13 must follow ID 14 on this physical chain to
# avoid corrupting ID 13's grouped-read status packet. Logical/action ordering
# remains SERVO_IDS and received packets are routed by their ID.
SERVO_SYNC_READ_IDS = (20, 21, 22, 23, 24, 30, 31, 32, 33, 10, 11, 12, 14, 13)

HOME_RAD = np.array(
    [
        0.002,
        0.053,
        -0.630,
        1.368,
        -0.784,
        0.0,
        0.0,
        0.0,
        0.0,
        -0.003,
        -0.065,
        0.635,
        1.379,
        -0.796,
    ],
    dtype=np.float64,
)

TWO_PI = 2.0 * math.pi


def joint_index(name: str) -> int:
    try:
        return JOINT_NAMES.index(name)
    except ValueError as exc:
        raise KeyError(f"unknown joint: {name}") from exc


def servo_index(servo_id: int) -> int:
    try:
        return SERVO_IDS.index(servo_id)
    except ValueError as exc:
        raise KeyError(f"unknown servo id: {servo_id}") from exc
