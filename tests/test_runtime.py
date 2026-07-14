from __future__ import annotations

import json
from pathlib import Path

from open_duck_x5.runtime import main


def test_mock_runtime_starts_paused_and_exits_cleanly(tmp_path: Path) -> None:
    config = Path(__file__).parents[1] / "duck_config.example.json"
    telemetry = tmp_path / "control.jsonl"
    assert (
        main(
            [
                "--bus",
                "mock",
                "--config",
                str(config),
                "--telemetry",
                str(telemetry),
                "--home-seconds",
                "0",
                "--max-ticks",
                "3",
            ]
        )
        == 0
    )
    records = [json.loads(line) for line in telemetry.read_text(encoding="utf-8").splitlines()]
    ticks = [record for record in records if record["schema_version"].endswith("control_tick.v1")]
    events = [record for record in records if record["schema_version"].endswith("runtime_event.v1")]
    assert len(ticks) == 3
    assert all(record["paused"] for record in ticks)
    assert all(not record["observation_valid"] for record in ticks)
    assert len(events) == 1
    assert events[0]["event"] == "runtime_halt"
    assert events[0]["reason"] == "normal_exit"
    assert isinstance(events[0]["timestamp_monotonic_ns"], int)
