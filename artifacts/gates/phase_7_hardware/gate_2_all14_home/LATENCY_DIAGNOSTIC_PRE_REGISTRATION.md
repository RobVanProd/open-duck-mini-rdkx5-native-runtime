# Gate 2 transport-latency diagnostic pre-registration

Status: `READY_BLOCKED_ANALYZER_NOT_CONNECTED`

Rob authorized an instrumented `usbmon` and logic-analyzer all-14 diagnostic
while the robot is suspended/benched, with torque off and no motion. This is a
diagnostic of the already blocked Gate 2 preflight, not authorization for the
home-pose hold or any later gate.

## Frozen run definition

- adapter/driver: WCH `1a86:55d3`, restored Linux `cdc_acm`;
- serial: 1,000,000 bit/s, 4 ms transaction timeout;
- loop: 50 Hz, isolated CPU 7, `SCHED_FIFO 80`;
- ticks: 50;
- commands: one 14-servo goal-position SyncWrite per tick with torque disabled;
- state: one 14-servo position/speed SyncRead per tick, wire order ending
  `14,13`, responses routed into frozen logical order;
- extended telemetry: one servo per tick in frozen logical round-robin order;
- moving flags: absent; torque-enable path: absent;
- final action on all exits: torque off.

## Evidence required for a valid three-layer run

1. ordinary timing JSONL and summary;
2. default-off application transaction trace enabled for this diagnostic;
3. raw `usbmon` capture filtered only during analysis, never at acquisition;
4. logic-analyzer native capture and UART-decode export;
5. analyzer model/software/sample rate/threshold/channel/probe point;
6. repository commit, config hash, kernel, driver, USB topology, RT state, and
   SHA-256 hashes for every recovered artifact.

The round-robin extended-read ID is the cross-capture synchronization marker.
The analyzer must be connected before the serial probe starts. A software-only
capture is useful engineering data but is not mislabeled as this authorized
three-layer run.

## Stop and classification rules

Stop on unexpected motion, any nonzero torque state, wrong wire order, missing
capture layer, missing tick, telemetry drop, bus-failure burst, hard tick
overrun, serial ownership conflict, or operator concern. Torque off and halt on
every stop path.

This diagnostic does not change or waive the Gate 2 thresholds. In particular,
the total-bus maximum remains `<5 ms`; application instrumentation results are
reported separately from the uninstrumented gate result.

At pre-registration time, USB enumeration showed only the X5 hubs and the WCH
serial adapter. No logic analyzer or analyzer CLI was present on the X5, and no
recognized logic analyzer was enumerated on the controlling Windows host.
Therefore no servo transaction was started under this authorization yet.
