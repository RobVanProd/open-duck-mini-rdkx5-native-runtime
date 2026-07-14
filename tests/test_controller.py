from __future__ import annotations

import threading

import numpy as np
import pytest

import open_duck_x5.controller as controller_module
from open_duck_x5.controller import ControllerReadout, PygameController


class FakeEventQueue:
    def __init__(self) -> None:
        self.pump_calls = 0

    def pump(self) -> None:
        self.pump_calls += 1


class FakeJoystick:
    def __init__(self) -> None:
        self.axes = [0.0] * 6
        self.buttons = [False] * 11

    def get_axis(self, index: int) -> float:
        return self.axes[index]

    def get_button(self, index: int) -> bool:
        return self.buttons[index]


def make_controller(kind: str = "xbox") -> tuple[PygameController, FakeJoystick]:
    controller = object.__new__(PygameController)
    controller.pygame = type("FakePygame", (), {"event": FakeEventQueue()})()
    controller.kind = kind
    controller.joystick = FakeJoystick()
    controller._lock = threading.Lock()
    controller._commands = np.zeros(7, dtype=np.float64)
    controller._timestamp_ns = 0
    controller._pause_toggle = False
    controller._phase_frequency_factor = 1.0
    controller._a_was_pressed = False
    controller._y_was_pressed = False
    controller._head_control_mode = False
    return controller, controller.joystick


@pytest.mark.parametrize(("kind", "right_axis"), [("xbox", 2), ("f710", 3)])
def test_controller_preserves_walk_axis_mapping_and_ranges(
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    right_axis: int,
) -> None:
    controller, joystick = make_controller(kind)
    joystick.axes[0] = 0.5
    joystick.axes[1] = -1.0
    joystick.axes[right_axis] = 0.25
    monkeypatch.setattr(controller_module, "clock_ns", lambda: 123)

    controller._poll_once()
    output = ControllerReadout()
    controller.read_into(output)

    np.testing.assert_allclose(output.commands[:3], [0.15, -0.1, -0.25])
    np.testing.assert_array_equal(output.commands[3:], [0.0, 0.0, 0.0, 0.0])
    assert output.timestamp_ns == 123
    assert output.connected is True


def test_a_button_pause_toggle_is_edge_triggered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, joystick = make_controller()
    monkeypatch.setattr(controller_module, "clock_ns", lambda: 100)
    output = ControllerReadout()

    joystick.buttons[0] = True
    controller._poll_once()
    controller.read_into(output)
    assert output.pause_toggle is True
    controller.read_into(output)
    assert output.pause_toggle is False

    controller._poll_once()
    controller.read_into(output)
    assert output.pause_toggle is False

    joystick.buttons[0] = False
    controller._poll_once()
    joystick.buttons[0] = True
    controller._poll_once()
    controller.read_into(output)
    assert output.pause_toggle is True


def test_y_button_enables_inherited_head_command_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, joystick = make_controller()
    monkeypatch.setattr(controller_module, "clock_ns", lambda: 200)
    joystick.axes[0] = -0.4
    joystick.axes[1] = -0.5
    joystick.axes[2] = 0.6

    joystick.buttons[3] = True
    controller._poll_once()
    assert controller._head_control_mode is True
    controller._poll_once()
    output = ControllerReadout()
    controller.read_into(output)

    np.testing.assert_array_equal(output.commands[0:4], [0.0, 0.0, 0.0, 0.0])
    np.testing.assert_allclose(output.commands[4:7], [0.39, 0.2, -0.3])

    joystick.buttons[3] = False
    controller._poll_once()
    joystick.buttons[3] = True
    controller._poll_once()
    assert controller._head_control_mode is False
    held_head_pose = output.commands[4:7].copy()
    controller._poll_once()
    controller.read_into(output)
    np.testing.assert_allclose(output.commands[4:7], held_head_pose)


def test_left_bumper_preserves_inherited_sprint_phase_factor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, joystick = make_controller()
    monkeypatch.setattr(controller_module, "clock_ns", lambda: 300)
    output = ControllerReadout()

    joystick.buttons[4] = True
    controller._poll_once()
    controller.read_into(output)
    assert output.phase_frequency_factor == 1.3

    joystick.buttons[4] = False
    controller._poll_once()
    controller.read_into(output)
    assert output.phase_frequency_factor == 1.0
