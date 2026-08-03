# T251A4 graph-host-only correction

Status: `PREREGISTERED_T251A4_GRAPH_HOST_ONLY_CORRECTION`

T251A3 measured the immutable ONNX call separately from its Python wrapper.
The largest eligible non-ONNX component is the graph host at 0.232 ms median.
The existing stage validates all outputs, and the post-send commit validates
the same outputs again before copying recurrent state.

The correction removes only that redundant pre-send work. The assembler writes
directly into the active graph's already-bound observation buffer. Before a
target can be produced, the current action is still checked for finiteness and
range. After literal successful send, the existing complete equality and
hidden-state checks still run before any recurrent state is committed. The
bound input switches from calibrator to locomotion only after the exact
250-tick handoff.

No observation, target, P30, ONNX, policy, ABI, or production path may change.
The complete fake-fault matrix and a 2,298-tick real-asset byte comparison must
pass locally before one separated semantic-plus-timing X5 screen can be
preregistered. This contract cannot itself earn T251B or Gate 5.
