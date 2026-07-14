# NOT RUN — Operations and Safety Hardware Verification

Offline tests cover startup torque-off ordering, crash/signal cleanup, watchdog
trips, stale-policy-input rejection, lost-controller shutdown, bounded telemetry,
`start_paused` enforcement, cutoff-first resource cleanup, and terminal
torque-off evidence that fails the summary closed. None of those mechanisms has been verified
against the physical X5, serial adapter, controller, or servo power rail.

Hardware evidence must measure cutoff behavior and preserve the logged halt
reason without advancing beyond the separately authorized gate. This artifact
remains `NOT_RUN`.
