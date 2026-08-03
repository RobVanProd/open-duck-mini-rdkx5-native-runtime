# T251A3 single-host component attribution

Status: `PREREGISTERED_T251A3_X5_SINGLE_HOST_COMPONENT_ATTRIBUTION`

T251A2 proved the optimized host byte-exact for 2,298 ticks but missed its
reserved p99 and p99.9 screen. Its semantic oracle ran a complete baseline host
in the same process and on the same isolated CPU every tick. Alternating call
order changed the optimized mean by only 0.032 ms, but that does not measure
cross-tick instruction/data-cache pressure from the second ONNX session.

T251A3 has two fixed, paced, no-device arms. The first runs only the exact
optimized host for the same 250/0/2,048 chain. The second runs a fresh optimized
host for 250/0/512 ticks and adds component timers around observation assembly,
the ONNX call, graph-host validation, target conversion, observer staging, and
commit. Both action traces must reproduce exact prefixes from T251A2.

This is attribution only. The `1.8/2.5/4.0 ms` limits are reported with zero
selection weight. T251A3 cannot pass T251, earn T251B, change thresholds, alter
production, deploy a policy, or authorize Gate 5. Its only output is which
single host component is eligible for the next measured correction.
