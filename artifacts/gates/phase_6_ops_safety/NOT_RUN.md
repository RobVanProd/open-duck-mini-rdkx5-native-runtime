# NOT RUN — Operations and Safety Hardware Verification

Offline tests cover startup torque-off ordering, crash/signal cleanup, watchdog
trips, stale-policy-input rejection, lost-controller shutdown, bounded telemetry,
and `start_paused` enforcement. None of those mechanisms has been verified
against the physical X5, serial adapter, controller, or servo power rail.

Hardware evidence must measure cutoff behavior and preserve the logged halt
reason without advancing beyond the separately authorized gate. This artifact
remains `NOT_RUN`.
