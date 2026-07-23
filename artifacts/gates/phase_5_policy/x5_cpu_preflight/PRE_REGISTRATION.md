# Winner-v2 X5 CPU-only preflight preregistration

Status: `LOCKED_PENDING_POLICY_ENVELOPE — NOT_RUN`

This is a no-servo timing gate for the separate stateful 115-D winner-v2 host.
It performs no serial, GPIO, I2C, controller, torque, or motion operation. It is
not automatic configuration and is not Hardware Gate 5.

## Frozen identities

- preflight implementation commit:
  `de870de8cde29a3e645c73c6f6cdeaa48cd8ea46`
- deterministic no-prefix source archive SHA-256:
  `9caefc209dfb85bd1ca28d998e37bcf0832c361468cec0d8d46c97cf6d7c9c17`
- `src/open_duck_x5/winner_v2_cpu_preflight.py` SHA-256:
  `473e4b9ff34e2d6d03350a59d8fc2b19749ffb29cba8023bd7dd8516e3a7f9b6`
- locked launcher: `setup/run_winner_v2_cpu_preflight.sh`
- locked launcher SHA-256 with pending-envelope sentinel:
  `3fb3cffa8bf02481c584482dae1196a5412ec79a17c533d37a55792f6c10483d`
- independent evidence-review implementation commit:
  `daddd4a0a8c7288ce7fa23e979977bbd338f766c`
- `src/open_duck_x5/winner_v2_cpu_preflight_review.py` SHA-256:
  `ebcdad2527d16d9f7a4c2443ace1fd03b5082a196a4ed0806ee2d62065bdba23`
- deterministic Git-provenance/envelope-closure implementation commit:
  `daddd4a0a8c7288ce7fa23e979977bbd338f766c`
- `src/open_duck_x5/policy_envelope_closure.py` SHA-256:
  `39213fb6f4641004cd5545bd6b71f7785035bfb6a5ce4a914c6f6cd1fd09f1a4`
- `src/open_duck_x5/policy_envelope_provenance.py` SHA-256:
  `f0a9daeab37f71a4dbce7fa0e5161afeacc5e8f8bbea3a5354b16077a4518c64`
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
  de870de8cde29a3e645c73c6f6cdeaa48cd8ea46 \
  > source.tar.gz
```

## Frozen population and order

1. Validate the policy-envelope v2, its committed policy-clearance decision,
   and the config identities before loading the ONNX or the historical formal
   verifier.
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
7. Run the frozen independent reviewer outside the immutable evidence
   directory. It must rehash the complete evidence population, rederive all
   20,000 timing samples and gates from JSONL, verify the exact runner/source/
   policy/config identities, and verify governor restoration.

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
before the X5 CPU-only invocation. The no-write closure tool must first accept
the independently supplied envelope SHA-256, unchanged launcher templates, and
the exact frozen selected ONNX. It also re-reads the preregistration and
envelope bytes from their distinct Git commits and verifies preregistration ->
selected-policy -> envelope-artifact ancestry. Any replacement ONNX requires a
new asset freeze rather than a sentinel edit.

A preflight pass candidate is not accepted unless the frozen reviewer emits
`PASS_X5_CPU_PREFLIGHT_EVIDENCE_VALIDATED`. The reviewed result remains marked
`REVIEW_REQUIRED`; neither status is robot clearance.
It grants no robot clearance, Gate 5, runtime deployment, serial access, torque,
or motion. Physical status is `NOT_RUN`.
