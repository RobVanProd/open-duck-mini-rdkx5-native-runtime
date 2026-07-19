from __future__ import annotations

import argparse
import gc
import json
import platform
import struct
import sys
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np

from .bus.protocol import checksum
from .bus.sts3215 import STS3215Bus
from .bus.types import ErrorCode, ServoSnapshot
from .constants import ACTION_DIM, SERVO_IDS, SERVO_SYNC_READ_IDS


class _NoopTransport:
    def write(self, data) -> None:
        del data

    def read_some_into(self, target, deadline_ns: int) -> int:
        del target, deadline_ns
        return 0

    def flush_input(self) -> None:
        return None

    def close(self) -> None:
        return None


def _status_packet(servo_id: int, logical_index: int) -> bytes:
    parameters = struct.pack("<HH", 2048 + logical_index, 100 + logical_index)
    body = bytes((servo_id, 6, 0)) + parameters
    return b"\xff\xff" + body + bytes((checksum(body),))


def _response_train() -> bytes:
    return b"".join(
        _status_packet(servo_id, SERVO_IDS.index(servo_id)) for servo_id in SERVO_SYNC_READ_IDS
    )


def _prepare(bus: STS3215Bus, train: bytes) -> None:
    bus._reset_read_state(None)
    bus._rx[: len(train)] = train
    bus._rx_length = len(train)
    bus._group_state_decoded = False


def _finalize(bus: STS3215Bus, snapshot: ServoSnapshot) -> None:
    snapshot.status[:] = bus._read_codes
    snapshot.device_status[:] = bus._read_device_status
    snapshot.stale[:] = bus._read_codes != int(ErrorCode.OK)
    if not bus._group_state_decoded:
        bus._decode_group_state(snapshot)


def _fixed_frame(bus: STS3215Bus, snapshot: ServoSnapshot) -> None:
    if not bus._parse_exact_sync_read_train(snapshot):
        raise RuntimeError("valid fixed train did not take the fixed-frame path")
    bus._rx_length = 0
    _finalize(bus, snapshot)


def _generic(bus: STS3215Bus, snapshot: ServoSnapshot) -> None:
    consumed, seen = bus._parse_available(
        expected_param_length=4,
        only_servo_id=None,
    )
    if consumed != ACTION_DIM * 10 or seen != ACTION_DIM:
        raise RuntimeError(f"generic parser consumed={consumed}, seen={seen}")
    bus._rx_length = 0
    _finalize(bus, snapshot)


def _batch(
    operation: Callable[[STS3215Bus, ServoSnapshot], None],
    bus: STS3215Bus,
    snapshot: ServoSnapshot,
    train: bytes,
    iterations: int,
) -> float:
    start = time.perf_counter_ns()
    for _ in range(iterations):
        _prepare(bus, train)
        operation(bus, snapshot)
    return (time.perf_counter_ns() - start) / iterations / 1_000.0


def _stats(values: list[float]) -> dict[str, float | int]:
    array = np.asarray(values, dtype=np.float64)
    return {
        "batches": len(values),
        "min": float(np.min(array)),
        "mean": float(np.mean(array)),
        "p95": float(np.percentile(array, 95)),
        "max": float(np.max(array)),
    }


def _configure_instrumentation(bus: STS3215Bus, snapshot: ServoSnapshot, *, enabled: bool) -> None:
    snapshot.instrumentation_enabled = enabled
    if not enabled:
        bus._rx_chunk_count = 0
        return
    bus._rx_chunk_count = 10
    for index in range(10):
        bus._rx_chunk_end[index] = (index + 1) * 14
        bus._rx_chunk_time_ns[index] = (index + 1) * 100_000


