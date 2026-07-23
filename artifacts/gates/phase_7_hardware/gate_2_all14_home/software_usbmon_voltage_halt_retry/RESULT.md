# Software + usbmon latency diagnostic retry

Status: `HALTED_STARTUP_INPUT_VOLTAGE_ERROR_REPRODUCED`

After Rob inspected the visible power connections, rebooted the robot, and
explicitly authorized one retry, the same software-only diagnostic ran on the
X5 from repository commit
`a50d32d22b7e60167a0087fd29ea02141628b1f5`. The capture used application
instrumentation plus Linux `usbmon`; no external analyzer was present or
required. Torque enable, motion, and policy execution were absent.

## Reproduced safety stop

The probe sent the initial all-14 torque-off SyncWrite and one startup SyncRead.
All fourteen response packets were received with valid framing in the reviewed
wire order ending `14,13`, but every response again carried device status byte
`0x01`. The Feetech protocol defines bit 0 as the input-voltage error flag. The
probe rejected the samples and halted before entering the requested 50-tick
loop.

The USB capture contains a second all-14 torque-off SyncWrite during final
cleanup and no goal-position SyncWrite. Afterward `/dev/ttyACM0` was unowned,
the adapter remained on `cdc_acm`, and the temporary `usbmon` module was absent.

## Startup USB timing

- initial torque-off bulk OUT URB: `99 us` submission-to-completion;
- 14-servo SyncRead request bulk OUT URB: `71 us`;
- SyncRead submission to first 10-byte response completion: `459 us`;
- SyncRead OUT completion to first response completion: `388 us`;
- first-to-last response completion span: `1,666 us`;
- SyncRead submission to final response completion: `2,125 us`;
- SyncRead OUT completion to final response completion: `2,054 us`;
- successive response-completion spacing: min/mean/median/max
  `116 / 128.2 / 131 / 147 us`;
- final torque-off bulk OUT URB: `76 us`.

This independently reproduces the first capture: fourteen replies cross the USB
interface in approximately `2.13 ms`, not one millisecond per servo. The full
per-tick timing attribution remains incomplete because the safety verifier
stopped before the loop.

## Recovered artifact hashes

- `metadata.json`:
  `01ad57c9037d9efcd95744a95aa20a4586a1af223838491371ddb0e4f252f909`
- `probe-stderr.txt`:
  `c7b2f3ced80b8003afde6ba5e1dcc2e592631275b8def616f232e8fdb6b17c33`
- `usbmon.txt`:
  `78a79aae67ba77b72ea2b7d66d82a1c6c25effc18567778ec084af2ec71083d5`
- empty `timing.jsonl` and `probe-stdout.txt`:
  `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`

Do not retry this same capture again. The next useful software-only step is a
separately reviewed torque-off read of the servos' present-voltage telemetry,
which can distinguish a reported low/high supply condition from a connection
problem without suppressing the status bit or enabling motion.
