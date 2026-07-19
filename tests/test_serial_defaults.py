from __future__ import annotations

import argparse
import inspect

from open_duck_x5 import (
    evidence_collector,
    probe,
    runtime,
    single_servo_probe,
    voltage_limit_probe,
    voltage_probe,
)
from open_duck_x5.bus.sts3215 import STS3215Bus
from open_duck_x5.tools.common import add_bus_arguments


def test_active_x5_entrypoints_default_to_direct_uart() -> None:
    assert probe.build_parser().get_default("device") == "/dev/ttyS1"
    assert runtime.build_parser().get_default("device") == "/dev/ttyS1"
    assert single_servo_probe.build_parser().get_default("device") == "/dev/ttyS1"
    assert voltage_probe.build_parser().get_default("device") == "/dev/ttyS1"
    assert voltage_limit_probe.build_parser().get_default("device") == "/dev/ttyS1"
    assert evidence_collector.build_parser().get_default("serial_device") == "/dev/ttyS1"


def test_script_parity_and_bus_defaults_use_direct_uart() -> None:
    parser = argparse.ArgumentParser()
    add_bus_arguments(parser)
    assert parser.get_default("device") == "/dev/ttyS1"
    assert inspect.signature(STS3215Bus).parameters["device"].default == "/dev/ttyS1"
