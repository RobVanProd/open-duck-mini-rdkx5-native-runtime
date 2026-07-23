# Automatic configuration pre-registration

Status: `STRUCTURE_FROZEN — BLOCKED_ON_POLICY_ENVELOPE_AND_MOTION_AUTHORIZATION`

This artifact freezes every outcome-independent part of the automatic physical
configuration check. It is not an execution authorization or a runnable gate.
The policy repository must first publish and pass the strict supported-
configuration envelope, and a closure artifact must freeze that exact envelope
SHA-256 before any robot response is observed.

The accepted envelope schema is
`open_duck_x5.supported_configuration_envelope.v2`; it must reference a
committed `open_duck_x5.policy_robot_clearance.v1` decision for the same ONNX.

No scale, caliper, static center-of-mass value, component position, manual
measurement, or policy inference is used.

## Frozen identities

- runtime source commit:
  `de870de8cde29a3e645c73c6f6cdeaa48cd8ea46`
- deterministic no-prefix `git archive --format=tar.gz` SHA-256:
  `9caefc209dfb85bd1ca28d998e37bcf0832c361468cec0d8d46c97cf6d7c9c17`
- source archive size: `503532` bytes
- physical `duck_config.json` SHA-256:
  `131a7b8fce1107b14f4727562f44f9e17324caf7fc22512ad7115911f050991b`
- reviewed BNO055 calibration JSON SHA-256:
  `e7518b0df8614c1d399c789fd26aa9888043ebacfccc98ef75a5010a4b8c34be`
- BNO055 legacy calibration source SHA-256:
  `a3552b357dc2d0e6a876c8e8406134ab36fa6e88a7b7f444c9f9d25122a9da08`
- UART: `/dev/ttyS1`, `1,000,000` baud, `4 ms` transaction timeout
- real-time host: isolated CPU 7, `SCHED_FIFO` priority 80, performance
  governor during the frozen populations, with the prior governor restored on
  every exit path
- policy envelope SHA-256: `PENDING — NO PHYSICAL RUN PERMITTED`
- locked launcher implementation commit:
  `daddd4a0a8c7288ce7fa23e979977bbd338f766c`
- locked launcher path: `setup/run_automatic_configuration.sh`
- locked launcher SHA-256 with the pending-envelope sentinel:
  `34a7ad10d42953e01fa28f786242d2dada74653659125e78b4fe6a493b3f366f`
- final launcher SHA-256 after inserting the reviewed envelope identity:
  `PENDING — NO PHYSICAL RUN PERMITTED`
- deterministic Git-provenance/no-write closure implementation commit:
  `daddd4a0a8c7288ce7fa23e979977bbd338f766c`
- `src/open_duck_x5/policy_envelope_closure.py` SHA-256:
  `39213fb6f4641004cd5545bd6b71f7785035bfb6a5ce4a914c6f6cd1fd09f1a4`
- `src/open_duck_x5/policy_envelope_provenance.py` SHA-256:
  `f0a9daeab37f71a4dbce7fa0e5161afeacc5e8f8bbea3a5354b16077a4518c64`

The source archive can be reproduced only as:

```bash
git archive --format=tar.gz \
  -o open-duck-x5-automatic-configuration-de870de.tar.gz \
  de870de8cde29a3e645c73c6f6cdeaa48cd8ea46
```

## Frozen sequence

The robot must be securely supported or benched, with hands clear. The locked
launcher accepts paths and acknowledgements only; device, baud, CPU,
priority, population, order, amplitude, and thresholds will have no override.
Its pending-envelope sentinel exits before the serial-device check.

1. Validate the already-passed policy envelope, committed clearance decision,
   and their Git provenance, then record the envelope SHA-256 before opening
   `/dev/ttyS1`.
2. Run a fresh 10,000-tick, 50 Hz, torque-off all-14 preflight. No target write,
   torque enable, home entry, or calibration motion is permitted unless its raw
   trace independently passes every preflight threshold below.
3. Move from measured position to the configured physical home over five
   seconds using the existing bounded startup path.
4. Run exactly 2,814 valid ticks: 201 contiguous ticks for each of the 14
   frozen joints in frozen logical order. Only the stage joint departs home.
5. For local stage tick `t`, command exactly
   `0.015*sin(2*pi*t/40) + 0.005*sin(2*pi*t/20)` radians relative to home.
   It starts and ends at home, stays within `0.03 rad`, and remains below
   `0.21 rad/s`.
6. Record all 14 targets and positions, round-robin current, complete-sweep bus
   time, IMU gyro/acceleration, both contacts, and independent monotonic sensor
   timestamps on every tick.
7. Torque off before publishing complete evidence. Automatically build profile
   v4 and validate it against the exact precommitted policy envelope.

No ONNX model is loaded. This is identification/calibration motion only, not a
policy replay and not Gate 5.

## Advancement thresholds

Both the 10,000-tick torque-off preflight and the 2,814-tick calibration must
simultaneously show:

- tick period p99 `<= 21 ms`;
- tick period p99.9 `<= 22 ms`;
- complete-sweep bus maximum `< 5 ms`;
- transaction failure rate `< 0.1%`;
- zero grouped-read bursts, partial replies, unexpected packets, device alarms,
  voltage alarms, stale required samples, evidence gaps, or telemetry drops;
- all 14 required servos, the BNO055, and both contacts present and fresh;
- exact target population/rate/amplitude/order and adequate round-robin current
  coverage; and
- confirmed final torque-off.

The generated 73-metric profile must then lie wholly within the preregistered
policy envelope. There is no measurement waiver and no closest-result pass.

## Stop rules

- A failed or incomplete torque-off preflight blocks all motion.
- A missing/mismatched source, config, calibration, or policy-envelope hash
  blocks serial open or torque enable.
- Any wrong joint/side/sign, unexpected motion, loss of support, operator
  concern, hard overrun, bus failure, stale sensor, device alarm, writer fault,
  signal, or exception halts the run and reaches the torque-off cleanup path.
- A partial trace never becomes final evidence and cannot be evaluated.
- An out-of-envelope profile holds the configuration; it does not modify the
  policy, bounds, robot, or config.

## Remaining freeze and authorization

After the policy envelope arrives, runtime must independently validate it and
commit a closure artifact containing its repository commit, artifact path,
artifact SHA-256, selected ONNX SHA-256, and the final launcher SHA-256 after
the one-value sentinel replacement. The frozen no-write closure tool must first
confirm both pending launcher template hashes, independently supplied envelope
SHA-256, complete envelope schema, exact selected ONNX identity, committed
preregistration and envelope bytes, and preregistration -> selected-policy ->
envelope-artifact ancestry. A changed ONNX blocks closure and requires a new
two-repository asset freeze. Only
then may Rob explicitly authorize this exact supported moving sequence.

Current authority remains: physical collection `NOT_RUN`, robot clearance
false, Gate 5 `NOT_RUN`, runtime deployment false, and grounded motion outside
scope.
