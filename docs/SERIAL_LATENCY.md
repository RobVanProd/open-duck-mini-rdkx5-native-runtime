# Serial Driver and Latency Verification

The inherited Pi guide installs an FTDI-only `latency_timer=1` rule but normally opens `/dev/ttyACM0`. A ttyACM device is commonly driven by `cdc_acm`, which does not expose the FTDI sysfs timer. The device name alone is not proof of the driver.

Run on the X5:

```bash
setup/verify_serial_path.sh /dev/ttyACM0
```

The artifact must capture:

- resolved `/sys/class/tty/<name>/device` path;
- bound driver/module;
- USB vendor/product IDs and topology;
- whether any `latency_timer` exists and its value;
- permissions and configured baud;
- kernel version.

If `latency_timer` exists, `setup/install_serial_latency_rule.sh <tty>` creates a device-specific udev rule setting it to 1 and verifies after replug/reload. If the attribute does not exist, the script exits with `UNSUPPORTED` and does not claim the setting was applied. The correct next step is to measure transaction latency on that driver, not to invent an equivalent knob.

Every hardware timing summary must include the verification output. Mock timing artifacts use `serial_driver=mock` and cannot close this item.

## Read-only X5 inventory result (2026-07-15)

The installed adapter resolves to `/dev/ttyACM0` with a stable `/dev/serial/by-id`
link. It is USB `1a86:55d3`, bound to `cdc_acm`, connected at USB full speed (12
Mbit/s), and exposed as `root:dialout` mode `0660`. No process held the device during
collection. No `latency_timer` attribute exists in the resolved tty/interface/device
ancestry, so the FTDI udev rule is inapplicable on this hardware. This closes the
driver-identification question, not the latency gate: actual round-trip and burst
timing still require the explicitly authorized probe.
