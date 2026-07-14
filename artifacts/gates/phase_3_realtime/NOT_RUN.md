# NOT RUN — Real-Time Scheduling Gate

SCHED_FIFO, CPU isolation, IRQ placement, p99, and p99.9 remain unverified on the X5.

The runtime and all-14 probe now partition pre-existing and future background
threads onto housekeeping CPUs before they create ONNX, sensor, controller, or
writer workers. They then verify that only the control thread can execute on the
isolated CPU under `SCHED_FIFO`. No such verification has run on the board, so
this artifact remains `NOT_RUN`.
