from __future__ import annotations

import struct
import threading

import numpy as np
import pytest

import open_duck_x5.sensors as sensors_module
from open_duck_x5.imu_calibration import BNO055Calibration
from open_duck_x5.sensors import (
    BNO055Smbus,
    PublishedSensorReadout,
    SensorHub,
    SensorReadout,
    X5FootContacts,
)


class FakeRegisterBus:
    def __init__(self, *, chip_id: int = sensors_module.BNO055_CHIP_ID) -> None:
        self.writes: list[tuple[int, int, int]] = []
        self.registers = bytearray(256)
        self.registers[sensors_module.BNO055_CHIP_ID_REGISTER] = chip_id
        self.registers[sensors_module.BNO055_CALIBRATION_STATUS] = 0xFF

    def write_byte_data(self, address: int, register: int, value: int) -> None:
        self.writes.append((address, register, value))
        self.registers[register] = value

    def read_byte_data(self, address: int, register: int) -> int:
        assert address == 0x28
        return self.registers[register]

    def write_i2c_block_data(
        self, address: int, register: int, values: list[int]
    ) -> None:
        assert address == 0x28
        self.registers[register : register + len(values)] = bytes(values)

    def read_i2c_block_data(
        self, address: int, register: int, length: int
    ) -> list[int]:
        assert address == 0x28
        return list(self.registers[register : register + length])


@pytest.mark.parametrize(
    ("upside_down", "expected_sign"),
    [(False, 0x04), (True, 0x07)],
)
def test_bno055_configuration_preserves_frozen_axis_mapping(
    monkeypatch: pytest.MonkeyPatch,
    upside_down: bool,
    expected_sign: int,
) -> None:
    monkeypatch.setattr(sensors_module.time, "sleep", lambda _seconds: None)
    bus = FakeRegisterBus()
    imu = object.__new__(BNO055Smbus)
    imu.bus = bus
    imu.address = 0x28

    imu._configure(upside_down, None)

    assert (0x28, sensors_module.BNO055_AXIS_MAP_CONFIG, 0x21) in bus.writes
    assert (0x28, sensors_module.BNO055_AXIS_MAP_SIGN, expected_sign) in bus.writes
    assert bus.writes[-1] == (0x28, sensors_module.BNO055_OPR_MODE, 0x0C)
    assert imu.describe()["identity_verified"] is True
    assert imu.describe()["calibration_applied"] is False


def test_bno055_applies_and_reads_back_frozen_calibration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sensors_module.time, "sleep", lambda _seconds: None)
    calibration = BNO055Calibration.from_mapping(
        {
            "schema_version": "open_duck_x5.bno055_calibration.v1",
            "source_format": "apirrone.imu_calib_data.pkl",
            "source_sha256": "a" * 64,
            "offsets_accelerometer": [1, -2, 3],
            "offsets_gyroscope": [-4, 5, -6],
            "offsets_magnetometer": [7, -8, 9],
        }
    )
    bus = FakeRegisterBus()
    imu = object.__new__(BNO055Smbus)
    imu.bus = bus
    imu.address = 0x28

    imu._configure(True, calibration)

    diagnostics = imu.describe()
    assert diagnostics["calibration_applied"] is True
    assert diagnostics["calibration_readback_verified"] is True
    assert diagnostics["calibration_source_sha256"] == "a" * 64
    assert diagnostics["calibration_readback"] == {
        "offsets_accelerometer": [1, -2, 3],
        "offsets_gyroscope": [-4, 5, -6],
        "offsets_magnetometer": [7, -8, 9],
    }
    assert diagnostics["calibration_status"] == {
        "system": 3,
        "gyroscope": 3,
        "accelerometer": 3,
        "magnetometer": 3,
    }


def test_bno055_rejects_wrong_chip_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sensors_module.time, "sleep", lambda _seconds: None)
    imu = object.__new__(BNO055Smbus)
    imu.bus = FakeRegisterBus(chip_id=0x00)
    imu.address = 0x28

    with pytest.raises(RuntimeError, match="bad BNO055 chip id"):
        imu._configure(False, None)


def test_bno055_rejects_calibration_readback_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BadReadbackBus(FakeRegisterBus):
        def read_i2c_block_data(
            self, address: int, register: int, length: int
        ) -> list[int]:
            if register == sensors_module.BNO055_OFFSET_ACCEL:
                return [0] * length
            return super().read_i2c_block_data(address, register, length)

    monkeypatch.setattr(sensors_module.time, "sleep", lambda _seconds: None)
    calibration = BNO055Calibration.from_mapping(
        {
            "schema_version": "open_duck_x5.bno055_calibration.v1",
            "source_format": "apirrone.imu_calib_data.pkl",
            "source_sha256": "a" * 64,
            "offsets_accelerometer": [1, 2, 3],
            "offsets_gyroscope": [4, 5, 6],
            "offsets_magnetometer": [7, 8, 9],
        }
    )
    imu = object.__new__(BNO055Smbus)
    imu.bus = BadReadbackBus()
    imu.address = 0x28

    with pytest.raises(RuntimeError, match="offsets_accelerometer readback mismatch"):
        imu._configure(False, calibration)


