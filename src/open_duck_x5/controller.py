from __future__ import annotations

import errno
import math
import os
import threading
from contextlib import suppress
from dataclasses import dataclass, field

import numpy as np

from .clock import clock_ns


@dataclass(slots=True)
class ControllerReadout:
    commands: np.ndarray = field(default_factory=lambda: np.zeros(7, dtype=np.float64))
    pause_toggle: bool = False
    phase_frequency_factor: float = 1.0
    timestamp_ns: int = 0
    connected: bool = False


class NullController:
    def read_into(self, output: ControllerReadout) -> None:
        output.commands.fill(0.0)
        output.pause_toggle = False
        output.phase_frequency_factor = 1.0
        output.timestamp_ns = clock_ns()
        output.connected = True

    def close(self) -> None:
        return None


class LinuxJoystickController:
    """Nonblocking Linux joystick reader with no polling thread.

    Gate 5 runs the controller read on the real-time thread.  This avoids a
    second Python thread entering SDL/pygame during Bluetooth hotplug and
    holding the interpreter lock long enough to starve the servo transaction.
    The Linux joystick ABI emits fixed eight-byte records, so input is drained
    into one preallocated buffer without logging or blocking in the hot loop.
    """

    _EVENT_SIZE = 8
    _EVENT_CAPACITY = 64
    _EVENT_BUTTON = 0x01
    _EVENT_AXIS = 0x02
    _EVENT_INIT = 0x80

    def __init__(self, kind: str, *, device: str = "/dev/input/js0") -> None:
        if kind not in ("xbox", "f710"):
            raise ValueError("controller kind must be xbox or f710")
        self.kind = kind
        self.device = device
        flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        self._fd = os.open(device, flags)
        self._event_buffer = bytearray(self._EVENT_SIZE * self._EVENT_CAPACITY)
        self._event_view = memoryview(self._event_buffer)
        self._read_iov = (self._event_view,)
        self._axes = np.zeros(8, dtype=np.float64)
        self._buttons = np.zeros(16, dtype=np.bool_)
        self._commands = np.zeros(7, dtype=np.float64)
        self._timestamp_ns = 0
        self._pause_toggle = False
        self._phase_frequency_factor = 1.0
        self._head_control_mode = False
        self._connected = True
        self.last_error_errno: int | None = None

    @staticmethod
    def _clamp(value: float, lower: float, upper: float) -> float:
        if value < lower:
            return lower
        if value > upper:
            return upper
        return value

    def _apply_event(self, offset: int) -> None:
        value = int(self._event_buffer[offset + 4]) | (
            int(self._event_buffer[offset + 5]) << 8
        )
        if value >= 0x8000:
            value -= 0x10000
        raw_type = int(self._event_buffer[offset + 6])
        number = int(self._event_buffer[offset + 7])
        event_type = raw_type & ~self._EVENT_INIT
        is_initial = bool(raw_type & self._EVENT_INIT)
        if event_type == self._EVENT_AXIS and number < self._axes.size:
            self._axes[number] = max(-1.0, float(value) / 32767.0)
            return
        if event_type != self._EVENT_BUTTON or number >= self._buttons.size:
            return
        pressed = value != 0
        was_pressed = bool(self._buttons[number])
        self._buttons[number] = pressed
        if not is_initial and pressed and not was_pressed:
            if number == 0:
                self._pause_toggle = True
            elif number == 3:
                self._head_control_mode = not self._head_control_mode

    def _drain_events(self) -> None:
        # One read can drain the complete 64-event joydev queue.  Keep the
        # amount of work per control tick bounded even during reconnect storms.
        for _attempt in range(2):
            try:
                count = os.readv(self._fd, self._read_iov)
            except BlockingIOError:
                return
            except InterruptedError:
                continue
            except OSError as exc:
                self.last_error_errno = exc.errno
                self._connected = False
                return
            if count == 0 or count % self._EVENT_SIZE:
                self.last_error_errno = errno.EPROTO
                self._connected = False
                return
            for offset in range(0, count, self._EVENT_SIZE):
                self._apply_event(offset)
            return

    def _map_commands(self) -> None:
        left_x = -float(self._axes[0])
        left_y = -float(self._axes[1])
        right_x_axis = 3 if self.kind == "f710" else 2
        right_x = -float(self._axes[right_x_axis])
        if self._head_control_mode:
            self._commands[0:4] = 0.0
            self._commands[4] = left_y * (0.78 if left_y >= 0 else 0.3)
            self._commands[5] = left_x * 0.5
            self._commands[6] = right_x * 0.5
        else:
            self._commands[0] = self._clamp(left_y * 0.15, -0.15, 0.15)
            self._commands[1] = self._clamp(left_x * 0.2, -0.2, 0.2)
            self._commands[2] = self._clamp(right_x, -1.0, 1.0)
        self._phase_frequency_factor = 1.3 if bool(self._buttons[4]) else 1.0

    def read_into(self, output: ControllerReadout) -> None:
        self._drain_events()
        if self._connected:
            self._map_commands()
            self._timestamp_ns = clock_ns()
        np.copyto(output.commands, self._commands)
        output.pause_toggle = self._pause_toggle
        self._pause_toggle = False
        output.phase_frequency_factor = self._phase_frequency_factor
        output.timestamp_ns = self._timestamp_ns
        output.connected = self._connected

    def close(self) -> None:
        if self._fd >= 0:
            os.close(self._fd)
            self._fd = -1
        self._connected = False


