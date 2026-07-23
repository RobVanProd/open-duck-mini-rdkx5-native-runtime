# NOT RUN — Operations and Safety Hardware Verification

Offline tests cover startup torque-off ordering, crash/signal cleanup, watchdog
trips during both home entry and the control loop, stale-policy-input rejection,
lost-controller shutdown, bounded telemetry, `start_paused` enforcement,
cutoff-first resource cleanup, and terminal torque-off evidence that fails the
summary closed. Gate 2 verified normal startup and final torque-off against the
physical X5, UART, and servo rail, but it did not inject a crash, signal,
watchdog trip, writer failure, stale sensor, or lost-controller fault.

Hardware evidence must measure cutoff behavior and preserve the logged halt
reason without advancing beyond the separately authorized gate. This artifact
remains `NOT_RUN`.
