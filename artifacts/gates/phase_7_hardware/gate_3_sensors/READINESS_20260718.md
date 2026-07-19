# Gate 3 readiness inventory — 2026-07-18

Status: `BLOCKED_CALIBRATION_REQUIRED`

This is an authorized non-moving readiness inventory, not a Gate 3 capture or
result. The board was reached at `192.168.1.50` as `sunrise`. No servo device was
opened, no torque or target command was issued, no policy was loaded, and no
BNO055 register was written. The only state change was a temporary input-only
claim of the two contact GPIOs; both were released and the post-cleanup
`hb_gpioinfo` output contained no `sysfs` claims.

## Calibration-file attribution

The search covered `/home/sunrise` for `imu_calib_data.pkl`, `*imu*calib*`, and
`*bno*calib*`. It returned no files. `/home/sunrise/imu_calibration.json` was
also absent.

The installed preserved runtime confirms that both `imu.py` and `raw_imu.py`
load `imu_calib_data.pkl` relative to the process working directory. When it is
absent, `raw_imu.py` prints `imu_calib_data.pkl not found` and
`Imu is running uncalibrated`. The deployed walking scripts import this
`raw_imu.Imu` path. There is therefore no legacy profile to convert or hash.

## Read-only BNO055 state

`/dev/i2c-5` existed, belonged to group `i2c`, and had no reported owner. Byte
reads at address `0x28` returned:

| Register | Value | Interpretation |
| --- | ---: | --- |
| chip ID `0x00` | `0xa0` | expected BNO055 identity |
| calibration `0x35` | `0x00` | system/gyro/accel/mag all zero |
| unit selection `0x3b` | `0x80` | device default, not runtime contract |
| operation mode `0x3d` | `0x10` | low mode nibble `0x0` (CONFIG) |
| power mode `0x3e` | `0x00` | normal power |
| axis map `0x41` | `0x24` | device default, not frozen `0x21` |
| axis sign `0x42` | `0x00` | device default, not frozen `0x07` |

These values prove identity but do not provide usable calibration offsets. They
also confirm that the readiness read did not silently treat default sensor state
as the runtime's configured state.

## Contact GPIO mapping

`hb_gpioinfo` required passwordless read-only `sudo`, which was available. With
each Hobot.GPIO BCM input claimed separately:

| Contract input | Physical pin | X5 native line | Alternate pin name | Raw |
| --- | ---: | ---: | --- | ---: |
| left / BCM22 | 15 | GPIO 388 | `LSIO_UART2_TX` | `1` |
| right / BCM27 | 13 | GPIO 379 | `LSIO_UART7_RX` | `1` |

The installed Hobot.GPIO build did not accept the `PUD_UP` call signature, so
the runtime fallback input setup path is the applicable path on this board.
Both input claims appeared as `sysfs` while open. Cleanup succeeded and a final
inventory showed no remaining `sysfs` claims.

## Decision

The GPIO and I2C endpoint prerequisites are ready. Gate 3 remains blocked—not
failed—because a physical BNO055 calibration must be completed and saved before
the offset profile/hash and exact source-bound capture launcher can be frozen.
Offsets will not be guessed, copied from another robot, or inferred from the
zero calibration status.
