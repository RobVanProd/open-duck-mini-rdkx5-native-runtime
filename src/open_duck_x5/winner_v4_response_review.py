from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .configuration_support import BODY_METRICS, JOINT_METRICS, PROFILE_SCHEMA_VERSION
from .response_context_review import RESPONSE_CONTEXT_DIM, RESPONSE_CONTEXT_FIELDS


POLICY_REPOSITORY = "RobVanProd/open-duck-mini-rdkx5"
POLICY_COMMIT = "6a5d43cd6aacd8cc9a989182444e8a7416c35299"
POLICY_PREREGISTRATION_PATH = (
    "outputs/analysis/winner_v4_response_interface_preregistration.json"
)
POLICY_PREREGISTRATION_SHA256 = (
    "562ea92c4ba9eb026263740a07fe349ed79e051f0a162e8dd476812f089b6adc"
)
POLICY_PR_URL = "https://github.com/RobVanProd/open-duck-mini-rdkx5/pull/76"

RESULT_SCHEMA_VERSION = "open_duck_x5.winner_v4_response_interface_review.v1"
STATUS = "PASS_RESPONSE73_FIELD_MAP_HOLD_POLICY_CONDITIONING_READINESS"
DECISION = "HOLD_TRAINING_PENDING_SIGNED_X_AND_SUPPORT_MODE_CONTRACT"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_review() -> dict[str, object]:
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "status": STATUS,
        "decision": DECISION,
        "policy_request": {
            "repository": POLICY_REPOSITORY,
            "commit": POLICY_COMMIT,
            "pull_request": POLICY_PR_URL,
            "artifact_path": POLICY_PREREGISTRATION_PATH,
            "artifact_sha256": POLICY_PREREGISTRATION_SHA256,
            "contract_id": "winner-v4-response73-r64",
        },
        "accepted_schema": {
            "profile_schema": PROFILE_SCHEMA_VERSION,
            "context_input_name": "response_context",
            "context_dtype": "float32",
            "context_shape": [1, RESPONSE_CONTEXT_DIM],
            "dimension": RESPONSE_CONTEXT_DIM,
            "flatten_order": list(RESPONSE_CONTEXT_FIELDS),
            "joint_metric_order": list(JOINT_METRICS),
            "body_metric_order": list(BODY_METRICS),
            "runtime_scaling": "none; SI values supplied directly",
            "normalization_location": "inside policy ONNX initializers",
            "missing_or_invalid_behavior": "prevent policy arming",
            "default_or_stale_substitution": False,
            "canonical_observation_changed": False,
            "action_phase_or_state_semantics_changed": False,
            "separate_preallocated_immutable_input_feasible": True,
            "profile_raw_evidence_and_envelope_hash_binding_feasible": True,
        },
        "field_map_checks": {
            "dimension_73": RESPONSE_CONTEXT_DIM == 73,
            "all_fields_unique": len(set(RESPONSE_CONTEXT_FIELDS)) == 73,
            "joint_fields_70": len(JOINT_METRICS) * 14 == 70,
            "body_fields_3": len(BODY_METRICS) == 3,
            "manual_or_true_configuration_fields_present": False,
            "profile_v4_validation_can_fail_closed": True,
        },
        "readiness_holds": [
            {
                "id": "SIGNED_RESPONSE_NOT_ENCODED_EXPLICITLY",
                "evidence": (
                    "profile v4 stores absolute p95 pitch/roll rate and acceleration norm "
                    "aggregated over the full trace; it stores no signed or per-stage body response"
                ),
                "required_resolution": (
                    "the preregistered CPU signed-X endpoint screen must prove that the complete "
                    "73-vector does not collapse the two signs before PPO"
                ),
            },
            {
                "id": "CALIBRATION_SUPPORT_MODE_UNDERSPECIFIED_FOR_POLICY_INPUT",
                "evidence": (
                    "profile v4 records only suspended_or_benched=true; it does not distinguish "
                    "a torso support, free-hanging support, or feet-supported calibration boundary"
                ),
                "required_resolution": (
                    "freeze one calibration support mode and prove simulator/runtime feature "
                    "semantics are the same, or prove the selected 73 metrics are invariant to "
                    "every accepted support mode"
                ),
            },
        ],
        "required_policy_correction": {
            "abi_field_order_change_required": False,
            "profile_schema_change_required_now": False,
            "pretraining_contract_additions": [
                "exact calibration support-mode identifier and simulator realization",
                "reject every other support mode for policy-conditioning evidence",
                "signed-X endpoint context non-collapse after runtime-equivalent excitation",
                "repeat determinism and profile-v4 reproduction",
            ],
            "if_signed_x_collapses": (
                "close response73 without training; any sign-preserving profile extension "
                "requires a new field-by-field policy proposal and runtime review"
            ),
        },
        "runtime_implementation": {
            "policy_loader_or_control_loop_changed": False,
            "response_flattener_connected_to_policy": False,
            "review_only_flattener_added": True,
            "hardware_path_reachable": False,
        },
        "authority": {
            "training": False,
            "hosted_compute": False,
            "runtime_policy_implementation": False,
            "rdkx5_or_robot": False,
            "serial_gpio_i2c": False,
            "torque_or_motion": False,
            "gate5_or_deployment": False,
            "robot_clearance": False,
        },
    }


