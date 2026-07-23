from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

POLICY_REPOSITORY = "RobVanProd/open-duck-mini-rdkx5"
POLICY_COMMIT = "53fb7e28cad693e7ac9844559690bc9bbd35093c"
POLICY_PR_URL = "https://github.com/RobVanProd/open-duck-mini-rdkx5/pull/76"
POLICY_ARTIFACT_PATH = (
    "outputs/analysis/winner_v6_dynamic_calibration_interface_preregistration.json"
)
POLICY_ARTIFACT_SHA256 = "a66ff7138bdc474c5bd6d0a8899eba041d00305a3d3bd38fc13b0c00e4c3007e"

RESULT_SCHEMA_VERSION = "open_duck_x5.winner_v6_dynamic_calibration_review.v1"
STATUS = "PASS_DYNAMIC_CALIBRATION_SCHEMA_HOLD_CPU_CONTRACT"
DECISION = "AUTHORIZE_POLICY_ZERO_PPO_CPU_SOFTWARE_CONTRACT_ONLY"
CONTEXT_DIMENSION = 64
CONTEXT_FIELDS = tuple(f"learned_response_latent[{index}]" for index in range(CONTEXT_DIMENSION))


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _tensor(name: str, shape: list[int]) -> dict[str, object]:
    return {"name": name, "dtype": "float32", "shape": shape}


def build_review() -> dict[str, object]:
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "status": STATUS,
        "decision": DECISION,
        "policy_request": {
            "repository": POLICY_REPOSITORY,
            "commit": POLICY_COMMIT,
            "pull_request": POLICY_PR_URL,
            "artifact_path": POLICY_ARTIFACT_PATH,
            "artifact_sha256": POLICY_ARTIFACT_SHA256,
        },
        "compatibility_boundary": {
            "runtime_v1_101x14_unchanged": True,
            "runtime_v1_policy_loader_changed": False,
            "required_path": "default-off versioned runtime-v2",
            "winner_v2_115d_semantics_required": True,
            "shared_101_slice_is_not_compatible": True,
            "runtime_v2_implementation_present": False,
        },
        "accepted_calibrator_abi": {
            "inputs": [
                _tensor("obs", [1, 115]),
                _tensor("previous_action", [1, 14]),
                _tensor("h_in", [1, 64]),
            ],
            "outputs": [
                _tensor("calibration_actions", [1, 14]),
                _tensor("previous_action_out", [1, 14]),
                _tensor("h_out", [1, 64]),
            ],
            "initial_previous_action": "exact float32 zeros",
            "initial_hidden_state": "exact float32 zeros",
            "action_semantics_changed": False,
            "x0_deadband_present": False,
        },
        "accepted_locomotion_abi": {
            "inputs": [
                _tensor("obs", [1, 115]),
                _tensor("previous_action", [1, 14]),
                _tensor("h_in", [1, 64]),
                _tensor("calibration_context", [1, 64]),
            ],
            "outputs": [
                _tensor("continuous_actions", [1, 14]),
                _tensor("previous_action_out", [1, 14]),
                _tensor("h_out", [1, 64]),
            ],
            "context_dtype": "float32",
            "context_shape": [1, CONTEXT_DIMENSION],
            "context_order": list(CONTEXT_FIELDS),
            "context_bounds": [-1.0, 1.0],
            "runtime_scaling": "none",
        },
        "accepted_sequence_semantics": {
            "calibration_ticks": 250,
            "frequency_hz": 50,
            "calibration_command_fields": "exact zeros",
            "calibration_phase": [1.0, 0.0],
            "calibration_phase_advances": False,
            "context_source": "exact final successful calibrator h_out",
            "locomotion_context_immutable": True,
            "locomotion_hidden_reset": "exact zeros",
            "locomotion_previous_action_source": "final confirmed calibrator previous_action_out",
            "applied_target_observer_continues_without_reset": True,
            "locomotion_phase_reset": [1.0, 0.0],
            "runtime_remains_paused_after_handoff": True,
            "paused_hold_target": "final confirmed safe calibration target",
        },
        "runtime_feasibility": {
            "two_preallocated_onnx_sessions_feasible": True,
            "preallocated_context_buffer_feasible": True,
            "no_python_context_scaling_required": True,
            "state_and_observer_handoff_feasible": True,
            "fail_closed_before_policy_arming_feasible": True,
            "calibration_evidence_hash_binding_feasible": True,
            "session_local_context_only_feasible": True,
        },
        "required_fail_closed_rules": [
            "missing, stale, failed, nonfinite, wrong-shape, or out-of-bound state prevents arming",
            "any lost contact, watchdog, bus, sensor, support-mode, or timing "
            "failure aborts calibration",
            "context is never loaded from a prior boot or persisted as a per-build measurement",
            "every runtime process start requires a new successful calibration "
            "before v2 locomotion arming",
            "torque off on every abort, exception, signal, watchdog, or failed handoff",
        ],
        "policy_cpu_contract_requirements": [
            "exact calibrator and locomotion names, shapes, and dtypes",
            "calibrator step-zero action exact zero for fixed and pseudorandom "
            "input/state controls",
            "calibrator hidden response state finite, bounded, and able to evolve",
            "locomotion context branch exact-zero default-off with protected "
            "action/state bit-exact",
            "no true configuration label enters either actor or exported graph",
            "graph-owned conservative action bounds hold for all tested tensors",
            "JAX/ONNX 250-tick calibration plus handoff plus locomotion chain agrees within 1e-7",
            "failed calibration never produces an armable context",
        ],
        "remaining_holds": [
            "policy zero-PPO CPU software contract not run",
            "support calibrator training not authorized until that contract passes",
            "runtime-v2 implementation remains absent",
            "no calibrator or locomotion graph is selected",
            "policy robot clearance and supported configuration envelope remain absent",
        ],
        "runtime_implementation": {
            "source_or_policy_loader_changed": False,
            "control_loop_changed": False,
            "hardware_path_reachable": False,
            "review_artifact_only": True,
        },
        "authority": {
            "policy_zero_ppo_cpu_contract": True,
            "training_or_hosted_compute": False,
            "runtime_policy_implementation": False,
            "rdkx5_or_robot": False,
            "serial_gpio_i2c": False,
            "torque_or_motion": False,
            "gate5_or_deployment": False,
            "robot_clearance": False,
        },
    }