def test_bno055_sample_decodes_frozen_units(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = bytearray(18)
    struct.pack_into("<hhh", payload, 0, 100, -250, 981)
    struct.pack_into("<hhh", payload, 12, 16, -32, 180)

    class FakeSampleBus:
        def read_i2c_block_data(self, address: int, register: int, length: int) -> list[int]:
            assert (address, register, length) == (0x28, 0x08, 18)
            return list(payload)

    imu = object.__new__(BNO055Smbus)
    imu.bus = FakeSampleBus()
    imu.address = 0x28
    imu.gyro_rad_s = np.zeros(3, dtype=np.float64)
    imu.acceleration_m_s2 = np.zeros(3, dtype=np.float64)
    imu.timestamp_ns = 0
    monkeypatch.setattr(sensors_module, "clock_ns", lambda: 123456789)

    assert imu.sample() == 123456789
    np.testing.assert_allclose(imu.acceleration_m_s2, [1.0, -2.5, 9.81])
    np.testing.assert_allclose(imu.gyro_rad_s, np.deg2rad([1.0, -2.0, 11.25]))


def test_contact_sample_preserves_active_low_polarity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeGPIO:
        @staticmethod
        def input(pin: int) -> bool:
            return pin == X5FootContacts.RIGHT_PIN_BCM

    contacts = object.__new__(X5FootContacts)
    contacts.GPIO = FakeGPIO()
    contacts.contacts = np.zeros(2, dtype=np.float32)
    contacts.timestamp_ns = 0
    monkeypatch.setattr(sensors_module, "clock_ns", lambda: 987654321)

    assert contacts.sample() == 987654321
    np.testing.assert_array_equal(contacts.contacts, [1.0, 0.0])


def test_sensor_read_uses_one_complete_published_sample() -> None:
    hub = object.__new__(SensorHub)
    hub.stale_after_ns = 40_000_000
    hub._published = PublishedSensorReadout(
        gyro_rad_s=(1.0, 2.0, 3.0),
        acceleration_m_s2=(4.0, 5.0, 6.0),
        contacts=(1.0, 0.0),
        imu_timestamp_ns=90_000_000,
        contacts_timestamp_ns=91_000_000,
    )
    output = SensorReadout()

    hub.read_into(output, 100_000_000)

    np.testing.assert_array_equal(output.gyro_rad_s, [1.0, 2.0, 3.0])
    np.testing.assert_array_equal(output.acceleration_m_s2, [4.0, 5.0, 6.0])
    np.testing.assert_array_equal(output.contacts, [1.0, 0.0])
    assert output.imu_age_ns == 10_000_000
    assert output.contacts_age_ns == 9_000_000
    assert output.imu_stale is False
    assert output.contacts_stale is False


def test_control_read_does_not_wait_for_blocked_i2c() -> None:
    class BlockingImu:
        def __init__(self) -> None:
            self.gyro_rad_s = np.zeros(3, dtype=np.float64)
            self.acceleration_m_s2 = np.zeros(3, dtype=np.float64)
            self.timestamp_ns = 0
            self.entered = threading.Event()
            self.release = threading.Event()

        def sample(self) -> int:
            self.entered.set()
            self.release.wait(2.0)
            self.timestamp_ns = 1
            return self.timestamp_ns

        def close(self) -> None:
            self.release.set()

    class FakeContacts:
        def __init__(self) -> None:
            self.contacts = np.zeros(2, dtype=np.float32)
            self.timestamp_ns = 0

        def sample(self) -> int:
            self.timestamp_ns = 1
            return self.timestamp_ns

        def close(self) -> None:
            return None

    imu = BlockingImu()
    hub = SensorHub(imu, FakeContacts())
    output = SensorReadout()
    read_done = threading.Event()

    def read_once() -> None:
        hub.read_into(output, 100_000_000)
        read_done.set()

    reader = threading.Thread(target=read_once, daemon=True)
    try:
        assert imu.entered.wait(0.5)
        reader.start()
        assert read_done.wait(0.2), "control read blocked behind the I2C sampler"
        assert output.imu_stale is True
        assert output.contacts_stale is True
    finally:
        imu.release.set()
        hub.close()
        reader.join(timeout=1.0)


def test_sensor_worker_counts_transient_device_errors() -> None:
    class FlakyImu:
        def __init__(self) -> None:
            self.gyro_rad_s = np.zeros(3, dtype=np.float64)
            self.acceleration_m_s2 = np.array([0.0, 0.0, 9.81], dtype=np.float64)
            self.timestamp_ns = 0
            self.calls = 0
            self.error_seen = threading.Event()
            self.success_seen = threading.Event()

        def sample(self) -> int:
            self.calls += 1
            if self.calls == 1:
                self.error_seen.set()
                raise RuntimeError("injected I2C error")
            self.timestamp_ns += 1
            self.success_seen.set()
            return self.timestamp_ns

        @staticmethod
        def close() -> None:
            return None

        @staticmethod
        def describe() -> dict[str, object]:
            return {}

    class FakeContacts:
        def __init__(self) -> None:
            self.contacts = np.zeros(2, dtype=np.float32)
            self.timestamp_ns = 0

        def sample(self) -> int:
            self.timestamp_ns += 1
            return self.timestamp_ns

        @staticmethod
        def close() -> None:
            return None

    imu = FlakyImu()
    hub = SensorHub(imu, FakeContacts(), sample_frequency_hz=1000.0)
    try:
        assert imu.error_seen.wait(0.5)
        assert imu.success_seen.wait(0.5)
    finally:
        hub.close()

    diagnostics = hub.diagnostics()
    assert diagnostics["sample_errors"] == 1
    assert diagnostics["sample_successes"] >= 1
    assert diagnostics["max_consecutive_errors"] == 1
    assert diagnostics["last_error_type"] == "RuntimeError"