def render_markdown(review: dict[str, object], json_sha256: str) -> str:
    return f"""# Winner-v4 Response73 Runtime Schema Review — 2026-07-20

status: `{review['status']}`

decision: `{review['decision']}`

JSON SHA-256: `{json_sha256}`

Policy request: `{POLICY_REPOSITORY}@{POLICY_COMMIT}`

Artifact: `{POLICY_PREREGISTRATION_PATH}`

Artifact SHA-256: `{POLICY_PREREGISTRATION_SHA256}`
PR: {POLICY_PR_URL}

## Accepted field map

Runtime can produce the proposed `response_context[1,73]` as a separate,
preallocated, immutable float32 ONNX input without changing `obs[115]`, action,
phase, previous-action, or recurrent-state semantics. The exact order is the
five profile-v4 joint metrics for each frozen joint in logical order (70 values),
then the three body metrics. Runtime applies no scaling; normalization belongs
inside the policy graph. Missing, invalid, stale, unreproducible, or
out-of-envelope profile evidence must prevent policy arming. No default value
or stale substitution is accepted.

The committed review-only flattener proves the order is constructible and
fail-closed. It is not connected to the policy loader or control loop.

## Why training remains held

The field map is valid, but profile v4 was originally an envelope-checking
artifact, not a policy-conditioning contract. Two gaps must be resolved before
PPO:

1. Its three body metrics are absolute p95 magnitudes aggregated over the whole
   trace. They contain no explicit sign or per-joint-stage body response. The
   policy's already-preregistered signed-X endpoint screen must prove that the
   complete 73-vector does not collapse the two failure signs.
2. The profile records only `suspended_or_benched=true`. It does not identify
   whether the torso is supported, the robot is free-hanging, or the feet carry
   load. Because those boundaries can change measured response, policy must
   freeze exactly one automatic-calibration support mode and its simulator
   realization, rejecting every other mode, or prove feature invariance across
   all accepted modes.

If signed X collapses, response73 closes without training. Any sign-preserving
profile extension requires a new exact policy proposal and runtime review.

## Authority

This is schema review only. No runtime policy path was implemented. It authorizes
no training, Colab, GPU/iGPU, X5 or robot access, serial/GPIO/I2C, torque,
motion, Gate 5, deployment, or robot clearance.
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    args = parser.parse_args(argv)

    review = build_review()
    json_bytes = (json.dumps(review, indent=2, sort_keys=True) + "\n").encode("utf-8")
    json_sha256 = _sha256_bytes(json_bytes)
    markdown = render_markdown(review, json_sha256)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(json_bytes)
    args.markdown.write_text(markdown, encoding="utf-8")
    print(f"status={STATUS} json_sha256={json_sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