def render_markdown(review: dict[str, object], json_sha256: str) -> str:
    return f"""# Winner-v6 Dynamic Calibration Runtime Schema Review

status: `{review["status"]}`

decision: `{review["decision"]}`

JSON SHA-256: `{json_sha256}`

Policy request: `{POLICY_REPOSITORY}@{POLICY_COMMIT}`

Artifact: `{POLICY_ARTIFACT_PATH}`

Artifact SHA-256: `{POLICY_ARTIFACT_SHA256}`

## Review result

The proposed two-graph state and context handoff is implementable as a
default-off versioned runtime-v2 path. It does not alter or reinterpret the
frozen runtime-v1 101x14 contract. Runtime can preallocate the calibrator's
115+14+64 inputs and 14+14+64 outputs, pass the final successful `h_out[64]`
without scaling into an immutable locomotion `calibration_context[64]`, carry
the confirmed previous action and P30 applied-target observer across the
handoff, reset locomotion recurrent state and phase exactly once, and remain
paused while holding the last safe calibration target.

The learned latent has no physical field interpretation at runtime. Its exact
order is `learned_response_latent[0:64]`, its values must be finite float32 in
[-1,1], and it exists only for the current process. Runtime must never persist
or reload it after restart; a new successful calibration is required on every
startup, which automatically covers later disassembly or configuration change
without manual measurements.

## Remaining hold

This review authorizes only the policy-side zero-PPO CPU software contract.
Training remains blocked until that contract proves the exact graph ABIs,
default-off identities, action bounds, state/context chain, and JAX/ONNX
agreement. Runtime implementation, hardware access, torque, motion, Gate 5,
deployment, and robot clearance remain unauthorized.
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    args = parser.parse_args(argv)
    review = build_review()
    json_bytes = (json.dumps(review, indent=2, sort_keys=True) + "\n").encode("utf-8")
    json_sha256 = _sha256_bytes(json_bytes)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(json_bytes)
    args.markdown.write_text(render_markdown(review, json_sha256), encoding="utf-8")
    print(f"status={STATUS} json_sha256={json_sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