def _benchmark_mode(
    train: bytes,
    *,
    instrumented: bool,
    warmup: int,
    batches: int,
    iterations_per_batch: int,
) -> dict[str, object]:
    fixed_bus = STS3215Bus(transport=_NoopTransport())
    generic_bus = STS3215Bus(transport=_NoopTransport())
    fixed_snapshot = ServoSnapshot.create()
    generic_snapshot = ServoSnapshot.create()
    _configure_instrumentation(fixed_bus, fixed_snapshot, enabled=instrumented)
    _configure_instrumentation(generic_bus, generic_snapshot, enabled=instrumented)

    for _ in range(warmup):
        _prepare(fixed_bus, train)
        _fixed_frame(fixed_bus, fixed_snapshot)
        _prepare(generic_bus, train)
        _generic(generic_bus, generic_snapshot)
    np.testing.assert_array_equal(fixed_snapshot.status, generic_snapshot.status)
    np.testing.assert_array_equal(fixed_snapshot.stale, generic_snapshot.stale)
    np.testing.assert_allclose(
        fixed_snapshot.positions_rad, generic_snapshot.positions_rad, rtol=0, atol=0
    )
    np.testing.assert_allclose(
        fixed_snapshot.velocities_rad_s,
        generic_snapshot.velocities_rad_s,
        rtol=0,
        atol=0,
    )

    fixed_values: list[float] = []
    generic_values: list[float] = []
    gc_was_enabled = gc.isenabled()
    gc.disable()
    try:
        for batch_index in range(batches):
            order = (
                (
                    (_fixed_frame, fixed_bus, fixed_snapshot, fixed_values),
                    (_generic, generic_bus, generic_snapshot, generic_values),
                )
                if batch_index % 2 == 0
                else (
                    (_generic, generic_bus, generic_snapshot, generic_values),
                    (_fixed_frame, fixed_bus, fixed_snapshot, fixed_values),
                )
            )
            for operation, bus, snapshot, destination in order:
                destination.append(
                    _batch(
                        operation,
                        bus,
                        snapshot,
                        train,
                        iterations_per_batch,
                    )
                )
    finally:
        if gc_was_enabled:
            gc.enable()

    fixed_stats = _stats(fixed_values)
    generic_stats = _stats(generic_values)
    return {
        "instrumentation_enabled": instrumented,
        "synthetic_receive_chunks": 10 if instrumented else 0,
        "generic": generic_stats,
        "fixed_frame": fixed_stats,
        "mean_speedup": float(generic_stats["mean"] / fixed_stats["mean"]),
        "mean_saving_us": float(generic_stats["mean"] - fixed_stats["mean"]),
        "equivalence": {
            "status": True,
            "staleness": True,
            "positions": True,
            "velocities": True,
        },
    }


def run_benchmark(*, warmup: int, batches: int, iterations_per_batch: int) -> dict[str, object]:
    if warmup < 1 or batches < 2 or iterations_per_batch < 1:
        raise ValueError("warmup and iterations must be positive; batches must be at least 2")
    train = _response_train()
    if len(train) != 140:
        raise RuntimeError(f"expected a 140-byte train, got {len(train)}")
    return {
        "schema_version": "open_duck_x5.fixed_frame_benchmark.v2",
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "clock": "time.perf_counter_ns",
        },
        "population": {
            "warmup_pairs": warmup,
            "batches_per_parser": batches,
            "iterations_per_batch": iterations_per_batch,
            "total_iterations_per_parser": batches * iterations_per_batch,
            "response_bytes": len(train),
        },
        "unit": "microseconds_per_parse_and_decode_iteration",
        "modes": {
            "uninstrumented": _benchmark_mode(
                train,
                instrumented=False,
                warmup=warmup,
                batches=batches,
                iterations_per_batch=iterations_per_batch,
            ),
            "instrumented_10_chunks": _benchmark_mode(
                train,
                instrumented=True,
                warmup=warmup,
                batches=batches,
                iterations_per_batch=iterations_per_batch,
            ),
        },
        "hardware_access": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Offline fixed-frame versus generic STS3215 parser benchmark"
    )
    parser.add_argument("--warmup", type=int, default=1_000)
    parser.add_argument("--batches", type=int, default=20)
    parser.add_argument("--iterations-per-batch", type=int, default=1_000)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run_benchmark(
            warmup=args.warmup,
            batches=args.batches,
            iterations_per_batch=args.iterations_per_batch,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes((json.dumps(result, indent=2, sort_keys=True) + "\n").encode())
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
