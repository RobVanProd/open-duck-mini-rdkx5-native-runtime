# Software + usbmon latency diagnostic

Status: `HALTED_STARTUP_INPUT_VOLTAGE_ERROR`

Rob clarified that the authorized diagnostic required no external equipment.
The exact software-only capture ran on the X5 from repository commit
`a50d32d22b7e60167a0087fd29ea02141628b1f5`, using application instrumentation
plus Linux `usbmon`. The robot remained suspended/benched. Torque enable,
motion, and policy execution were absent.

## Safety stop

The probe sent the initial all-14 torque-off SyncWrite and then performed its
required startup SyncRead. All fourteen response packets were received with
valid framing and routed IDs, but every response carried device status byte
`0x01`. The Feetech protocol defines bit 0 as the input-voltage error flag. The
probe therefore rejected every sample as stale/device-error and stopped before
entering the requested 50-tick loop.

The raw USB capture proves a second all-14 torque-off SyncWrite was submitted
and completed during final cleanup. No goal-position SyncWrite appears in the
capture. The serial device was unowned afterward, the driver remained
`cdc_acm`, and the temporary `usbmon` module was unloaded.

## Startup USB timing recovered before the stop

- initial torque-off bulk OUT URB: `75 us` submission-to-completion;
- 14-servo SyncRead request bulk OUT URB: `67 us`;
- SyncRead submission to first 10-byte response completion: `440 us`;
- SyncRead OUT completion to first response completion: `373 us`;
- first-to-last response completion span: `1,690 us`;
- SyncRead submission to final response completion: `2,130 us`;
- SyncRead OUT completion to final response completion: `2,063 us`;
- successive response-completion spacing: min/mean/median/max
  `123 / 130 / 125 / 147 us`;
- final torque-off bulk OUT URB: `74 us`.

The response order was exactly the reviewed wire order ending `14,13`. These
data already disprove a one-millisecond physical minimum per servo response,
but they do not constitute a completed per-tick latency run. No Gate 2 threshold
is advanced or waived.

## Recovered artifact hashes

- `metadata.json`:
  `dd1c2dd49aa3797cd8860a32e4232af8efbe9e6cf1870a8c518d680dbfb9e0ba`
- `probe-stderr.txt`:
  `c7b2f3ced80b8003afde6ba5e1dcc2e592631275b8def616f232e8fdb6b17c33`
- `usbmon.txt`:
  `dfb057994b5cd52f9a660bb2f9c4cbe53b10d7ee53686b6f68baea159abfa696`
- empty `timing.jsonl` and `probe-stdout.txt`:
  `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`

The next run is blocked until the servo supply condition is checked and the
all-servo `0x01` voltage status is no longer present. Do not mask or ignore the
device-status byte merely to obtain timing numbers.
