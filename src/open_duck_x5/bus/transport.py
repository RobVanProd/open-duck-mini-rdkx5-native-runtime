from __future__ import annotations

import os
import select
import time
from pathlib import Path
from typing import Protocol

from ..clock import clock_ns


class ByteTransport(Protocol):
    device: str

    def write(self, data: bytes | bytearray | memoryview) -> int: ...

    def read_some_into(self, target: memoryview, deadline_ns: int) -> int: ...

    def flush_input(self) -> None: ...

    def close(self) -> None: ...


class SerialTransport:
    """Nonblocking serial transport with absolute monotonic read deadlines."""

    def __init__(self, device: str, baudrate: int = 1_000_000, write_timeout_s: float = 0.005):
        try:
            import serial
        except ImportError as exc:
            raise RuntimeError("pyserial is required for the serial bus") from exc
        self.device = device
        self.baudrate = int(baudrate)
        self._serial = serial.Serial(
            port=device,
            baudrate=self.baudrate,
            timeout=0,
            write_timeout=write_timeout_s,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            exclusive=True if os.name == "posix" else None,
        )
        try:
            self._fd = self._serial.fileno()
        except (AttributeError, OSError):
            self._fd = None

    def write(self, data: bytes | bytearray | memoryview) -> int:
        written = int(self._serial.write(data))
        if written != len(data):
            raise OSError(f"partial serial write: {written}/{len(data)} bytes")
        return written

    def read_some_into(self, target: memoryview, deadline_ns: int) -> int:
        while True:
            remaining_ns = deadline_ns - clock_ns()
            if remaining_ns <= 0:
                return 0
            if self._fd is not None and os.name == "posix":
                readable, _, _ = select.select([self._fd], [], [], remaining_ns / 1e9)
                if not readable:
                    return 0
                # A signal, scheduler stall, or another interpreter thread can
                # resume this call after the absolute deadline even though the
                # serial bytes are now buffered. Late data is stale data: do not
                # turn an over-deadline response into a reported success.
                if clock_ns() >= deadline_ns:
                    return 0
                return int(self._serial.readinto(target))
            waiting = int(getattr(self._serial, "in_waiting", 0))
            if waiting:
                return int(self._serial.readinto(target[: min(len(target), waiting)]))
            time.sleep(min(remaining_ns / 1e9, 0.0001))

    def flush_input(self) -> None:
        self._serial.reset_input_buffer()

    def close(self) -> None:
        self._serial.close()

    @property
    def sysfs_tty_path(self) -> Path | None:
        if os.name != "posix":
            return None
        name = Path(self.device).name
        path = Path("/sys/class/tty") / name / "device"
        return path.resolve() if path.exists() else None
