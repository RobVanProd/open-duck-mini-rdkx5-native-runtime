# USB/serial latency attribution diagnostic

This diagnostic is evidence-only. It does not advance Gate 2, enable torque,
move a joint, or run a policy. It captures three views of the same all-14
transaction sequence:

1. preallocated application timestamps from `STS3215Bus`;
2. kernel bulk-URB submission/completion events from `usbmon`;
3. an external logic-analyzer trace of the physical STS half-duplex data line.

The application trace is default-off. When enabled, the hot loop stores scalar
timestamps, read-call counts, and fourteen response-completion timestamps into
preallocated NumPy arrays. It performs no JSON construction or filesystem I/O
until the probe has stopped, the bus has closed, and final torque-off has been
attempted.

## Synchronization

Each tick records the round-robin extended-read servo ID. The request bytes are
visible in both `usbmon` and the physical UART trace, providing a marker that
does not alter goal positions, servo configuration, wire order, or the frozen
policy contract. SyncRead remains in the reviewed wire order ending `14,13`.

`usbmon` observes URB submission and completion, not individual USB tokens.
The logic analyzer is therefore required to separate USB/bridge residence from
physical UART serialization and servo turnaround.

## Physical analyzer requirements

- Connect analyzer ground to robot/adapter ground and its data input to the STS
  half-duplex signal through an input rated for the measured bus voltage.
- Use a high-impedance input; do not drive the bus from the analyzer.
- Sample at 20 MS/s or faster for the 1 Mbit/s 8N1 waveform.
- Start capture before the shell diagnostic and stop only after it reports final
  torque-off.
- Export the unmodified native capture plus a timestamped UART-decode CSV when
  supported. Record analyzer model, software version, threshold, sample rate,
  channel, and probe point.

Do not infer a logic-analyzer result from `usbmon`. If the analyzer is absent or
not connected, label the three-layer run `NOT_RUN` and do not substitute a
two-layer capture under the same authorization description.

## Board command

After a reviewed commit is present on the board and the external analyzer is
actively capturing:

```bash
sudo setup/capture_usbmon_torque_off.sh \
  --device /dev/ttyACM0 \
  --config /home/sunrise/duck_config.json \
  --ticks 50 \
  --output-dir /home/sunrise/duck-evidence/usbmon-logic-diagnostic \
  --hardware-authorized --suspended-or-benched
```

The script has no torque-enable argument. It refuses missing hardware
acknowledgements, an owned serial device, missing RT/usbmon prerequisites, and
overwriting an earlier capture. It records commit, kernel, USB bus/device,
clock anchors, stdout/stderr, hashes, the ordinary timing artifacts, the
application transaction trace, and raw `usbmon` text.

Correlate the software layers afterward with:

```bash
analyze_usbmon_latency \
  --usbmon usbmon.txt \
  --metadata metadata.json \
  --transaction-trace transaction-trace.jsonl \
  --output usbmon-analysis.json
```
