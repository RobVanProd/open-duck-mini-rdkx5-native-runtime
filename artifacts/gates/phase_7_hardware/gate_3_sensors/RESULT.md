# Hardware Gate 3 result — IMU and contacts

Status: `PASS_REVIEWED`

The corrected, separately authorized nine-label matrix completed on the
supported RDK-X5 robot on 2026-07-19. Each label captured exactly 250 samples at
50 Hz from the 100 Hz sensor worker after the bounded 2.0-second initial-sample
barrier. All 2,250 rows have fresh IMU and contact timestamps; every per-label
worker reported zero sample errors. The complete 67-entry board checksum set
reproduced without a mismatch.

No servo endpoint was opened. Runner provenance records
`servo_bus_accessed=false`, `torque_enabled=false`,
`goal_position_writes=0`, `policy_loaded=false`, and
`policy_inference_count=0`. After completion `/dev/i2c-5` was unowned, both
GPIO claims were released, and the guarded screen session had exited.

## Physical-label review

Rob physically supported and labeled every state immediately before capture.
Independent raw-row reduction found:

- upright mean acceleration `[0.38476, 0.91704, 9.79360] m/s²`;
- nose-forward/back X means `-5.00064/+6.85560 m/s²`, an opposing separation
  of `11.85624 m/s²`;
- left/right tilt Y means `-7.88388/+7.20860 m/s²`, an opposing separation of
  `15.09248 m/s²`;
- mean acceleration norms from `9.58981` to `9.84396 m/s²` across all labels;
- exact contact means `[0,0]`, `[1,0]`, `[0,1]`, and `[1,1]` for the four
  preregistered contact states.

The `upright` orientation-only capture observed four simultaneous true samples
per contact (`0.016` mean). This is recorded rather than hidden; it does not
set the contact gate, whose four dedicated, physically confirmed populations
were exact over all 1,000 samples.

The opposing axes, positive upright Z gravity, exact dedicated switch
populations, and typed physical confirmations are unambiguous and not
reversed. Human review therefore promotes Gate 3 from the deliberately
review-only automated packet to `PASS_REVIEWED`.

## Provenance

- corrected source commit:
  `aac7410f241a5419af2257ba9635e6755d7b5ae8`;
- source archive SHA-256:
  `d41e516ec52558ec169c0f8f017d8959aed657a999786ed5e8e7716895ced9a0`;
- live config SHA-256:
  `131a7b8fce1107b14f4727562f44f9e17324caf7fc22512ad7115911f050991b`;
- calibration profile SHA-256:
  `e7518b0df8614c1d399c789fd26aa9888043ebacfccc98ef75a5010a4b8c34be`;
- board checksum-list SHA-256:
  `bde587fa93bffb1c81f1e0042ed4f944bf385d58b1dbeb41b1a6ee0886e94671`;
- board review SHA-256:
  `a76587b03fe866224efaf988cd596559e821c6635906a1a18180783e2495d457`;
- independent current-validator SHA-256:
  `f4198d91c0c3d0244e3a67802e728c33b05980c2677516b0187dc89f3a965e0a`.

The source-archive review packet intentionally remains `REVIEW_REQUIRED` with
`gate3_passed=false`; that is the frozen D017 behavior preventing software from
manufacturing physical clearance. `matrix_20260719/human-review.json` records
the separate reviewed decision. The board packet predates a reporting-only
echo of `initial_sample_ready_timeout_s` in its `capture_contract`; all nine
source-bound summaries and runner metadata record `2.0`, and the independent
current validator reproduces the complete packet with that field present.

Raw JSONL remains on the X5 at
`/home/sunrise/gate3/sensor-matrix-20260718-readybarrier` and is not committed.
The repository contains the checksum list, source-bound board packet,
independent packet, runner metadata, and reduced human review under
`matrix_20260719/`.

Gate 3 passes. This result does not authorize Gate 4, any policy, motor motion,
or grounded operation.
