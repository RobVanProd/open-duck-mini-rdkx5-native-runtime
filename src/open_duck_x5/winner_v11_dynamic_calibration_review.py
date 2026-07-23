from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

POLICY_REPOSITORY = "RobVanProd/open-duck-mini-rdkx5"
POLICY_COMMIT = "ed3385dbaf30a8cd1580baf452ff0d8406a1121b"
POLICY_PR_URL = "https://github.com/RobVanProd/open-duck-mini-rdkx5/pull/76"
POLICY_ARTIFACT_PATH = (
    "outputs/analysis/winner_v11_dynamic_calibration_interface_preregistration.json"
)
POLICY_ARTIFACT_CLAIMED_SHA256 = (
    "045342b676d96557d451c6a85383f1381c3e3b2489cad3c2b943d85e0778adc6"
)
POLICY_ARTIFACT_COMMITTED_SHA256 = (
    "738cdfe131b5ba70eebbac3333c1b04016c7abdcb8a370c4c682bc3bc9a65424"
)

WINNER_V10_HALF_SHA256 = (
    "cf001269908d86e47eaa145ffda1d87e946a314ecf51056dc086c4cf10164ab6"
)
WINNER_V10_FINAL_SHA256 = (
    "d52b63241340d9d56671b95c58bb0fc72af0998fd47d4684719f6cd44f244a10"
)
WINNER_V10_REPRESENTATION_RESULT_SHA256 = (
    "240f0e736b2e4c232c3caaba7700917c55bf825b5da07f729db51b3c5b6675e5"
)
WINNER_V10_REPRESENTATION_COMMITTED_SHA256 = (
    "c66d36dd073464fbe09a1c68b9c6d5ca2acda8406e52570032df90c61b833a17"
)
WINNER_V10_NOMINAL_RESULT_SHA256 = (
    "eae89e89eb4b92c0414ee7e69c1b8e633d3408495216e55bf1d80bb467642690"
)
WINNER_V10_NOMINAL_COMMITTED_SHA256 = (
    "236772a969955bb49e35c685bab2ecb19ab912b6511b7bbdc22c199c6307fa0b"
)
WINNER_V10_R2_CONDITION6_RESULT_SHA256 = (
    "1787cea6abb1f94edaba605b4dae3436c274d3602a35a3339d93fbcf127fa3f9"
)
WINNER_V10_R2_CONDITION6_COMMITTED_SHA256 = (
    "89cb884879448d480915870c169ed1af942c082ce092b00af5b0dbc0af3209a1"
)
WINNER_V10_R2_CONDITION7_RESULT_SHA256 = (
    "70bd46ab3879a3d2b8e4aa8f1b0cb85563d6b1003705cbc8734848b23bccb274"
)
WINNER_V10_R2_CONDITION7_COMMITTED_SHA256 = (
    "4cccd7f93110c4b6f758b6979a008ad31c8791e2cd0d285db69a80d7bddb676d"
)
WINNER_V9_STORED_BOUND_RESULT_SHA256 = (
    "aee674240aa22d93e45494cd0356b984edf4c2a23a3df055cb6df4aa2433b38e"
)
WINNER_V6_NETWORK_SOURCE_SHA256 = (
    "cfff280a1c592043d7e1849c68a3c99b05574814180506e6608f17877a5dbb90"
)
WINNER_V6B_CLOSED_RESULT_SHA256 = (
    "a1b1bcb81646e332707ba9961f8d4c78f3acd307df4eed161bf8f61d28f21612"
)
WINNER_V6B_CLOSED_RESULT_COMMITTED_SHA256 = (
    "44c8c8c86c91f0f8145c309656ce478d40603d06512ea40dcf963bfc2cd6a054"
)
WINNER_V6B_NUMERIC_ATTRIBUTION_SHA256 = (
    "eb3ed6a951b76e4c88b9adcbb52de3b3a6a84719f469ebfcd788dcef65ee879c"
)
WINNER_V6B_NUMERIC_ATTRIBUTION_COMMITTED_SHA256 = (
    "0b40472af2b427bdc20bd4985a83924f5018d7884cc32b678c958fe31f5dafff"
)
PRIOR_RUNTIME_ABI_REVIEW_SHA256 = (
    "f0b95db839cff0c0329ffb1d9458c06e1ec6e6432b2b3ef84ef5f451550547c8"
)

RESULT_SCHEMA_VERSION = "open_duck_x5.winner_v11_dynamic_calibration_review.v1"
STATUS = "SCHEMA_FEASIBLE_HOLD_WINNER_V11_ZERO_PPO_HASH_BINDING"
DECISION = "REQUEST_POLICY_LF_STABLE_HASH_CORRECTION_BEFORE_ZERO_PPO"
CONTEXT_DIMENSION = 64


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _tensor(name: str, shape: list[int]) -> dict[str, object]:
    return {"name": name, "dtype": "float32", "shape": shape}


