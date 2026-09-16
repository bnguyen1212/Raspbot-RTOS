# RASPBOT V2 RTOS Simulation

CE 6308 / CS 6396 / EEDG 6308 — Project 1

A round-robin cooperative task scheduler for the Yahboom RASPBOT V2 (Raspberry Pi,
mecanum wheels, USB camera). This is a scaffold — run instructions, setup steps, and
usage details will be filled in as the implementation lands.

## Status

Structure and interface stubs only. See [docs/task_contracts.md](docs/task_contracts.md)
for the function signatures each module must implement.

## Project Structure

- `scheduler/` — the round-robin loop and timer/safety cutoff logic (`TimerCheck`,
  `round_robin`). No hardware or vision code lives here.
- `vision/` — color counting and localization from camera frames (`ColorCounter`,
  `ColorLocator`). Pure functions over image arrays — no camera or hardware calls.
- `motion/` — robot actions and low-level mecanum wheel control. `motion/actions.py`
  is the only place `main.py` calls into to move the robot; `motion/mecanum.py` is
  the low-level kinematics layer underneath it.
- `tests/` — unit tests, including static sample images (`tests/sample_images/`)
  for offline vision testing.
- `docs/` — task/interface contracts shared across contributors.

**[docs/task_contracts.md](docs/task_contracts.md) is the source of truth** for
every function signature and for what data gets passed between tasks. If your
code doesn't match it, sync with whoever owns the calling side before merging —
don't just change the signature.

## Branching Strategy

- **`main`** — production-ready, submission/robot-ready code only. Only merge
  here after the full integrated system has been tested successfully on the
  actual robot.
- **`dev`** — integration branch. Feature branches merge here first; this is
  where vision, motion, and scheduler code get combined and tested together.
- **`feature/<name>`** — one per subsystem or person (e.g. `feature/vision`,
  `feature/motion`, `feature/scheduler`). Branch off `dev`, not `main`.

## Contribution Workflow

1. Pull latest `dev` and branch off it:
   ```
   git checkout dev && git pull && git checkout -b feature/<name>
   ```
2. Before opening a PR, confirm your functions match the signatures/data types
   in [docs/task_contracts.md](docs/task_contracts.md).
3. Push your branch and open a PR into `dev` (not `main`).
4. After merging to `dev`, whoever has robot access pulls `dev` (not individual
   feature branches) onto the Pi for integration testing.
5. Only after a successful full hardware test — startup spin, color detection,
   correct action dispatch, timeout cutoff all work — does someone merge `dev`
   into `main`.

## Testing

- Vision code (`vision/`) should be testable offline using the static images in
  `tests/sample_images/` — no robot required.
- Motion code (`motion/`) requires the actual robot to verify end-to-end; budget
  hardware time accordingly and coordinate access with the team.
- Run the test suite with `pytest` from the `tests/` directory (or `pytest tests/`
  from the repo root).

## Local Setup / Running on the Robot

1. Clone the repo:
   ```
   git clone <repo-url>
   cd RaspbotV2-RTOS
   ```
2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
   (The Yahboom motor/sensor SDK isn't on PyPI — see the note in
   `requirements.txt` and install it per Yahboom's instructions directly on the
   Pi.)
3. On the Pi, pull the branch you need (`dev` for integration testing, `main`
   for a robot-ready run), activate your venv if you use one, and run:
   ```
   python main.py
   ```

**TODO:** fill in Pi-specific setup steps still needed — enabling I2C,
camera/USB permissions, and installing the Yahboom motor library on-device.

## Task Ownership

| Person | Subsystem | Covers |
|--------|-----------|--------|
| Person A | `motion/` | Mecanum wheel control, action functions |
| Person B | `vision/` | Color counting, color locating |
| Person C | `scheduler/` | Round-robin loop, timer/safety cutoff, integration (`main.py`) |

Update names above once roles are finalized.
