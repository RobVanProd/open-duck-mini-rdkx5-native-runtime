from __future__ import annotations

import math
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
