from __future__ import annotations

from time import perf_counter_ns

# Monotonic and the highest-resolution process-wide clock available on the host.
# Every runtime timestamp imports this same callable.
clock_ns = perf_counter_ns
