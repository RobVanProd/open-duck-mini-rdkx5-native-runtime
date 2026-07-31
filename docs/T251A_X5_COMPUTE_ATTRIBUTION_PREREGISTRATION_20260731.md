# T251A X5 compute-attribution preregistration

Status: `PREREGISTERED_T251A_X5_COMPUTE_ATTRIBUTION`

T251 completed once and is held only on its three frozen policy-host latency
limits. T251A is not a retry and cannot pass T251. It runs the unchanged T247
assets in a separate X5 directory and partitions the measured cost among exact
ONNX inference, the Python state-coherent host, cyclic GC, and residual CPU-7
kernel work.

The four arms and their order are frozen in the machine-readable contract. Two
clean full-host arms differ only in GC state, one arm measures the exact
locomotion graph floor, and one instrumented arm attributes host component
cost. Every tick is synthetic and commits only in-memory state. The diagnostic
imports and opens no serial, GPIO, I2C, sensor, controller, torque, or motion
path.

The T251 `2/3/5 ms` limits remain unchanged. The result may earn exactly one
evidence-selected implementation correction; it cannot earn production
integration, policy training, Hardware Gate 5, torque, or motion.

Machine-readable contract:
`artifacts/gates/phase_5_policy/t251a_x5_compute_attribution_preregistration_20260731.json`