def calibrator_abi() -> dict[str, object]:
    return {
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
    }


def locomotion_abi() -> dict[str, object]:
    return {
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
    }


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
            "claimed_artifact_sha256": POLICY_ARTIFACT_CLAIMED_SHA256,
            "committed_artifact_sha256": POLICY_ARTIFACT_COMMITTED_SHA256,
            "requested_contract_id": "winner-v11-dynamic-calibration-r64",
        },
        "hash_binding_review": {
            "committed_git_bytes_are_authoritative": True,
            "policy_artifact_claim_matches_committed_bytes": False,
            "policy_artifact_claim_matches_lf_to_crlf_transcoding": True,
            "platform_dependent_hash_binding": True,
            "matching_committed_sources": [
                "tools/build_winner_v11_dynamic_calibration_interface_preregistration.py",
                "patches/winner_v6_dynamic_calibration_networks.py",
            ],
            "mismatched_sources": {
                "winner_v6b_zero_ppo_cpu_contract_result.json": {
                    "claimed": WINNER_V6B_CLOSED_RESULT_SHA256,
                    "committed": WINNER_V6B_CLOSED_RESULT_COMMITTED_SHA256,
                },
                "winner_v6b_numeric_hold_attribution.json": {
                    "claimed": WINNER_V6B_NUMERIC_ATTRIBUTION_SHA256,
                    "committed": WINNER_V6B_NUMERIC_ATTRIBUTION_COMMITTED_SHA256,
                },
                "winner_v10_inward_torque_contract_result.json": {
                    "claimed": WINNER_V10_REPRESENTATION_RESULT_SHA256,
                    "committed": WINNER_V10_REPRESENTATION_COMMITTED_SHA256,
                },
                "winner_v10_nominal_behavior_result.json": {
                    "claimed": WINNER_V10_NOMINAL_RESULT_SHA256,
                    "committed": WINNER_V10_NOMINAL_COMMITTED_SHA256,
                },
                "winner_v10_r2_condition6_result.json": {
                    "claimed": WINNER_V10_R2_CONDITION6_RESULT_SHA256,
                    "committed": WINNER_V10_R2_CONDITION6_COMMITTED_SHA256,
                },
                "winner_v10_r2_condition7_result.json": {
                    "claimed": WINNER_V10_R2_CONDITION7_RESULT_SHA256,
                    "committed": WINNER_V10_R2_CONDITION7_COMMITTED_SHA256,
                },
            },
            "all_embedded_source_hashes_match_committed_bytes": False,
            "required_correction": (
                "metadata-only LF-stable regeneration at a new policy commit; "
                "no graph, ABI, gate, or authority change"
            ),
        },
        "reviewed_provenance": {
            "prior_runtime_abi_review": {
                "path": (
                    "artifacts/gates/phase_0_audit/"
                    "winner_v6_dynamic_calibration_review/result.json"
                ),
                "sha256": PRIOR_RUNTIME_ABI_REVIEW_SHA256,
            },
            "unchanged_network_source": {
                "path": "patches/winner_v6_dynamic_calibration_networks.py",
                "sha256": WINNER_V6_NETWORK_SOURCE_SHA256,
            },
            "closed_v6b_result": {
                "sha256": WINNER_V6B_CLOSED_RESULT_SHA256,
                "reclassified": False,
                "retry_authorized": False,
            },
            "v6b_numeric_attribution_sha256": (
                WINNER_V6B_NUMERIC_ATTRIBUTION_SHA256
            ),
        },
        "protected_winner_v10_base": {
            "policy_sha256": {
                "half": WINNER_V10_HALF_SHA256,
                "final": WINNER_V10_FINAL_SHA256,
            },
            "inward_torque_representation_result_sha256": (
                WINNER_V10_REPRESENTATION_RESULT_SHA256
            ),
            "nominal_behavior_result_sha256": WINNER_V10_NOMINAL_RESULT_SHA256,
            "r2_condition6_result_sha256": (
                WINNER_V10_R2_CONDITION6_RESULT_SHA256
            ),
            "r2_condition7_hold_result_sha256": (
                WINNER_V10_R2_CONDITION7_RESULT_SHA256
            ),
            "nominal_behavior_passed": True,
            "r2_conditions_1_through_6_passed": True,
            "r2_condition7_terminal_hold_preserved": True,
            "robot_clearance": False,
            "deployment_policy_selected": False,
        },
        "condition7_x0_evidence": {
            "torso_com_x_m": -0.05,
            "checkpoints": ["half", "final"],
            "actuator_fits": ["p30", "p31_34"],
            "trace_population": 4,
            "all_trace_sha256": (
                "2303e73ed34a77ab5b46e70f622ebf7f97290d83af8826ecce3542cd2f79641e"
            ),
            "all_traces_byte_identical": True,
            "all_samples": 47,
            "all_termination_reason": "fall_or_nan",
            "winner_v9_stored_bound_result_sha256": (
                WINNER_V9_STORED_BOUND_RESULT_SHA256
            ),
            "winner_v9_both_x0_chains_exact_zero": True,
            "winner_v10_policy_graphs_byte_identical_to_winner_v9": True,
            "winner_v10_x0_action_and_state_exact_zero": True,
            "interpretation": (
                "the protected zero-command deadband is identical across both "
                "checkpoints and fits and does not stabilize torso COM X=-0.05 m"
            ),
        },
        "accepted_interface": {
            "calibrator": calibrator_abi(),
            "locomotion": locomotion_abi(),
            "identical_to_reviewed_winner_v6_abi": True,
            "calibration_ticks": 250,
            "observation_contract": "winner-v2-115d",
            "normalization_location": "inside future ONNX graph",
        },
        "required_winner_v6_sequence_inheritance": {
            "frequency_hz": 50,
            "calibrator_initial_previous_action": "exact float32 zeros[1,14]",
            "calibrator_initial_hidden_state": "exact float32 zeros[1,64]",
            "calibration_command_fields": "exact zeros[7]",
            "calibration_phase": [1.0, 0.0],
            "calibration_phase_advances": False,
            "context_order": [
                f"learned_response_latent[{index}]"
                for index in range(CONTEXT_DIMENSION)
            ],
            "context_bounds": [-1.0, 1.0],
            "runtime_remains_paused_after_handoff": True,
            "paused_hold_target": "final confirmed safe calibration target",
            "future_abort_path_requires_torque_off": True,
        },
        "runtime_feasibility": {
            "unchanged_abi_remains_implementable": True,
            "winner_v10_inward_torque_is_graph_internal": True,
            "winner_v10_requires_runtime_semantic_change": False,
            "default_off_delegation_can_be_bit_exact": True,
            "host_action_projection_or_limiter_required": False,
            "final_confirmed_previous_action_can_cross_handoff": True,
            "p30_applied_target_observer_can_continue_without_reset": True,
            "final_successful_context_can_be_copied_without_scaling": True,
            "session_local_immutable_context_feasible": True,
            "mandatory_valid_context_before_locomotion_arming_feasible": True,
            "existing_runtime_v2_forces_x0_action_zero": False,
            "existing_runtime_v2_can_remain_default_off_review_only": True,
        },
        "accepted_handoff_semantics": {
            "context_source": "exact final successful calibrator h_out",
            "context_shape": [1, CONTEXT_DIMENSION],
            "context_dtype": "float32",
            "context_runtime_scaling": "none",
            "context_persisted_between_boots": False,
            "context_recomputed_each_process_start": True,
            "locomotion_context_immutable": True,
            "locomotion_hidden_initial": "exact float32 zeros[1,64]",
            "locomotion_phase_reset": [1.0, 0.0],
            "locomotion_phase_order": "observe current then advance after confirmed send",
            "previous_action_source": (
                "final confirmed calibrator previous_action_out"
            ),
            "applied_target_observer_reset_at_handoff": False,
        },
        "zero_ppo_cpu_mechanics_contract": {
            "execution_authorized_by_this_review": False,
            "separately_named_contract_required": True,
            "cpu_only": True,
            "optimizer_steps": 0,
            "formal_behavior_cells": 0,
            "calibrator_and_locomotion_jax_onnx_chain": True,
            "calibrator_ticks": 250,
            "arbitrary_finite_default_off_population": True,
            "default_off_continuous_actions_bit_exact_to_winner_v10": True,
            "default_off_previous_action_out_bit_exact_to_winner_v10": True,
            "enabled_graph_owns_absolute_delta_guard": True,
            "enabled_graph_owns_normalized_action_absolute_delta_guard": True,
            "inward_torque_bounds_are_plant_xml_semantics": True,
            "host_must_not_translate_torque_bounds_into_action_limits": True,
            "host_must_not_add_second_limiter_or_projection": True,
            "invalid_handoffs_fail_closed": True,
            "protected_physical_chain_semantics_required": True,
            "default_off_x0_remains_exact_winner_v10_deadband": True,
            "future_enabled_x0_action_is_graph_authoritative": True,
            "runtime_must_not_independently_force_enabled_x0_action_zero": True,
            "future_enabled_x0_requires_separate_behavior_gate": True,
            "pass_authorizes": (
                "nothing until LF-stable policy metadata receives a new runtime "
                "review; no optimizer step is authorized"
            ),
        },
        "compatibility_boundary": {
            "runtime_v1_101x14_unchanged": True,
            "existing_runtime_v2_115d_unchanged": True,
            "production_policy_loader_changed": False,
            "shared_101_slice_is_not_compatible": True,
            "review_artifact_only": True,
        },
        "required_fail_closed_rules": [
            "wrong policy, source, contract, reference, fit, config, or runtime hash",
            "missing, stale, mixed-epoch, nonfinite, wrong-shape, or out-of-bound input",
            "failed or ambiguous send, lost contact, bus, sensor, watchdog, or timing failure",
            "missing, mutable, persisted, scaled, or invalid calibration context",
            "any invalid handoff prevents locomotion arming",
        ],
        "remaining_holds": [
            "winner-v6 and winner-v6b completed results remain closed",
            "winner-v11 zero-PPO CPU mechanics contract is not yet frozen or run",
            "policy preregistration and six source receipts are not bound to committed LF bytes",
            "no optimizer step or training preregistration is authorized",
            "Winner-v10 condition-7 hold remains terminal and is not resumed",
            "no calibrator or locomotion deployment graph is selected",
            "policy robot clearance remains false",
            "runtime implementation, X5 preflight, Gate 5, and deployment remain blocked",
        ],
        "runtime_implementation": {
            "source_or_policy_loader_changed": False,
            "control_loop_changed": False,
            "hardware_path_reachable": False,
            "review_artifact_only": True,
        },
        "authority": {
            "policy_metadata_hash_correction": True,
            "policy_freeze_zero_ppo_cpu_mechanics_contract": False,
            "policy_run_zero_ppo_cpu_mechanics_contract": False,
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
    return f"""# Winner-v11 Dynamic Calibration Runtime Schema Review

status: `{review['status']}`

decision: `{review['decision']}`

JSON SHA-256: `{json_sha256}`

Policy request: `{POLICY_REPOSITORY}@{POLICY_COMMIT}`

Policy claimed artifact SHA-256: `{POLICY_ARTIFACT_CLAIMED_SHA256}`

Committed LF artifact SHA-256: `{POLICY_ARTIFACT_COMMITTED_SHA256}`

Protected Winner-v10 graphs: `{WINNER_V10_HALF_SHA256}` and
`{WINNER_V10_FINAL_SHA256}`

## Schema result

The unchanged calibrator `115+14+64 -> 14+14+64` and locomotion
`115+14+64+64 -> 14+14+64` ABIs remain implementable against the exact
Winner-v10 protected graph hashes. Winner-v10's inward-torque representation
is internal to the graph and does not change the runtime observation, action,
state, handoff, or target semantics. A disabled adapter can delegate both
`continuous_actions` and `previous_action_out` byte-for-byte without a host
limiter or projection.

Runtime can carry the final confirmed previous action and P30 applied-target
observer through the handoff, copy the final successful `h_out[1,64]` without
scaling into immutable session-local `calibration_context`, reset locomotion
hidden state and phase once, and refuse locomotion arming without a valid
context. No context may be persisted across a process restart.

Condition 7 also fixes an important boundary: the four x=0 traces across both
checkpoints and both actuator fits are byte-identical, exact-zero protected
deadband chains, and all terminate after 47 samples at torso COM X=-0.05 m.
Default-off must preserve that Winner-v10 result exactly. A future trained,
enabled Winner-v11 graph may need nonzero x=0 corrective action, so runtime
must not impose its own x=0 zero-action rule. Enabled x=0 behavior remains
graph-authoritative and must pass a separate behavior gate before any use.

## Hash-binding hold

The policy receipt is not stable over committed bytes. Its claimed artifact
hash is the SHA-256 of a Windows CRLF checkout, while the exact Git object at
the reviewed commit has the distinct LF hash above. Six embedded evidence
receipts have the same LF/CRLF mismatch. The builder and unchanged network
source receipts do match committed bytes, so the defect is metadata-only, but
the zero-PPO population may not be frozen or run from this review.

## Authority boundary

Policy may make only an LF-stable metadata correction and return it for a new
runtime review. The future mechanics contract requirements remain: both
protected hashes, exact default-off action/state identity, the 250-tick
JAX/ONNX calibrator and handoff chain, graph-owned enabled bounds, physically
chained protected semantics, zero behavior cells, zero optimizer steps, and
invalid-handoff rejection.

This review does not authorize training, an optimizer step, Colab, GPU/iGPU,
runtime implementation, X5 or robot access, serial/GPIO/I2C, torque, motion,
Gate 5, deployment, or robot clearance. Winner-v10's condition-7 hold and the
closed Winner-v6/v6b results remain unchanged.
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
