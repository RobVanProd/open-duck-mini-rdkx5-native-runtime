# USB Adapter Attribution — 2026-07-15

Status: `READ_ONLY_COMPLETE`

Rob requested adapter attribution before another torque-off timing run. The X5
was accessed only for read-only operating-system inventory. No servo device was
opened and no servo packet, torque command, or target was sent during this
attribution step.

## Results

`lsusb` reported:

```text
Bus 001 Device 003: ID 1a86:55d3 QinHeng Electronics USB Single Serial
```

The serial endpoint and udev properties reported:

```text
/dev/ttyACM0
ID_VENDOR_ID=1a86
ID_MODEL_ID=55d3
ID_USB_DRIVER=cdc_acm
/sys/bus/usb/drivers/cdc_acm
```

There was no `/dev/ttyUSB0`, no FTDI device in `lsusb`, and no
`latency_timer` file below the tty device's sysfs path. The FTDI default-16-ms
latency-timer hypothesis is therefore inapplicable to this adapter. This result
is consistent with the earlier WCH CH343 vendor-driver experiment and
strengthens direct UART as the next transport A/B after a complete USB sample.

## Scope boundary

This inventory does not establish UART performance and does not authorize a
wiring change. Rob plans to connect the bus to X5 UART pins 8/10 plus ground
when physically present; that later comparison requires a separately captured
device/driver attribution and the same frozen timing population.
