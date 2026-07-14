from __future__ import annotations

import math
import struct
import threading
import time
from dataclasses import dataclass, field

import numpy as np

from .clock import clock_ns

BNO055_ADDRESS = 0x28
BNO055_PAGE_ID = 0x07
BNO055_ACCEL_DATA_X_LSB = 0x08
BNO055_UNIT_SEL = 0x3B
BNO055_OPR_MODE = 0x3D
BNO055_PWR_MODE = 0x3E
BNO055_SYS_TRIGGER = 0x3F
BNO055_AXIS_MAP_CONFIG = 0x41
BNO055_AXIS_MAP_SIGN = 0x42
BNO055_CONFIG_MODE = 0x00
BNO055_NDOF_MODE = 0x0C


class BNO055Smbus:
    """Minimal BNO055 sampler using smbus2 directly on the X5."""

    def __init__(
        self, *, bus_number: int = 5, address: int = BNO055_ADDRESS, upside_down: bool
    ) -> None:
        try:
            import smbus2
        except ImportError as exc:
            raise RuntimeError("install the 'hardware' extra for smbus2") from exc
        self.bus_number = int(bus_number)
        self.address = int(address)
        self.bus = smbus2.SMBus(self.bus_number)
        self.gyro_rad_s = np.zeros(3, dtype=np.float64)
        self.acceleration_m_s2 = np.zeros(3, dtype=np.float64)
        self.timestamp_ns = 0
        try:
            self._configure(upside_down)
        except BaseException:
            self.bus.close()
            raise

    def _write(self, register: int, value: int) -> None:
        self.bus.write_byte_data(self.address, register, value)

    def _configure(self, upside_down: bool) -> None:
        self._write(BNO055_OPR_MODE, BNO055_CONFIG_MODE)
        time.sleep(0.025)
        self._write(BNO055_PAGE_ID, 0)
        self._write(BNO055_PWR_MODE, 0)
        self._write(BNO055_SYS_TRIGGER, 0)
        # Default units: m/s^2 for acceleration and degrees/s for gyro.
        self._write(BNO055_UNIT_SEL, 0)
        # Inherited mapping: output X<-Y, Y<-X, Z<-Z.
        self._write(BNO055_AXIS_MAP_CONFIG, 0x21)
        # Sign bits are X,Y,Z at bits 2,1,0 in the Adafruit driver contract.
        self._write(BNO055_AXIS_MAP_SIGN, 0x07 if upside_down else 0x04)
        self._write(BNO055_OPR_MODE, BNO055_NDOF_MODE)
        time.sleep(0.02)

    def sample(self) -> int:
        # 0x08..0x19: accel, magnetometer, and gyro in one transaction.
        data = self.bus.read_i2c_block_data(self.address, BNO055_ACCEL_DATA_X_LSB, 18)
        ax, ay, az = struct.unpack_from("<hhh", bytes(data), 0)
        gx, gy, gz = struct.unpack_from("<hhh", bytes(data), 12)
        self.acceleration_m_s2[:] = (ax / 100.0, ay / 100.0, az / 100.0)
        degrees_to_radians = math.pi / 180.0
        self.gyro_rad_s[:] = (
            gx / 16.0 * degrees_to_radians,
            gy / 16.0 * degrees_to_radians,
            gz / 16.0 * degrees_to_radians,
        )
        self.timestamp_ns = clock_ns()
        return self.timestamp_ns

    def close(self) -> None:
        self.bus.close()


