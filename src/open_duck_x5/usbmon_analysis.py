from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

_USBMON_LINE = re.compile(
    r"^(?P<tag>\S+)\s+(?P<timestamp>\d+)\s+(?P<event>[SCE])\s+"
    r"(?P<transfer>[BCIZ])(?P<direction>[io]):"
    r"(?P<bus>\d+):(?P<device>\d+):(?P<endpoint>\d+)\s+(?P<tail>.*)$"
)
_WRAP_US = 1 << 32


@dataclass(frozen=True, slots=True)
class UsbmonEvent:
    tag: str
    timestamp_us: int
    event: str
    transfer: str
    direction: str
    bus: int
    device: int
    endpoint: int
    status: str
    length: int
    data: bytes


@dataclass(frozen=True, slots=True)
class OutTransfer:
    kind: str
    servo_id: int | None
    submit_ns: int
    complete_ns: int | None
    length: int


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_usbmon_line(line: str) -> UsbmonEvent | None:
    match = _USBMON_LINE.match(line.strip())
    if match is None:
        return None
    tail = match.group("tail").split()
    if len(tail) < 2:
        return None
    try:
        length = int(tail[1])
    except ValueError:
        return None
    data = b""
    if "=" in tail:
        marker = tail.index("=")
        hex_text = "".join(tail[marker + 1 :])
        try:
            data = bytes.fromhex(hex_text)
        except ValueError:
            data = b""
    return UsbmonEvent(
        tag=match.group("tag"),
        timestamp_us=int(match.group("timestamp")),
        event=match.group("event"),
        transfer=match.group("transfer"),
        direction=match.group("direction"),
        bus=int(match.group("bus")),
        device=int(match.group("device")),
        endpoint=int(match.group("endpoint")),
        status=tail[0],
        length=length,
        data=data,
    )


def _unwrap_timestamp_ns(timestamp_us: int, anchor_ns: int) -> int:
    anchor_us = anchor_ns // 1000
    wrap = round((anchor_us - timestamp_us) / _WRAP_US)
    return (timestamp_us + wrap * _WRAP_US) * 1000


def _classify_sts_out(data: bytes) -> tuple[str, int | None]:
    if len(data) < 6 or data[:2] != b"\xff\xff":
        return "other", None
    servo_id = int(data[2])
    instruction = int(data[4])
    address = int(data[5])
    if instruction == 0x83 and servo_id == 0xFE:
        if address == 42:
            return "goal_sync_write", None
        if address == 40:
            return "torque_sync_write", None
        return "other_sync_write", None
    if instruction == 0x82 and servo_id == 0xFE and address == 56:
        return "state_sync_read", None
    if instruction == 0x02 and address == 60:
        return "extended_read", servo_id
    return "other", servo_id


