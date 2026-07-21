from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .winner_v11_dynamic_calibration_review import (
    CONTEXT_DIMENSION,
    WINNER_V10_FINAL_SHA256,
    WINNER_V10_HALF_SHA256,
    calibrator_abi,
    locomotion_abi,
)

POLICY_REPOSITORY = "RobVanProd/open-duck-mini-rdkx5"
POLICY_COMMIT = "07893eecb7858f15a61d8763be526ca4800ebafa"
POLICY_PR_URL = "https://github.com/RobVanProd/open-duck-mini-rdkx5/pull/76"
POLICY_ARTIFACT_PATH = (
    "outputs/analysis/winner_v11_dynamic_calibration_interface_preregistration.json"
)
POLICY_ARTIFACT_SHA256 = (
    "2500c731a3413b08568e6e88b57300d2c8c86b61f9fe7418f3efa21ab639c8a2"
)
PRIOR_RUNTIME_HOLD_COMMIT = "9d9410f9ff892e467551e75332dd17bcdcd9f819"
PRIOR_RUNTIME_HOLD_SHA256 = (
    "a5496d7f23195975f83c2536cd0b5a962a074eaf9afdf7b4455b33f496c7c080"
)
SOURCE_RECEIPTS = {
    "builder": "0627a810c2caa99de62a2b0b815ef667ca97e2689facce86eb8a8ae14ac3c16a",
    "closed_v6b_result": (
        "44c8c8c86c91f0f8145c309656ce478d40603d06512ea40dcf963bfc2cd6a054"
    ),
    "runtime_hash_review_receipt": (
        "20995a5c6116f2db5a5bf5d44cbab1e553dc00dcf42475d9b9971ebdb4b285e2"
    ),
    "v6_network_source": (
        "cfff280a1c592043d7e1849c68a3c99b05574814180506e6608f17877a5dbb90"
    ),
    "v6b_numeric_attribution": (
        "0b40472af2b427bdc20bd4985a83924f5018d7884cc32b678c958fe31f5dafff"
    ),
    "winner_v10_nominal": (
        "236772a969955bb49e35c685bab2ecb19ab912b6511b7bbdc22c199c6307fa0b"
    ),
    "winner_v10_r2_condition6": (
        "89cb884879448d480915870c169ed1af942c082ce092b00af5b0dbc0af3209a1"
    ),
    "winner_v10_r2_condition7_hold": (
        "4cccd7f93110c4b6f758b6979a008ad31c8791e2cd0d285db69a80d7bddb676d"
    ),
    "winner_v10_representation": (
        "c66d36dd073464fbe09a1c68b9c6d5ca2acda8406e52570032df90c61b833a17"
    ),
}

