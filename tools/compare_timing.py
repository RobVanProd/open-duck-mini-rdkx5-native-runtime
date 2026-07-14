from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a baseline-vs-new timing comparison")
    parser.add_argument("--new-summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    new = json.loads(args.new_summary.read_text(encoding="utf-8"))
    result = {
        "schema_version": "open_duck_x5.baseline_comparison.v1",
        "status": "INFORMATIONAL_MOCK" if new.get("informational_only") else "HARDWARE_RESULT",
        "legacy": {
            "x0_read_failure_percent": 1.07,
            "x008_read_failure_percent": 2.68,
            "tick_max_ms": 26.0,
            "read_bursts_observed": True,
            "phase_1_full_timing_artifact": None,
        },
        "new": new,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    output_bytes = (json.dumps(result, indent=2, sort_keys=True) + "\n").encode("utf-8")
    args.output.write_bytes(output_bytes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
