# NOT RUN — Hardware Gate 2: All-14 Home Hold

The moving Gate 2 run has not been performed. An authorized all-14 torque-off
preflight failed the bus gates, so torque was never enabled and home entry never
began. See `PREFLIGHT_BLOCKED.md` and the machine-readable preflight summaries.

A future re-authorized run must verify all 14 IDs, move slowly to the configured
home pose, then hold with SyncWrite, grouped state read, and round-robin extended
telemetry under verified `SCHED_FIFO` and CPU isolation.

Required simultaneously: tick p99 <= 21 ms, tick p99.9 <= 22 ms, zero read
bursts, transaction failure rate < 0.1%, telemetry drops zero, and bus max < 5 ms.
