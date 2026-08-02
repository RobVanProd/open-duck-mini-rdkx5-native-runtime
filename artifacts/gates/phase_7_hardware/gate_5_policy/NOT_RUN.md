# NOT RUN — Hardware Gate 5: Suspended T247 Policy Replay

Hardware Gate 5 has not run. No T247 policy binary has been copied to the X5
production staging path, no T247 policy has opened the live servo bus, and no
policy-driven torque or motion has occurred.

The prior blockers are now closed:

- T249B offline behavior: 20/20 conditions and 320/320 cells pass.
- Exact command-routed X5 compute: 35/35 checks pass for x=0 and x=.08.
- Opt-in production runtime wiring: 18/18 mock real-asset checks pass.
- Independent T247 control-summary contract: reviewed green.
- Hardware Gates 1-4: `PASS_REVIEWED`.
- Single-arm Gate 5 launcher: preregistered, implemented, and fail-closed.

The current state is `READY_FOR_EXPLICIT_SUSPENDED_T247_GATE5_X0_AUTHORIZATION`.
Readiness is not authorization. The exact next hardware action is one x=0 arm:
250 active calibration ticks followed by 600 active replay ticks. It requires
the robot to be securely supported, the Xbox controller connected, hands clear,
and Rob's explicit authorization for that invocation.

The x=.08 arm cannot run automatically. It requires a separately reviewed green
x=0 receipt, the receipt's exact SHA-256, and separate explicit authorization.
Grounded replay remains prohibited.
