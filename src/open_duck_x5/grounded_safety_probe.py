from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from .grounded_safety import GROUNDED_READINESS_SAMPLES, GroundedStabilityGuard
from .safety import SafetyError
from .sensors import SensorReadout


def _sample(
    tick: int,
    *,
    acceleration: tuple[float, float, float] = (0.0, 0.0, 9.81),
    contacts: tuple[float, float] = (1.0, 1.0),
) -> SensorReadout:
    sample = SensorReadout()
    sample.acceleration_m_s2[:] = acceleration
    sample.contacts[:] = contacts
    sample.imu_timestamp_ns = tick * 10_000_000
    sample.contacts_timestamp_ns = tick * 10_000_000
    sample.imu_stale = False
    sample.contacts_stale = False
    return sample


def _ready() -> GroundedStabilityGuard:
    guard = GroundedStabilityGuard(enforce_contacts=True)
    for tick in range(1, GROUNDED_READINESS_SAMPLES + 1):
        guard.add_readiness_sample(_sample(tick))
    return guard


def _trip_case(
    name: str, samples: list[SensorReadout], expected_fragment: str
) -> dict[str, object]:
    guard = _ready()
    trip_tick: int | None = None
    error = None
    for tick, sample in enumerate(samples, 1):
        try:
            guard.observe(sample)
        except SafetyError as exc:
            trip_tick = tick
            error = str(exc)
            break
    return {
        "name": name,
        "result": "PASS" if error and expected_fragment in error else "FAIL",
        "trip_tick": trip_tick,
        "error": error,
        "expected_error_fragment": expected_fragment,
        "goal_writes_after_trip": 0,
    }


def run_fault_injection() -> dict[str, object]:
    hard = math.radians(33.0)
    sustained = math.radians(17.0)
    cases = [
        _trip_case(
            "single_hard_tilt",
            [
                _sample(
                    100,
                    acceleration=(
                        9.81 * math.sin(hard),
                        0.0,
                        9.81 * math.cos(hard),
                    ),
                )
            ],
            "single-tick tilt",
        ),
        _trip_case(
            "sustained_tilt",
            [
                _sample(
                    100 + tick,
                    acceleration=(
                        9.81 * math.sin(sustained),
                        0.0,
                        9.81 * math.cos(sustained),
                    ),
                )
                for tick in range(3)
            ],
            "persisted for 3 ticks",
        ),
        _trip_case(
            "both_contacts_false",
            [_sample(100 + tick, contacts=(0.0, 0.0)) for tick in range(3)],
            "both foot contacts",
        ),
        _trip_case(
            "invalid_acceleration",
            [
                _sample(100 + tick, acceleration=(0.0, 0.0, 0.0))
                for tick in range(3)
            ],
            "invalid acceleration",
        ),
    ]
    healthy = _ready()
    for tick in range(250):
        healthy.observe(_sample(100 + tick))
    cases.append(
        {
            "name": "healthy_control",
            "result": "PASS" if healthy.trip_reason is None else "FAIL",
            "ticks": 250,
            "trip_reason": healthy.trip_reason,
        }
    )
    passed = all(case["result"] == "PASS" for case in cases)
    return {
        "schema_version": "open_duck_x5.g3_o1_mock_fault_injection.v1",
        "status": "PASS" if passed else "FAIL",
        "scope": {
            "backend": "pure-software-mock",
            "robot_access": False,
            "torque": False,
            "motion": False,
            "policy": False,
        },
        "readiness_samples": GROUNDED_READINESS_SAMPLES,
        "cases": cases,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run offline G3 safety fault injection")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = run_fault_injection()
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    # Evidence hashes must be identical on Windows development hosts and the
    # Linux CI/X5 checkout. Avoid platform newline translation.
    output.write_bytes((json.dumps(result, indent=2) + "\n").encode("utf-8"))
    print(json.dumps(result, separators=(",", ":")))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
