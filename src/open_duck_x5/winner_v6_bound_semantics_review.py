from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

POLICY_REPOSITORY = "RobVanProd/open-duck-mini-rdkx5"
POLICY_COMMIT = "885147d62621d1ab991801a25716afa821d7f081"
POLICY_PR_URL = "https://github.com/RobVanProd/open-duck-mini-rdkx5/pull/76"
FORMAL_RESULT_PATH = "outputs/analysis/winner_v6_zero_ppo_cpu_contract_result.json"
FORMAL_RESULT_SHA256 = "5a99f94a4a4d0f3ffcf23e3d27a5d4c833b318b5cc8f677d6b851e3f619fe5c9"
ATTRIBUTION_PATH = "outputs/analysis/winner_v6_zero_ppo_contract_hold_attribution.json"
ATTRIBUTION_SHA256 = "d318f2c0ef1931f30574f71e8f7f1bffd971bf16815f152c1213bc9dc4e2a3b3"

RESULT_SCHEMA_VERSION = "open_duck_x5.winner_v6_bound_semantics_review.v1"
STATUS = "PASS_BOUND_SEMANTICS_SPLIT_HOLD_V6B_CONTRACT"
DECISION = "AUTHORIZE_POLICY_V6B_ZERO_PPO_CPU_CONTRACT_ONLY"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_review() -> dict[str, object]:
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "status": STATUS,
        "decision": DECISION,
        "policy_evidence": {
            "repository": POLICY_REPOSITORY,
            "commit": POLICY_COMMIT,
            "pull_request": POLICY_PR_URL,
            "formal_result_path": FORMAL_RESULT_PATH,
            "formal_result_sha256": FORMAL_RESULT_SHA256,
            "attribution_path": ATTRIBUTION_PATH,
            "attribution_sha256": ATTRIBUTION_SHA256,
            "completed_formal_status": "HOLD_WINNER_V6_ZERO_PPO_CPU_SOFTWARE_CONTRACT",
            "completed_formal_result_reclassified": False,
            "completed_formal_contract_retry_authorized": False,
        },
        "accepted_semantic_split": {
            "default_off_identity": {
                "population": "arbitrary finite tensors with the exact reviewed ABI",
                "rule": (
                    "the expanded graph delegates continuous_actions and "
                    "previous_action_out byte-for-byte to the accepted protected graph"
                ),
                "new_adapter_projection_applied": False,
                "double_limiting_permitted": False,
            },
            "enabled_adapter_projection": {
                "population": "arbitrary finite in-shape stress tensors",
                "rule": (
                    "the final protected-plus-adapter output remains in [-1,1] and "
                    "within the graph-owned protected winner-v2 per-joint delta vector"
                ),
                "new_adapter_projection_applied": True,
            },
            "protected_full_action_contract": {
                "population": (
                    "chained observations whose measured joint state comes from the "
                    "same simulated/runtime tick and whose previous_action comes from "
                    "the prior confirmed graph output"
                ),
                "rule": (
                    "evaluate the existing final protected action semantics, including "
                    "the downstream actual-centered guard, without replacing them with "
                    "an upstream-only delta assertion on independently sampled state"
                ),
                "independent_joint_state_and_previous_action_pairs_valid": False,
            },
        },
        "causal_basis": {
            "only_formal_failure": "graph_owned_action_bounds_hold",
            "protected_identity_passed": True,
            "enabled_adapter_stress_bounds_passed": True,
            "jax_onnx_chain_passed": True,
            "calibration_fail_closed_passed": True,
            "protected_graph_order": [
                "upstream previous-action velocity projection",
                "downstream actual-centered guard",
                "zero-command deadband",
                "final action and previous-action state outputs",
            ],
            "conclusion": (
                "The failed combined assertion conflated the disabled protected path "
                "with the enabled adapter path and evaluated the protected guard on an "
                "invalid independently randomized state/action fixture."
            ),
        },
        "v6b_contract_constraints": {
            "separately_named_contract_required": True,
            "may_not_overwrite_or_reclassify_failed_contract": True,
            "same_protected_checkpoints": True,
            "same_network_weights": True,
            "same_random_seeds": True,
            "same_graph_abis": True,
            "same_numeric_tolerance": 1.0e-7,
            "same_calibration_ticks": 250,
            "same_invalid_handoff_cases": True,
            "only_allowed_change": (
                "split the bound assertions by disabled, enabled, and physically "
                "chained protected populations exactly as reviewed"
            ),
            "pass_authorizes": (
                "a separate calibrator-training preregistration for review; no optimizer "
                "step is authorized by the v6b software contract itself"
            ),
        },
        "compatibility_boundary": {
            "runtime_v1_101x14_unchanged": True,
            "runtime_v2_implementation_present": False,
            "winner_v2_115d_semantics_required": True,
            "host_must_not_add_a_second_action_limiter": True,
            "actual_centered_guard_remains_graph_internal": True,
        },
        "remaining_holds": [
            "winner-v6 exact completed zero-PPO contract remains held",
            "v6b zero-PPO contract has not been frozen or run",
            "no support calibrator training is authorized",
            "runtime-v2 implementation remains absent",
            "no calibrator or locomotion graph is selected",
            "policy robot clearance remains absent",
        ],
        "runtime_implementation": {
            "source_or_policy_loader_changed": False,
            "control_loop_changed": False,
            "hardware_path_reachable": False,
            "review_artifact_only": True,
        },
        "authority": {
            "policy_v6b_zero_ppo_cpu_contract": True,
            "training_or_ppo": False,
            "colab_hosted_gpu_or_igpu": False,
            "runtime_policy_implementation": False,
            "rdkx5_or_robot": False,
            "serial_gpio_i2c": False,
            "torque_or_motion": False,
            "gate5_or_deployment": False,
            "robot_clearance": False,
        },
    }


def render_markdown(review: dict[str, object], json_sha256: str) -> str:
    return f"""# Winner-v6 Bound-Semantics Runtime Review

status: `{review["status"]}`

decision: `{review["decision"]}`

JSON SHA-256: `{json_sha256}`

Policy evidence: `{POLICY_REPOSITORY}@{POLICY_COMMIT}`

## Review result

The completed winner-v6 formal result remains held and may not be retried or
reclassified. Its enabled adapter stress passed, its default-off protected
identity passed, and its only combined failure applied an upstream delta rule
after the protected graph's downstream actual-centered guard on independently
randomized joint/action state.

Runtime accepts three distinct assertions: arbitrary-input default-off identity,
arbitrary-input enabled-adapter projection, and the protected full-action contract
on physically chained state. Default-off must not double-limit the protected
graph. Enabled adapter output must own its final projection.

## Remaining hold

This review authorizes only one separately named policy-side v6b zero-PPO CPU
contract under the exact constraints in the JSON artifact. It authorizes no
training, PPO, Colab, GPU/iGPU, runtime implementation, X5 or robot access,
serial/GPIO/I2C, torque, motion, Gate 5, deployment, or robot clearance.
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
