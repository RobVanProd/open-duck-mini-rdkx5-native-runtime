from __future__ import annotations

import math
from typing import Any

import numpy as np

from .configuration_support import (
    BODY_METRICS,
    JOINT_METRICS,
    ConfigurationSupportError,
    validate_automatic_profile_data,
)
from .constants import JOINT_NAMES


RESPONSE_CONTEXT_DIM = len(JOINT_NAMES) * len(JOINT_METRICS) + len(BODY_METRICS)
RESPONSE_CONTEXT_FIELDS = tuple(
    f"joint_response.{joint_name}.{metric}"
    for joint_name in JOINT_NAMES
    for metric in JOINT_METRICS
) + tuple(f"body_response.{metric}" for metric in BODY_METRICS)

if RESPONSE_CONTEXT_DIM != 73 or len(RESPONSE_CONTEXT_FIELDS) != RESPONSE_CONTEXT_DIM:
    raise AssertionError("automatic response context must contain exactly 73 fields")


def flatten_response_context(profile: dict[str, Any]) -> np.ndarray:
    """Flatten a complete profile-v4 response for ABI review.

    This function is deliberately not connected to policy execution.  It proves
    that the proposed policy-side order can be produced without changing or
    interpreting the canonical observation vector.  Any invalid or held profile
    fails closed; no default value or stale substitution is permitted.
    """

    issues = validate_automatic_profile_data(profile)
    if issues:
        raise ConfigurationSupportError(
            "automatic profile cannot form a policy response context: "
            + ", ".join(issues)
        )

    values = [
        profile["joint_response"][joint_name][metric]
        for joint_name in JOINT_NAMES
        for metric in JOINT_METRICS
    ]
    values.extend(profile["body_response"][metric] for metric in BODY_METRICS)
    if len(values) != RESPONSE_CONTEXT_DIM:
        raise AssertionError("response context population changed after profile validation")
    if any(isinstance(value, bool) or not math.isfinite(float(value)) for value in values):
        raise ConfigurationSupportError("response context contains a nonfinite value")

    context = np.asarray(values, dtype=np.float32)
    if context.shape != (RESPONSE_CONTEXT_DIM,):
        raise AssertionError("response context shape is not (73,)")
    context.setflags(write=False)
    return context
