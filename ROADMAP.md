# Roadmap

Status values distinguish implemented offline work from evidence collected on the robot.

| Phase | Engineering status | Hardware evidence | Advance rule |
| ---: | --- | --- | --- |
| 0. Pi inheritance audit | Complete | Reference snapshot only | Audit and contract reviewed |
| 1. Timing probe | Implemented | `NOT_RUN` | Legacy baseline captured before improvement claim |
| 2. Direct bus | Implemented, mock-tested | `NOT_RUN` | <5 ms bus budget and failure taxonomy verified |
| 3. RT loop | Implemented | `NOT_RUN` | SCHED_FIFO and CPU isolation verified, then p99 gates pass |
| 4. Sensors | Implemented, mock-tested | `NOT_RUN` | Tilt/contact labels and freshness pass |
| 5. Policy host | Implemented, contract-tested | `NOT_RUN` | Golden observation vector and warm-up pass |
| 6. Ops/safety | Implemented, unit-tested | `NOT_RUN` | Crash/watchdog torque-off and pause verified |
| 7. Hardware gates | Runbooks pre-registered | `NOT_RUN` | Each gate separately authorized and passed |

Native servo-transaction escalation remains unstarted. It is allowed only after Phase 3 is measured on hardware with RT setup verified and either tick p99 exceeds 21 ms or p99.9 exceeds 22 ms.
