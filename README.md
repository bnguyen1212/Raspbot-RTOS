# RASPBOT V2 RTOS Simulation

CE 6308 / CS 6396 / EEDG 6308 — Project 1

A round-robin cooperative task scheduler for the Yahboom RASPBOT V2 (Raspberry Pi,
mecanum wheels, USB camera). This is a scaffold — run instructions, setup steps, and
usage details will be filled in as the implementation lands.

## Status

- **Done:** the scheduler (`scheduler/`) and the `main.py` wiring, including
  `--dry-run` and safe shutdown; the vision layer (`vision/`), with
  placeholder HSV ranges still to be tuned on the robot.
- **Still stubs:** `motion/`.
- **Still needed:** a motion stop action (`ShutdownAction`). Without it, a
  real run can't stop the wheels on exit, so **don't run `main.py` on the
  robot without `--dry-run` until it exists.** See "Shutdown" in the contract.

See [docs/task_contracts.md](docs/task_contracts.md) for the function
signatures each module must implement.

## Project Structure

- `config.py` — every shared constant (HSV color ranges, image size, thresholds,
  timeout, motion speeds and timing). Modules import these from here; nothing
  hardcodes them.
- `scheduler/` — the scheduler side of the project:
  - `loop.py`: the round-robin loop (`run_loop`), the timer/safety cutoff
    (`TimerCheck`) and `round_robin`. It imports nothing from `vision/` or
    `motion/`; every task is passed in.
  - `camera.py`: the frame sources (`Camera` for a live camera, `StaticImage`
    for an image file). This is the only place the camera is opened.
  - `dry_run.py`: stand-in motion actions that print instead of driving the
    motors (`--dry-run`).
- `main.py` — the entry point. It parses the command line, picks the real or
  dry-run actions and the frame source, and hands them to `run_loop`.
- `vision/` — color counting and localization from camera frames (`ColorCounter`,
  `ColorLocator`, and the shared HSV mask helper in `hsv_mask.py`). Pure
  functions over image arrays — no camera or hardware calls.
- `tools/vision_debug.py` — runs the vision pipeline on image files and saves an
  annotated picture (masks, centroid, centering deadband) plus HSV statistics,
  for tuning the color ranges in `config.py`.
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

- Vision code (`vision/`) is tested offline with synthetic frames, plus any
  labeled photos in `tests/sample_images/` (naming rules in
  `tests/sample_images/README.md`) — no robot required. To see what vision
  makes of a photo:
  ```
  python tools/vision_debug.py tests/sample_images/green_center_near.png -o debug_out
  ```
- Motion code (`motion/`) requires the actual robot to verify end-to-end; budget
  hardware time accordingly and coordinate access with the team.
- Scheduler code (`scheduler/`) is tested with fake tasks and a fake clock, so
  no hardware is needed and no test waits for the real timeout.
- Install the dev dependencies first (`pip install -r requirements-dev.txt`;
  this also installs the runtime ones), then run `pytest tests/` from the repo
  root.
- To exercise the whole loop without the robot, use `--dry-run` (see below).

## Local Setup / Running on the Robot

1. Clone the repo:
   ```
   git clone <repo-url>
   cd RaspbotV2-RTOS
   ```
2. Install dependencies:
   - On the Pi (runtime only):
     ```
     pip install -r requirements.txt
     ```
   - On a dev machine (runtime plus pytest):
     ```
     pip install -r requirements-dev.txt
     ```
   (The Yahboom motor/sensor SDK isn't on PyPI — see the note in
   `requirements.txt` and install it per Yahboom's instructions directly on the
   Pi.)
3. On the Pi, pull the branch you need (`dev` for integration testing, `main`
   for a robot-ready run), activate your venv if you use one, and run:
   ```
   python main.py
   ```

### Command-line options

```
python main.py                                    # on the robot
python main.py --dry-run                          # laptop webcam, no motors
python main.py --dry-run --image path/to.png      # static image, no motors
python main.py --dry-run --image path/to.png --timeout 3
```

| Flag | Default | Meaning |
|---|---|---|
| `--dry-run` | off | Print each action instead of driving the motors. `motion/` and the motor library are never imported, so this works on any machine. |
| `--image PATH` | live camera | Use this image as every frame. |
| `--camera INDEX` | `config.CAMERA_INDEX` | Camera device index. |
| `--timeout SECONDS` | `config.TIMEOUT_SECONDS` | Safety cutoff, for shorter test runs. |

The motors stop and the camera is released however the run ends: timeout,
Ctrl-C (exit code 130), or an error. A dry run uses the real vision code.

**TODO:** fill in Pi-specific setup steps still needed — enabling I2C,
camera/USB permissions, and installing the Yahboom motor library on-device.

## Task Ownership

| Person | Subsystem | Covers |
|--------|-----------|--------|
| Person A | `motion/` | Mecanum wheel control, action functions |
| Person B | `vision/` | Color counting, color locating |
| Person C | `scheduler/` | Round-robin loop, timer/safety cutoff, integration (`main.py`) |

Update names above once roles are finalized.
