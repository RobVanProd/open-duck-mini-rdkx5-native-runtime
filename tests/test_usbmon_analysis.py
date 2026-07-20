from __future__ import annotations

import json
from pathlib import Path

from open_duck_x5.usbmon_analysis import analyze_capture, parse_usbmon_line


def test_parse_usbmon_bulk_submission() -> None:
    event = parse_usbmon_line(
        "abc 1000 S Bo:1:003:2 -115 8 = ffff1404023c0b9e"
    )
    assert event is not None
    assert event.timestamp_us == 1000
    assert event.event == "S"
    assert event.transfer == "B"
    assert event.direction == "o"
    assert event.bus == 1
    assert event.device == 3
    assert event.data == bytes.fromhex("ffff1404023c0b9e")


def test_correlates_three_out_transfers_with_one_application_tick(tmp_path: Path) -> None:
    metadata = {
        "usb_bus": 1,
        "usb_device": 3,
        "clock_anchor_before": {"perf_counter_ns": 1_000_000_000},
    }
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    usbmon_path = tmp_path / "usbmon.txt"
    usbmon_path.write_text(
        "\n".join(
            (
                "a 1000010 S Bo:1:003:2 -115 50 = fffffe2e832a02",
                "a 1000020 C Bo:1:003:2 0 50 >",
                "b 1000030 S Bo:1:003:2 -115 22 = fffffe12823804",
                "b 1000040 C Bo:1:003:2 0 22 >",
                "g 1000042 C Bi:1:003:1 0 140 = ffff14060000000000e5",
                "c 1000050 S Bo:1:003:2 -115 8 = ffff1404023c0b9e",
                "c 1000060 C Bo:1:003:2 0 8 >",
                "h 1000062 C Bi:1:003:1 0 17 = ffff140d0000004a1c",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    trace = {
        "tick": 0,
        "sync_marker": {"extended_servo_id": 20},
        "timestamps_ns": {
            "write_start_ns": 1_000_005_000,
            "group_write_start_ns": 1_000_025_000,
            "group_first_rx_ns": 1_000_044_000,
            "group_last_rx_ns": 1_000_045_000,
            "extended_write_start_ns": 1_000_045_000,
            "extended_first_rx_ns": 1_000_064_000,
            "extended_last_rx_ns": 1_000_067_000,
            "bus_end_ns": 1_000_070_000,
        },
    }
    trace_path = tmp_path / "transaction.jsonl"
    trace_path.write_text(json.dumps(trace) + "\n", encoding="utf-8")

    result = analyze_capture(
        usbmon_path=usbmon_path,
        metadata_path=metadata_path,
        transaction_trace_path=trace_path,
    )

    assert result["ticks_correlated"] == 1
    assert result["out_transfer_counts"] == {
        "goal_sync_write": 1,
        "state_sync_read": 1,
        "extended_read": 1,
    }
    assert result["out_urb_duration_us"]["mean"] == 10.0
    assert result["app_start_to_usb_submit_us"]["mean"] == 5.0
    assert result["bulk_in_completion_count"] == 2
    assert result["usb_last_in_to_app_last_rx_us"]["mean"] == 4.0