RESULT_SCHEMA_VERSION = "open_duck_x5.winner_v11_dynamic_calibration_rereview.v1"
STATUS = "PASS_WINNER_V11_LF_BINDING_HOLD_ZERO_PPO_ONLY"
DECISION = "AUTHORIZE_POLICY_WINNER_V11_ZERO_PPO_CPU_MECHANICS_CONTRACT_ONLY"


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
            "artifact_path": POLICY_ARTIFACT_PATH,
            "committed_lf_sha256": POLICY_ARTIFACT_SHA256,
            "schema_version": "winner_v11.dynamic_calibration_interface_preregistration.v2",
            "contract_id": "winner-v11-dynamic-calibration-r64",
        },
        "hash_correction_closure": {
            "prior_runtime_hold_commit": PRIOR_RUNTIME_HOLD_COMMIT,
            "prior_runtime_hold_artifact_sha256": PRIOR_RUNTIME_HOLD_SHA256,
            "prior_hold_reclassified": False,
            "metadata_only_correction": True,
            "graph_abi_gate_or_authority_changed": False,
            "zero_ppo_run_started_before_review": False,
            "committed_git_blobs_authoritative": True,
            "source_receipt_hash_mode": "sha256 after CRLF-to-LF normalization",
            "source_receipts": SOURCE_RECEIPTS,
            "source_receipt_count": 9,
            "all_source_receipts_match_committed_git_blobs": True,
            "lf_hash_binding_closed": True,
        },
        "protected_winner_v10_base": {
            "policy_sha256": {
                "half": WINNER_V10_HALF_SHA256,
                "final": WINNER_V10_FINAL_SHA256,
            },
            "default_off_action_and_state_must_be_bit_exact": True,
            "winner_v6_and_v6b_results_remain_closed": True,
            "r2_conditions_1_through_6_passed": True,
            "r2_condition7_terminal_hold_preserved": True,
            "r2_resumption": False,
            "robot_clearance": False,
            "deployment_policy_selected": False,
        },
        "accepted_interface": {
            "calibrator": calibrator_abi(),
            "locomotion": locomotion_abi(),
            "identical_to_reviewed_winner_v6_abi": True,
            "calibration_ticks": 250,
            "observation_contract": "winner-v2-115d",
            "normalization_location": "inside future ONNX graph",
            "host_action_projection_or_limiter_added": False,
        },
        "required_sequence_semantics": {
            "frequency_hz": 50,
            "calibrator_initial_previous_action": "exact float32 zeros[1,14]",
            "calibrator_initial_hidden_state": "exact float32 zeros[1,64]",
            "calibration_command": "exact float32 zeros[7]",
            "calibration_phase": [1.0, 0.0],
            "calibration_phase_advances": False,
            "context_shape": [1, CONTEXT_DIMENSION],
            "context_dtype": "float32",
            "context_order": "learned_response_latent[0:64]",
            "context_bounds_inclusive": [-1.0, 1.0],
            "context_source": "exact final successful calibrator h_out",
            "context_runtime_scaling": "none",
            "context_session_local_immutable_nonpersistent": True,
            "context_recomputed_each_process_start": True,
            "previous_action_handoff": "final confirmed previous_action_out",
            "p30_applied_target_observer_continues_without_reset": True,
            "locomotion_hidden_initial": "exact float32 zeros[1,64]",
            "locomotion_phase_reset": [1.0, 0.0],
            "runtime_remains_paused_after_handoff": True,
            "paused_hold_target": "final confirmed safe calibration target",
        },
        "x0_and_torque_boundary": {
            "condition7_torso_com_x_m": -0.05,
            "condition7_x0_trace_population": 4,
            "condition7_x0_all_trace_sha256": (
                "2303e73ed34a77ab5b46e70f622ebf7f97290d83af8826ecce3542cd2f79641e"
            ),
            "condition7_x0_all_byte_identical": True,
            "condition7_x0_action_and_state_exact_zero": True,
            "condition7_x0_all_terminate_after_samples": 47,
            "default_off_x0_remains_byte_exact_winner_v10": True,
            "future_enabled_x0_is_graph_authoritative_and_may_be_nonzero": True,
            "runtime_must_not_force_enabled_x0_zero": True,
            "future_enabled_x0_requires_separate_behavior_gate": True,
            "graph_owns_normalized_action_absolute_and_delta_guards": True,
            "inward_torque_representation_is_plant_xml_semantics": True,
            "inward_torque_requires_runtime_semantic_change": False,
            "host_must_not_translate_torque_bounds_into_action_limits": True,
        },
        "authorized_zero_ppo_cpu_contract": {
            "separately_named_contract_required": True,
            "cpu_only": True,
            "optimizer_steps": 0,
            "formal_behavior_cells": 0,
            "calibrator_ticks": 250,
            "arbitrary_finite_default_off_population": True,
            "both_winner_v10_hashes_required": True,
            "default_off_action_and_previous_state_bit_exact": True,
            "calibrator_and_locomotion_jax_onnx_chain": True,
            "enabled_graph_owns_absolute_and_delta_action_guards": True,
            "protected_physical_chain_semantics_required": True,
            "invalid_handoffs_fail_closed": True,
            "pass_authorizes_only": (
                "a separate training preregistration proposal for review; "
                "no optimizer step"
            ),
        },
        "required_fail_closed_rules": [
            "wrong policy, source, contract, reference, fit, config, or runtime hash",
            "missing, stale, mixed-epoch, nonfinite, wrong-shape, or out-of-bound input",
            "failed or ambiguous send, lost contact, bus, sensor, watchdog, or timing failure",
            "missing, mutable, persisted, scaled, or invalid calibration context",
            "any invalid handoff prevents locomotion arming",
            "every future abort path torque-offs before exit",
        ],
        "compatibility_boundary": {
            "runtime_v1_101x14_unchanged": True,
            "existing_runtime_v2_115d_unchanged": True,
            "production_policy_loader_changed": False,
            "runtime_implementation_added": False,
            "review_artifact_only": True,
        },
        "remaining_holds": [
            "zero-PPO CPU mechanics contract has not run",
            "no optimizer step or training is authorized",
            "no support-mode behavior has been defined or tested",
            "no calibrator or locomotion deployment graph is selected",
            "Winner-v10 condition-7 hold remains terminal",
            "policy robot clearance remains false",
            "runtime implementation, X5 preflight, Gate 5, and deployment remain blocked",
        ],
        "authority": {
            "policy_freeze_zero_ppo_cpu_mechanics_contract": True,
            "policy_run_zero_ppo_cpu_mechanics_contract": True,
            "training_or_optimizer": False,
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
    return f"""# Winner-v11 Dynamic Calibration Runtime Rereview

status: `{review['status']}`

decision: `{review['decision']}`

JSON SHA-256: `{json_sha256}`

Policy request: `{POLICY_REPOSITORY}@{POLICY_COMMIT}`

Corrected committed LF artifact SHA-256: `{POLICY_ARTIFACT_SHA256}`

## Rereview result

The metadata-only correction closes the prior LF/CRLF hold. The exact
committed artifact and all nine source receipts match authoritative Git blobs,
the prior runtime HOLD remains unreclassified, and no zero-PPO run began before
this review. No graph, ABI, gate, or authority changed.

The unchanged calibrator `115+14+64 -> 14+14+64` and locomotion
`115+14+64+64 -> 14+14+64` ABIs remain feasible against the exact Winner-v10
protected hashes. The corrected request now explicitly inherits the complete
Winner-v6 sequence, context, pause, and fail-closed contract.

Default-off x=0 remains byte-exact Winner-v10. Runtime does not impose a host
x=0 deadband: a future enabled graph may produce nonzero corrective action at
x=0, but that behavior is graph-authoritative and requires a separate behavior
gate. Normalized action guards remain graph-owned; inward torque remains
plant/XML semantics and creates no runtime limiter.

## Authority boundary

Policy may freeze and run one separately named CPU-only zero-PPO mechanics
contract with 250 calibrator ticks, zero optimizer steps, and zero behavior
cells. This does not authorize training, an optimizer step, Colab, GPU/iGPU,
runtime implementation, X5 or robot access, serial/GPIO/I2C, torque, motion,
Gate 5, deployment, or robot clearance.
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    args = parser.parse_args(argv)
    review = build_review()
    json_bytes = (json.dumps(review, indent=2, sort_keys=True) + "\n").encode()
    json_sha256 = _sha256_bytes(json_bytes)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(json_bytes)
    args.markdown.write_text(render_markdown(review, json_sha256), encoding="utf-8")
    print(f"status={STATUS} json_sha256={json_sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
