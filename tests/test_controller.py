from __future__ import annotations

import struct
import threading

import numpy as np
import pytest

import open_duck_x5.controller as controller_module
from open_duck_x5.controller import (
    ControllerReadout,
    LinuxJoystickController,
    PygameController,
)


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
    controller._emergency_stop = False
    controller._phase_frequency_factor = 1.0
    controller._a_was_pressed = False
    controller._b_was_pressed = False
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


def test_b_button_emergency_stop_is_edge_triggered() -> None:
    controller, joystick = make_controller()
    output = ControllerReadout()

    joystick.buttons[1] = True
    controller._poll_once()
    controller.read_into(output)
    assert output.emergency_stop is True

    controller.read_into(output)
    assert output.emergency_stop is False

    controller._poll_once()
    controller.read_into(output)
    assert output.emergency_stop is False

    joystick.buttons[1] = False
    controller._poll_once()
    joystick.buttons[1] = True
    controller._poll_once()
    controller.read_into(output)
    assert output.emergency_stop is True


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


def _js_event(value: int, event_type: int, number: int, *, initial: bool = False) -> bytes:
    if initial:
        event_type |= 0x80
    return struct.pack("<IhBB", 0, value, event_type, number)


def test_linux_joystick_reads_button_edges_without_a_polling_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    batches = [
        _js_event(0, 0x01, 0, initial=True)
        + _js_event(16384, 0x02, 0, initial=True)
        + _js_event(1, 0x01, 0),
        _js_event(0, 0x01, 0),
    ]
    closed: list[int] = []

    monkeypatch.setattr(controller_module.os, "open", lambda *_: 41)
    monkeypatch.setattr(controller_module.os, "close", closed.append)

    def fake_readv(fd: int, buffers) -> int:
        assert fd == 41
        if not batches:
            raise BlockingIOError
        payload = batches.pop(0)
        buffers[0][: len(payload)] = payload
        return len(payload)

    monkeypatch.setattr(controller_module.os, "readv", fake_readv, raising=False)
    monkeypatch.setattr(controller_module, "clock_ns", lambda: 123)
    controller = LinuxJoystickController("xbox")
    output = ControllerReadout()

    controller.read_into(output)
    assert output.connected is True
    assert output.pause_toggle is True
    assert output.timestamp_ns == 123
    assert output.commands[1] == pytest.approx(-0.1000030518509476)

    controller.read_into(output)
    assert output.pause_toggle is False
    controller.close()
    assert closed == [41]


def test_linux_joystick_reads_b_button_as_emergency_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    batches = [_js_event(1, 0x01, 1), _js_event(0, 0x01, 1)]
    monkeypatch.setattr(controller_module.os, "open", lambda *_: 46)
    monkeypatch.setattr(controller_module.os, "close", lambda _: None)

    def fake_readv(_fd: int, buffers) -> int:
        if not batches:
            raise BlockingIOError
        payload = batches.pop(0)
        buffers[0][: len(payload)] = payload
        return len(payload)

    monkeypatch.setattr(controller_module.os, "readv", fake_readv, raising=False)
    controller = LinuxJoystickController("xbox")
    output = ControllerReadout()

    controller.read_into(output)
    assert output.emergency_stop is True
    controller.read_into(output)
    assert output.emergency_stop is False
    controller.close()


def test_linux_joystick_disconnect_is_reported_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(controller_module.os, "open", lambda *_: 42)
    monkeypatch.setattr(controller_module.os, "close", lambda _: None)
    monkeypatch.setattr(
        controller_module.os,
        "readv",
        lambda *_: (_ for _ in ()).throw(OSError(19, "controller removed")),
        raising=False,
    )
    controller = LinuxJoystickController("xbox")
    output = ControllerReadout()

    controller.read_into(output)

    assert output.connected is False
    assert output.timestamp_ns == 0
    assert output.pause_toggle is False
    assert controller.last_error_errno == 19
    controller.close()


def test_linux_joystick_empty_queue_is_live_and_nonfatal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(controller_module.os, "open", lambda *_: 43)
    monkeypatch.setattr(controller_module.os, "close", lambda _: None)
    monkeypatch.setattr(
        controller_module.os,
        "readv",
        lambda *_: (_ for _ in ()).throw(BlockingIOError()),
        raising=False,
    )
    monkeypatch.setattr(controller_module, "clock_ns", lambda: 456)
    controller = LinuxJoystickController("xbox")
    output = ControllerReadout()

    controller.read_into(output)

    assert output.connected is True
    assert output.timestamp_ns == 456
    assert controller.last_error_errno is None
    controller.close()


def test_linux_joystick_retries_one_interrupted_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    payload = _js_event(1, 0x01, 0)
    monkeypatch.setattr(controller_module.os, "open", lambda *_: 44)
    monkeypatch.setattr(controller_module.os, "close", lambda _: None)

    def fake_readv(_fd: int, buffers) -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise InterruptedError
        buffers[0][: len(payload)] = payload
        return len(payload)

    monkeypatch.setattr(controller_module.os, "readv", fake_readv, raising=False)
    controller = LinuxJoystickController("xbox")
    output = ControllerReadout()

    controller.read_into(output)

    assert calls == 2
    assert output.connected is True
    assert output.pause_toggle is True
    controller.close()


def test_linux_joystick_per_tick_read_work_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    payload = _js_event(0, 0x01, 0, initial=True)
    monkeypatch.setattr(controller_module.os, "open", lambda *_: 45)
    monkeypatch.setattr(controller_module.os, "close", lambda _: None)

    def fake_readv(_fd: int, buffers) -> int:
        nonlocal calls
        calls += 1
        buffers[0][: len(payload)] = payload
        return len(payload)

    monkeypatch.setattr(controller_module.os, "readv", fake_readv, raising=False)
    controller = LinuxJoystickController("xbox")

    controller.read_into(ControllerReadout())

    assert calls == 1
    controller.close()


def test_linux_factory_never_constructs_pygame_controller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = object()
    monkeypatch.setattr(controller_module.os, "name", "posix")
    monkeypatch.setattr(
        controller_module,
        "LinuxJoystickController",
        lambda kind: sentinel if kind == "xbox" else None,
    )
    monkeypatch.setattr(
        controller_module,
        "PygameController",
        lambda *_: (_ for _ in ()).throw(AssertionError("pygame must not start")),
    )

    assert controller_module.create_controller("xbox") is sentinel
