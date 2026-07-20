# X5 Fixed-Frame Parser Benchmark

Status: `OFFLINE_X5_COMPLETE_NO_SERIAL`

Source commit `6138f02` benchmarked the generic STS3215 packet parser/decoder
against the fixed-order 14 × 10-byte candidate using a synthetic, checksum-valid
140-byte response train. Both paths produced bit-exact status, staleness,
position, and velocity outputs. The benchmark does not instantiate
`SerialTransport`, and `/dev/ttyS1` was verified unowned before and after each
run.

The matched population was 1,000 warm-up pairs followed by 20 batches of 1,000
iterations per parser. It ran under `SCHED_FIFO 80` on isolated CPU 7.

| Mode | Generic mean | Fixed mean | Saving | Speedup |
| --- | ---: | ---: | ---: | ---: |
| `schedutil`, no transaction trace | 577.187 us | 300.357 us | 276.829 us | 1.922× |
| `schedutil`, 10 receive chunks traced | 737.019 us | 478.085 us | 258.933 us | 1.542× |
| `performance`, no transaction trace | 580.104 us | 295.620 us | 284.484 us | 1.962× |
| `performance`, 10 receive chunks traced | 737.379 us | 469.159 us | 268.219 us | 1.572× |

The continuous benchmark keeps the CPU busy, so switching from `schedutil` to
`performance` does not test the 50 Hz wake-from-idle condition. The governor
was changed reversibly for the second run and restored to `schedutil`; the
before/during/after evidence reads `schedutil/performance/schedutil`.

The fixed parser is valid and measurably faster, but its 259-277 us saving is
not sufficient by itself to close the measured 656 us mean deficit, much less
the complete-sweep maximum. It is therefore not advanced directly to a serial
run. The live exact-collector trace provides a stronger next hypothesis:
group parse tail versus group read-call count correlates at `-0.953669`. Fewer
read wakeups imply more idle time immediately before parsing, while the board's
single CPU-frequency policy is `schedutil` over 300 MHz-1.5 GHz. A one-variable
50 Hz governor A/B is preregistered separately.

## Provenance

- source commit: `6138f02`;
- source archive SHA-256:
  `7b64f4ce322c1b8bf40a06858bc2b719e95be22b3ae04966c3e6c5e55a0156c7`;
- schedutil RT CPU 7 result SHA-256:
  `7851c4d2ed7aa314732887215bcbde1544d6e21c925512106df7e2bfef4c08af`;
- performance RT CPU 7 result SHA-256:
  `8ca5a832e6b333af56cdb4a04fea34cc21e7041eb327e2fcae3dc4c280d4f7f5`.

These are CPU-only results. They do not clear a servo-bus or hardware gate.
