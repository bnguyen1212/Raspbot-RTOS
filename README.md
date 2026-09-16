# RASPBOT V2 RTOS Simulation

CE 6308 / CS 6396 / EEDG 6308 — Project 1

A round-robin cooperative task scheduler for the Yahboom RASPBOT V2 (Raspberry Pi,
mecanum wheels, USB camera). This is a scaffold — run instructions, setup steps, and
usage details will be filled in as the implementation lands.

## Status

Structure and interface stubs only. See [docs/task_contracts.md](docs/task_contracts.md)
for the function signatures each module must implement.

## Layout

- `scheduler/` — round-robin loop, timing/safety cutoff logic
- `vision/` — color counting and localization from camera frames (no hardware calls)
- `motion/` — robot actions and low-level mecanum wheel control (all hardware calls live here)
- `tests/` — unit tests, including static sample images for offline vision testing
- `docs/` — task/interface contracts shared across contributors
