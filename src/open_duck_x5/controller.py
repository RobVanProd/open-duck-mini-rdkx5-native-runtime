from __future__ import annotations

import threading
from dataclasses import dataclass, field

import numpy as np

from .clock import clock_ns


@dataclass(slots=True)
class ControllerReadout:
    commands: np.ndarray = field(default_factory=lambda: np.zeros(7, dtype=np.float64))
    pause_toggle: bool = False
    timestamp_ns: int = 0
    connected: bool = False


class NullController:
    def read_into(self, output: ControllerReadout) -> None:
        output.commands.fill(0.0)
        output.pause_toggle = False
        output.timestamp_ns = clock_ns()
        output.connected = True

    def close(self) -> None:
        return None


class PygameController:
    """Xbox/F710 command mapping with edge-triggered A pause parity."""

    def __init__(self, kind: str, *, frequency_hz: float = 20.0) -> None:
        if kind not in ("xbox", "f710"):
            raise ValueError("controller kind must be xbox or f710")
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
        self._a_was_pressed = False
        self._thread = threading.Thread(target=self._run, name=f"{kind}-controller", daemon=True)
        try:
            self._thread.start()
        except BaseException:
            pygame.quit()
            raise

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.pygame.event.pump()
                left_x = -float(self.joystick.get_axis(0))
                left_y = -float(self.joystick.get_axis(1))
                right_x_axis = 3 if self.kind == "f710" else 2
                right_x = -float(self.joystick.get_axis(right_x_axis))
                commands = self._commands
                commands[0] = np.clip(left_y * 0.15, -0.15, 0.15)
                commands[1] = np.clip(left_x * 0.2, -0.2, 0.2)
                commands[2] = np.clip(right_x, -1.0, 1.0)
                a_pressed = bool(self.joystick.get_button(0))
                toggle = a_pressed and not self._a_was_pressed
                self._a_was_pressed = a_pressed
                with self._lock:
                    self._pause_toggle = self._pause_toggle or toggle
                    self._timestamp_ns = clock_ns()
            except Exception:
                pass
            self._stop.wait(self.period_s)

    def read_into(self, output: ControllerReadout) -> None:
        with self._lock:
            np.copyto(output.commands, self._commands)
            output.pause_toggle = self._pause_toggle
            self._pause_toggle = False
            output.timestamp_ns = self._timestamp_ns
        output.connected = output.timestamp_ns != 0

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=1.0)
        self.pygame.quit()
