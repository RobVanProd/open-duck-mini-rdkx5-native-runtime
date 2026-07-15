# Gate 2 transport-latency diagnostic pre-registration

Status: `READY_SOFTWARE_USBMON_ONLY`

Rob authorized an instrumented `usbmon` all-14 diagnostic while the robot is
suspended/benched, with torque off and no motion. He subsequently clarified
that “logic analyzer” meant on-device diagnostic code; no external analyzer or
other physical test equipment exists. This pre-run revision therefore freezes
the capture scope as application timestamps plus Linux `usbmon` only. It is a
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

## Evidence required for a valid software run

1. ordinary timing JSONL and summary;
2. default-off application transaction trace enabled for this diagnostic;
3. raw `usbmon` capture filtered only during analysis, never at acquisition;
4. explicit `capture_scope=software-usbmon` and
   `external_logic_analyzer_present=false` metadata;
5. repository commit, config hash, kernel, driver, USB topology, RT state, and
   SHA-256 hashes for every recovered artifact.

The round-robin extended-read ID synchronizes application events with USB bulk
traffic. The result may attribute application/kernel queuing and bound the
unobserved bridge/wire interval. It must not claim direct physical-wire timing.

## Stop and classification rules

Stop on unexpected motion, any nonzero torque state, wrong wire order, missing
software capture layer, missing tick, telemetry drop, bus-failure burst, hard tick
overrun, serial ownership conflict, or operator concern. Torque off and halt on
every stop path.

This diagnostic does not change or waive the Gate 2 thresholds. In particular,
the total-bus maximum remains `<5 ms`; application instrumentation results are
reported separately from the uninstrumented gate result.

Before this scope clarification, USB enumeration showed only the X5 hubs and
the WCH serial adapter, and no servo transaction was started. This revision is
recorded before the software probe runs.