def _stats(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {name: None for name in ("min", "mean", "p95", "p99", "p99_9", "max")}
    array = np.asarray(values, dtype=np.float64)
    return {
        "min": float(np.min(array)),
        "mean": float(np.mean(array)),
        "p95": float(np.percentile(array, 95)),
        "p99": float(np.percentile(array, 99)),
        "p99_9": float(np.percentile(array, 99.9)),
        "max": float(np.max(array)),
    }


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def analyze_capture(
    *, usbmon_path: Path, metadata_path: Path, transaction_trace_path: Path
) -> dict[str, object]:
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    bus = int(metadata["usb_bus"])
    device = int(metadata["usb_device"])
    anchor_ns = int(metadata["clock_anchor_before"]["perf_counter_ns"])
    events = []
    for line in usbmon_path.read_text(encoding="utf-8", errors="replace").splitlines():
        event = parse_usbmon_line(line)
        if event is not None and event.bus == bus and event.device == device:
            events.append(event)

    completions = {event.tag: event for event in events if event.event == "C"}
    transfers: list[OutTransfer] = []
    for event in events:
        if event.event != "S" or event.transfer != "B" or event.direction != "o":
            continue
        kind, servo_id = _classify_sts_out(event.data)
        complete = completions.get(event.tag)
        transfers.append(
            OutTransfer(
                kind=kind,
                servo_id=servo_id,
                submit_ns=_unwrap_timestamp_ns(event.timestamp_us, anchor_ns),
                complete_ns=(
                    _unwrap_timestamp_ns(complete.timestamp_us, anchor_ns)
                    if complete is not None
                    else None
                ),
                length=event.length,
            )
        )

    bulk_in_completions = [
        {
            "timestamp_ns": _unwrap_timestamp_ns(event.timestamp_us, anchor_ns),
            "length": event.length,
            "endpoint": event.endpoint,
        }
        for event in events
        if event.event == "C"
        and event.transfer == "B"
        and event.direction == "i"
        and event.length > 0
    ]
    traces = _read_jsonl(transaction_trace_path)
    cursor = 0
    paired_ticks = []
    app_to_submit_us: list[float] = []
    out_urb_us: list[float] = []
    usb_last_in_to_app_last_rx_us: list[float] = []

    def next_transfer(kind: str, servo_id: int | None = None) -> OutTransfer:
        nonlocal cursor
        while cursor < len(transfers):
            candidate = transfers[cursor]
            cursor += 1
            if candidate.kind == kind and (servo_id is None or candidate.servo_id == servo_id):
                return candidate
        qualifier = f" servo {servo_id}" if servo_id is not None else ""
        raise ValueError(f"usbmon capture lacks {kind}{qualifier} for trace tick")

    for trace in traces:
        timestamps = trace["timestamps_ns"]
        marker = trace["sync_marker"]
        extended_servo_id = int(marker["extended_servo_id"])
        goal = next_transfer("goal_sync_write")
        group = next_transfer("state_sync_read")
        extended = next_transfer("extended_read", extended_servo_id)
        paired_ticks.append((trace, goal, group, extended))

    per_tick = []
    for index, (trace, goal, group, extended) in enumerate(paired_ticks):
        timestamps = trace["timestamps_ns"]
        extended_servo_id = int(trace["sync_marker"]["extended_servo_id"])
        stages = (
            ("goal_sync_write", goal, int(timestamps["write_start_ns"])),
            ("state_sync_read", group, int(timestamps["group_write_start_ns"])),
            (
                "extended_read",
                extended,
                int(timestamps["extended_write_start_ns"]),
            ),
        )
        stage_payload = {}
        for name, transfer, app_start_ns in stages:
            submit_delta_us = (transfer.submit_ns - app_start_ns) / 1e3
            app_to_submit_us.append(submit_delta_us)
            urb_duration_us = (
                (transfer.complete_ns - transfer.submit_ns) / 1e3
                if transfer.complete_ns is not None
                else None
            )
            if urb_duration_us is not None:
                out_urb_us.append(urb_duration_us)
            stage_payload[name] = {
                "app_start_ns": app_start_ns,
                "usbmon_submit_ns": transfer.submit_ns,
                "usbmon_complete_ns": transfer.complete_ns,
                "app_start_to_usb_submit_us": submit_delta_us,
                "out_urb_duration_us": urb_duration_us,
                "length": transfer.length,
            }

        next_goal_ns = (
            paired_ticks[index + 1][1].submit_ns
            if index + 1 < len(paired_ticks)
            else int(timestamps["bus_end_ns"])
        )

        def input_window(
            start_ns: int, end_ns: int, app_first_rx_ns: int, app_last_rx_ns: int
        ) -> dict[str, object]:
            completions_in_window = [
                item
                for item in bulk_in_completions
                if start_ns <= int(item["timestamp_ns"]) <= end_ns
            ]
            if not completions_in_window:
                return {
                    "completion_count": 0,
                    "total_bytes": 0,
                    "first_complete_ns": None,
                    "last_complete_ns": None,
                    "completion_span_us": None,
                    "last_complete_to_app_first_rx_us": None,
                    "last_complete_to_app_last_rx_us": None,
                }
            first_ns = int(completions_in_window[0]["timestamp_ns"])
            last_ns = int(completions_in_window[-1]["timestamp_ns"])
            last_to_app_last = (app_last_rx_ns - last_ns) / 1e3
            usb_last_in_to_app_last_rx_us.append(last_to_app_last)
            return {
                "completion_count": len(completions_in_window),
                "total_bytes": sum(int(item["length"]) for item in completions_in_window),
                "first_complete_ns": first_ns,
                "last_complete_ns": last_ns,
                "completion_span_us": (last_ns - first_ns) / 1e3,
                "last_complete_to_app_first_rx_us": (app_first_rx_ns - last_ns) / 1e3,
                "last_complete_to_app_last_rx_us": last_to_app_last,
            }

        per_tick.append(
            {
                "tick": int(trace["tick"]),
                "extended_servo_id": extended_servo_id,
                "stages": stage_payload,
                "bulk_in": {
                    "group": input_window(
                        group.submit_ns,
                        extended.submit_ns,
                        int(timestamps["group_first_rx_ns"]),
                        int(timestamps["group_last_rx_ns"]),
                    ),
                    "extended": input_window(
                        extended.submit_ns,
                        next_goal_ns,
                        int(timestamps["extended_first_rx_ns"]),
                        int(timestamps["extended_last_rx_ns"]),
                    ),
                },
            }
        )

    event_counts: dict[str, int] = {}
    for event in events:
        key = f"{event.event}_{event.transfer}{event.direction}"
        event_counts[key] = event_counts.get(key, 0) + 1
    transfer_counts: dict[str, int] = {}
    for transfer in transfers:
        transfer_counts[transfer.kind] = transfer_counts.get(transfer.kind, 0) + 1

    return {
        "schema_version": "open_duck_x5.usbmon_latency_analysis.v1",
        "inputs": {
            "usbmon_sha256": _sha256(usbmon_path),
            "metadata_sha256": _sha256(metadata_path),
            "transaction_trace_sha256": _sha256(transaction_trace_path),
        },
        "usb_bus": bus,
        "usb_device": device,
        "filtered_event_count": len(events),
        "event_counts": event_counts,
        "out_transfer_counts": transfer_counts,
        "bulk_in_completion_count": len(bulk_in_completions),
        "ticks_correlated": len(per_tick),
        "app_start_to_usb_submit_us": _stats(app_to_submit_us),
        "out_urb_duration_us": _stats(out_urb_us),
        "usb_last_in_to_app_last_rx_us": _stats(usb_last_in_to_app_last_rx_us),
        "per_tick": per_tick,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Correlate usbmon bulk transfers with the transaction trace"
    )
    parser.add_argument("--usbmon", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--transaction-trace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = analyze_capture(
        usbmon_path=args.usbmon,
        metadata_path=args.metadata,
        transaction_trace_path=args.transaction_trace,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
