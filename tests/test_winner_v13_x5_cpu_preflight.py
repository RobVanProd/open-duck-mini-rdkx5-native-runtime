from __future__ import annotations

import json
from pathlib import Path

PREREGISTRATION = Path(
    "artifacts/gates/phase_5_policy/t251_x5_no_motion_cpu_preflight_preregistration_20260731.json"
)


def test_t251_preregistration_is_exact_and_no_motion() -> None:
    value = json.loads(PREREGISTRATION.read_text(encoding="utf-8"))
    assert value["status"] == "PREREGISTERED_T251_X5_NO_MOTION_CPU_PREFLIGHT"
    assert value["earned_by"]["status"] == ("PASS_T250_STATE_COHERENT_RUNTIME_INTEGRATION")
    runner = value["runner_contract"]
    assert runner["provider"] == "CPUExecutionProvider only"
    assert runner["scheduler"] == "SCHED_FIFO"
    assert runner["affinity"] == "exactly one CPU"
    assert runner["warmup_runs_per_graph"] == 10
    assert runner["calibration_ticks"] == 250
    assert runner["home_return_ticks"] == 0
    assert runner["locomotion_ticks"] == 10_000
    gates = value["preflight_gates"]
    assert gates["stage_latency_p99_ms_max"] == 2.0
    assert gates["stage_latency_p99_9_ms_max"] == 3.0
    assert gates["stage_latency_max_ms_max"] == 5.0
    assert value["decision_rule"]["gate5_on_pass"] is False
    assert value["decision_rule"]["robot_motion_on_pass"] is False
    authority = value["authority"]
    assert authority["offline_cpu_execution_on_x5"] is True
    assert authority["serial_bus"] is False
    assert authority["servo_reads_or_writes"] is False
    assert authority["torque"] is False
    assert authority["motion"] is False
    assert authority["policy_deployment"] is False
    assert authority["gate5"] is False
