# Winner-v2 X5 CPU-only preflight preregistration

Status: `LOCKED_PENDING_POLICY_ENVELOPE — NOT_RUN`

This is a no-servo timing gate for the separate stateful 115-D winner-v2 host.
It performs no serial, GPIO, I2C, controller, torque, or motion operation. It is
not automatic configuration and is not Hardware Gate 5.

## Frozen identities

- preflight implementation commit:
  `c6b03ce318f8d427813bef4cc93134f954b102d6`
- deterministic no-prefix source archive SHA-256:
  `782cdf283c7557b11f6267b6c0d110d035bb7b1851700736cb85af25313519df`
- `src/open_duck_x5/winner_v2_cpu_preflight.py` SHA-256:
  `473e4b9ff34e2d6d03350a59d8fc2b19749ffb29cba8023bd7dd8516e3a7f9b6`
- locked launcher: `setup/run_winner_v2_cpu_preflight.sh`
- locked launcher SHA-256 with pending-envelope sentinel:
  `698b747bcd1217c51f0059f8a68a2ee34cc2bca6ea674da9f04af8ecfa96493c`
- `duck_config.json` SHA-256:
  `131a7b8fce1107b14f4727562f44f9e17324caf7fc22512ad7115911f050991b`
- corrected handoff manifest SHA-256:
  `d771d188218152c782c7d688440e2dd2083b47fd9b883749123f89226c6827c5`
- selected 512000-step ONNX SHA-256:
  `99d3afce0dfac127816c6327665c35b3c403e005f25cd0a505dfcb37f01304de`
- preregistered policy-envelope SHA-256:
  `PENDING — LAUNCHER CANNOT RUN`

The source archive is reproducible only as:

```bash
git archive --format=tar.gz \
  c6b03ce318f8d427813bef4cc93134f954b102d6 \
  > source.tar.gz
```

## Frozen population and order

1. Validate the policy-envelope and config identities before loading the ONNX
   or the historical formal verifier.
2. Re-run the complete four-cell, 2,400-tick winner-v2 handoff verifier. Any
   non-pass stops the preflight.
3. Temporarily set policy0 to `performance`; pin the child to isolated CPU 7
   under `SCHED_FIFO` priority 80.
4. Run 10,000 in-memory transactions at x=0 from fresh 600-tick golden
   episodes. A transaction is 115-D assembly, stateful CPU ONNX inference,
   graph-authoritative target checks, P30 staging, and confirmed state commit.
5. Repeat exactly at x=.08. No command, population, CPU, priority, or threshold
   override is exposed by the launcher.
6. Serialize the preallocated timing samples only after measured transactions,
   emit a review-required summary and hashes, and restore the prior governor on
   every exit path.

The selected policy session performs 100 warm-up inferences before each fresh
episode; session construction and warm-up are outside the measured population.
Cyclic GC is disabled only for the measured population and its prior state is
restored on success or failure, matching the runtime hot-loop discipline. No
sleep, disk I/O, bus call, or mock-bus delay is included in a transaction.

## Pre-registered timing gates

Each command must independently satisfy all of:

- population at least 10,000 transactions;
- transaction p99 no greater than 5.0 ms;
- transaction p99.9 no greater than 7.0 ms;
- transaction maximum no greater than 10.0 ms.

The transaction maximum is evaluated over the complete predeclared population,
not a 250-tick sample. These bounds reserve at least 10 ms of the 20 ms control
period for the already measured servo/sensor path, telemetry publication, and
scheduler tail. They do not replace the physical Gate 5 whole-tick gates.

## Stop and authority rules

The launcher contains a non-SHA `PENDING_POLICY_ENVELOPE_SHA256` value and exits
before resolving paths, creating output, changing the governor, loading ONNX,
or executing the formal verifier. After policy publishes a reviewed envelope,
runtime may replace only that value and must freeze the resulting launcher hash
before the X5 CPU-only invocation.

A pass is only `PASS_X5_CPU_ONLY_PREFLIGHT_CANDIDATE` plus independent review.
It grants no robot clearance, Gate 5, runtime deployment, serial access, torque,
or motion. Physical status is `NOT_RUN`.