class X5FootContacts:
    LEFT_PIN_BCM = 22
    RIGHT_PIN_BCM = 27

    def __init__(self) -> None:
        try:
            import Hobot.GPIO as GPIO
        except ImportError as exc:
            raise RuntimeError("Hobot.GPIO is required on the RDK-X5") from exc
        self.GPIO = GPIO
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        try:
            GPIO.setup(self.LEFT_PIN_BCM, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            GPIO.setup(self.RIGHT_PIN_BCM, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        except (AttributeError, TypeError):
            GPIO.setup(self.LEFT_PIN_BCM, GPIO.IN)
            GPIO.setup(self.RIGHT_PIN_BCM, GPIO.IN)
        self.contacts = np.zeros(2, dtype=np.float32)
        self.timestamp_ns = 0

    def sample(self) -> int:
        # Frozen polarity: raw GPIO false means contact true.
        self.contacts[0] = float(not self.GPIO.input(self.LEFT_PIN_BCM))
        self.contacts[1] = float(not self.GPIO.input(self.RIGHT_PIN_BCM))
        self.timestamp_ns = clock_ns()
        return self.timestamp_ns

    def close(self) -> None:
        self.GPIO.cleanup([self.LEFT_PIN_BCM, self.RIGHT_PIN_BCM])


@dataclass(slots=True)
class SensorReadout:
    gyro_rad_s: np.ndarray = field(default_factory=lambda: np.zeros(3, dtype=np.float64))
    acceleration_m_s2: np.ndarray = field(
        default_factory=lambda: np.array([0.0, 0.0, 9.81], dtype=np.float64)
    )
    contacts: np.ndarray = field(default_factory=lambda: np.zeros(2, dtype=np.float32))
    imu_timestamp_ns: int = 0
    contacts_timestamp_ns: int = 0
    imu_age_ns: int = 0
    contacts_age_ns: int = 0
    imu_stale: bool = True
    contacts_stale: bool = True


@dataclass(frozen=True, slots=True)
class PublishedSensorReadout:
    """A complete immutable sensor sample published by one reference assignment."""

    gyro_rad_s: tuple[float, float, float]
    acceleration_m_s2: tuple[float, float, float]
    contacts: tuple[float, float]
    imu_timestamp_ns: int
    contacts_timestamp_ns: int


class SensorHub:
    def __init__(
        self,
        imu: BNO055Smbus,
        contacts: X5FootContacts,
        *,
        sample_frequency_hz: float = 100.0,
        stale_after_s: float = 0.04,
    ) -> None:
        if not math.isfinite(sample_frequency_hz) or sample_frequency_hz <= 0:
            raise ValueError("sensor sample frequency must be finite and positive")
        if not math.isfinite(stale_after_s) or stale_after_s <= 0:
            raise ValueError("sensor stale threshold must be finite and positive")
        self.imu = imu
        self.contacts = contacts
        self.period_ns = int(1e9 / sample_frequency_hz)
        self.stale_after_ns = int(stale_after_s * 1e9)
        self._published: PublishedSensorReadout | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="x5-sensors", daemon=True)
        try:
            self._thread.start()
        except BaseException:
            self.contacts.close()
            self.imu.close()
            raise

    def _run(self) -> None:
        deadline = clock_ns()
        while not self._stop.is_set():
            try:
                self.imu.sample()
                self.contacts.sample()
                # Device I/O happens before publication. The control loop reads a
                # single immutable object reference, so it can never wait behind
                # I2C or observe a half-updated IMU/contact pair.
                self._published = PublishedSensorReadout(
                    gyro_rad_s=tuple(float(value) for value in self.imu.gyro_rad_s),
                    acceleration_m_s2=tuple(
                        float(value) for value in self.imu.acceleration_m_s2
                    ),
                    contacts=tuple(float(value) for value in self.contacts.contacts),
                    imu_timestamp_ns=int(self.imu.timestamp_ns),
                    contacts_timestamp_ns=int(self.contacts.timestamp_ns),
                )
            except Exception:
                # The consumer observes age becoming stale; the hot path does not
                # print or silently reuse the sample.
                pass
            deadline += self.period_ns
            remaining = deadline - clock_ns()
            if remaining > 0:
                self._stop.wait(remaining / 1e9)

    def read_into(self, output: SensorReadout, now_ns: int) -> None:
        published = self._published
        if published is not None:
            output.gyro_rad_s[0] = published.gyro_rad_s[0]
            output.gyro_rad_s[1] = published.gyro_rad_s[1]
            output.gyro_rad_s[2] = published.gyro_rad_s[2]
            output.acceleration_m_s2[0] = published.acceleration_m_s2[0]
            output.acceleration_m_s2[1] = published.acceleration_m_s2[1]
            output.acceleration_m_s2[2] = published.acceleration_m_s2[2]
            output.contacts[0] = published.contacts[0]
            output.contacts[1] = published.contacts[1]
            output.imu_timestamp_ns = published.imu_timestamp_ns
            output.contacts_timestamp_ns = published.contacts_timestamp_ns
        output.imu_age_ns = max(0, now_ns - output.imu_timestamp_ns)
        output.contacts_age_ns = max(0, now_ns - output.contacts_timestamp_ns)
        output.imu_stale = output.imu_timestamp_ns == 0 or output.imu_age_ns > self.stale_after_ns
        output.contacts_stale = (
            output.contacts_timestamp_ns == 0 or output.contacts_age_ns > self.stale_after_ns
        )

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=1.0)
        self.contacts.close()
        self.imu.close()


class MockSensorHub:
    def __init__(self) -> None:
        self._gyro = np.zeros(3, dtype=np.float64)
        self._acceleration = np.array([0.0, 0.0, 9.81], dtype=np.float64)
        self._contacts = np.zeros(2, dtype=np.float32)

    def read_into(self, output: SensorReadout, now_ns: int) -> None:
        np.copyto(output.gyro_rad_s, self._gyro)
        np.copyto(output.acceleration_m_s2, self._acceleration)
        np.copyto(output.contacts, self._contacts)
        output.imu_timestamp_ns = now_ns
        output.contacts_timestamp_ns = now_ns
        output.imu_age_ns = 0
        output.contacts_age_ns = 0
        output.imu_stale = False
        output.contacts_stale = False

    def close(self) -> None:
        return None