class PygameController:
    """Xbox/F710 command mapping with inherited pause and head-mode parity."""

    def __init__(self, kind: str, *, frequency_hz: float = 20.0) -> None:
        if kind not in ("xbox", "f710"):
            raise ValueError("controller kind must be xbox or f710")
        if not math.isfinite(frequency_hz) or frequency_hz <= 0:
            raise ValueError("controller frequency must be finite and positive")
        try:
            import pygame
        except ImportError as exc:
            raise RuntimeError("install the 'hardware' extra for controller support") from exc
        self.pygame = pygame
        self.kind = kind
        self.period_s = 1.0 / frequency_hz
        pygame.init()
        pygame.joystick.init()
        try:
            if pygame.joystick.get_count() < 1:
                raise RuntimeError("no pygame joystick detected")
            self.joystick = pygame.joystick.Joystick(0)
            self.joystick.init()
        except BaseException:
            pygame.quit()
            raise
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._commands = np.zeros(7, dtype=np.float64)
        self._timestamp_ns = 0
        self._pause_toggle = False
        self._phase_frequency_factor = 1.0
        self._a_was_pressed = False
        self._y_was_pressed = False
        self._head_control_mode = False
        self._thread = threading.Thread(target=self._run, name=f"{kind}-controller", daemon=True)
        try:
            # Publish one fresh sample before Runtime can enter its first tick.
            self._poll_once()
            self._thread.start()
        except BaseException:
            pygame.quit()
            raise

    @staticmethod
    def _clamp(value: float, lower: float, upper: float) -> float:
        if value < lower:
            return lower
        if value > upper:
            return upper
        return value

    def _poll_once(self) -> None:
        self.pygame.event.pump()
        left_x = -float(self.joystick.get_axis(0))
        left_y = -float(self.joystick.get_axis(1))
        right_x_axis = 3 if self.kind == "f710" else 2
        right_x = -float(self.joystick.get_axis(right_x_axis))
        a_pressed = bool(self.joystick.get_button(0))
        y_pressed = bool(self.joystick.get_button(3))
        sprint_pressed = bool(self.joystick.get_button(4))
        pause_toggle = a_pressed and not self._a_was_pressed
        head_mode_toggle = y_pressed and not self._y_was_pressed
        self._a_was_pressed = a_pressed
        self._y_was_pressed = y_pressed

        with self._lock:
            if self._head_control_mode:
                self._commands[0:4] = 0.0
                head_yaw_scale = 0.5
                head_pitch_scale = 0.78 if left_y >= 0 else 0.3
                head_roll_scale = 0.5
                self._commands[4] = left_y * head_pitch_scale
                self._commands[5] = left_x * head_yaw_scale
                self._commands[6] = right_x * head_roll_scale
            else:
                self._commands[0] = self._clamp(left_y * 0.15, -0.15, 0.15)
                self._commands[1] = self._clamp(left_x * 0.2, -0.2, 0.2)
                self._commands[2] = self._clamp(right_x, -1.0, 1.0)
            self._pause_toggle = self._pause_toggle or pause_toggle
            self._phase_frequency_factor = 1.3 if sprint_pressed else 1.0
            self._timestamp_ns = clock_ns()
            if head_mode_toggle:
                # Match the inherited controller: Y changes the mode used by the
                # next sample, leaving the last head pose held in walking mode.
                self._head_control_mode = not self._head_control_mode

    def _run(self) -> None:
        while not self._stop.is_set():
            # Runtime detects the unchanged timestamp and pauses within 250 ms.
            with suppress(Exception):
                self._poll_once()
            self._stop.wait(self.period_s)

    def read_into(self, output: ControllerReadout) -> None:
        with self._lock:
            np.copyto(output.commands, self._commands)
            output.pause_toggle = self._pause_toggle
            self._pause_toggle = False
            output.phase_frequency_factor = self._phase_frequency_factor
            output.timestamp_ns = self._timestamp_ns
        output.connected = output.timestamp_ns != 0

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=1.0)
        self.pygame.quit()


def create_controller(kind: str):
    """Select the thread-free kernel joystick backend on Linux."""

    if os.name == "posix":
        return LinuxJoystickController(kind)
    return PygameController(kind)
