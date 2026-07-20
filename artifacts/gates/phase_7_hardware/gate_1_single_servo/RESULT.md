# Hardware Gate 1: Single-Servo Bus Result

Status: `PASS_REVIEWED`

The explicitly authorized suspended/benched Gate 1 probe ran servo ID 20 with
torque disabled for 10,000 present-position reads at 50 Hz and 1 Mbit/s.
No goal position was written and no policy inference ran.

## Provenance

- collection ID: `duck-evidence-gate1-20260715`
- archive size: 1,017,547 bytes
- archive SHA-256:
  `d8b5900df4905a6189572102daa88eba3ada16df8ad9c01d4acad94910943fa6`
- internal manifest: 199 files, all verified
- raw JSONL SHA-256:
  `a2c0708f5cb481ce0c21b72dc5976507f36846e732fa83696826de2646f9c311`
- summary SHA-256:
  `788c35fae422157d0582569f78fb25e18585357a3441566cfe218abfdf964d95`
- device/driver: `/dev/ttyACM0`, `cdc_acm`
- authorization flags: hardware `true`, suspended/benched `true`
- live kernel isolation in bundle: CPU 7

## Results

- ping: `ok`
- completed reads: `10,000 / 10,000`
- transaction failures: `0`
- timeout/CRC/partial/device/I/O/unexpected-ID counts: all `0`
- unexpected response lengths: `0`
- failure bursts: `0`
- telemetry records dropped: `0`
- round trip p95/p99/p99.9/max:
  `0.892052 / 0.924637 / 0.998007 / 1.034865 ms`
- tick p95/p99/p99.9/max:
  `20.059065 / 20.083874 / 20.090855 / 20.130398 ms`
- final torque-off: `ok`
- halt reason: none

Every pre-registered Gate 1 boolean is true, including complete stream,
authorization provenance, framing, zero failures, zero bursts, and final
torque-off. The machine-readable reviewed summary is
`single_servo_summary.json`.

Gate 2 remains separately unauthorized. This single-servo result neither proves
all-14 bus time nor decides whether the Python transaction loop needs Rust.
