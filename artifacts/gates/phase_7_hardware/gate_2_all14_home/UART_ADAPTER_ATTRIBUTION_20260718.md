# Direct UART Attribution — 2026-07-18

Status: `READ_ONLY_COMPLETE`

Rob removed the USB cable, connected the Waveshare Bus Servo Adapter (A) UART
header to X5 physical pins 8/10 plus ground, changed the adapter's control-mode
pins/jumper, and powered on the robot. This attribution opened no serial device
and sent no servo packet.

## Read-only X5 evidence

- `lsusb` no longer contains QinHeng/WCH `1a86:55d3` or any USB serial device.
- `/dev/ttyS1` exists with owner `root:dialout` and mode `0660`.
- udev path: `/devices/platform/soc/34000000.a55_apb0/34070000.serial/tty/ttyS1`.
- driver: `/sys/bus/platform/drivers/dw-apb-uart`.
- device-tree `serial1` alias: `/soc/a55_apb0/serial@34070000`.
- kernel registration: `ttyS1`, 16550A, MMIO `0x34070000`, IRQ 34,
  base baud 6,250,000.
- pinctrl state is `default`; `lsio_uart1_rx` and `lsio_uart1_tx` are muxed to
  `34070000.serial` through group `uart1grp`.
- `/proc/tty/driver/serial` reported UART1 counters `tx:0 rx:0` at attribution.
- no process owned `/dev/ttyS1`.
- isolated CPU 7 and the existing RT boot configuration remain present.

This identifies `/dev/ttyS1` as the software endpoint for the physical pins
Rob connected. It does not prove TX/RX signal continuity, adapter logic voltage,
servo replies, or correct jumper position; those require the guarded torque-off
startup exchange.

## Safety assertion

After this read-only attribution, Rob confirmed that the robot is on its stand
and directed continuation of the same torque-off comparison. This satisfies the
repository's supported/benched assertion for the exact preregistered UART run;
it does not authorize torque, motion, policy inference, or any later gate.
