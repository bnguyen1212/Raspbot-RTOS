# Task Contracts

This document is the source of truth for the function signatures and data
contracts shared across `scheduler/`, `vision/`, and `motion/`. Since three
people are implementing these modules in parallel, do not change a signature
listed here without syncing with whoever owns the calling side.

All inter-task data is passed via arguments and return values. No task reads
or writes module-level globals to communicate with another task.

Every function signature in the code carries the type hints shown here. Modules
that use `X | Y` in annotations start with `from __future__ import annotations`,
so the hints also work on Python versions older than 3.10.

**All timing uses `time.monotonic()`**, never `time.time()`. The wall clock can
jump (for example on an NTP sync on the Pi), and that would cut the run short
or stretch it. `run_loop` reads every time through its `clock` argument, which
`main()` sets to `time.monotonic`. Tests pass a fake clock instead.

## config.py

Every shared constant lives in `config.py` at the repo root. Modules import them
(`from config import ...`) and never hardcode these values. `config.py` imports
nothing from the project, so it can't create a circular import. Values marked
**TODO** are placeholders that must be tuned or calibrated on the robot.

### Types (defined in `config.py`)

| Name | Definition | Meaning |
|---|---|---|
| `HSV` | `tuple[int, int, int]` | `(H, S, V)` on OpenCV's scale: H 0–179, S 0–255, V 0–255 |
| `HSVRange` | `tuple[HSV, HSV]` | `(lower, upper)`, both bounds inclusive (`cv2.inRange` semantics) |
| `Position` | `tuple[float, float]` | `(x, y)` in pixels, origin at the top-left, `0 <= x < W`, `0 <= y < H` |
| `RedState` | `TypedDict`: `red_start: float \| None`, `red_rearm: bool` | State of the red-turn sequence. A plain `dict` at runtime. See [Red-turn sequence](#red-turn-sequence). |

### Constants

| Name | Type | Default | Meaning |
|---|---|---|---|
| `COMMAND_COLORS` | `dict[str, tuple[HSVRange, ...]]` | see file | HSV ranges for each color. A pixel belongs to a color if it falls in **any** of that color's ranges. `"green"` and `"blue"` have one range each. `"red"` has two (H 0–10 and H 170–179) because red hue wraps around 0/180. **TODO: tune under real lighting.** |
| `TRACKED_COLORS` | `tuple[str, ...]` | `("green", "blue", "red")` | `tuple(COMMAND_COLORS)`. Its order is the tie-break order for the winning color. |
| `MIN_PIXEL_THRESHOLD` | `int` | `500` | A color with a count **below** this is "not detected". **TODO: tune.** |
| `IMAGE_WIDTH` | `int` | `640` | Frame width that `capture_frame()` must return. |
| `IMAGE_HEIGHT` | `int` | `480` | Frame height that `capture_frame()` must return. |
| `IMAGE_CENTER_X` | `int` | `320` | `IMAGE_WIDTH // 2` |
| `CAMERA_INDEX` | `int` | `0` | `cv2.VideoCapture` device index for the USB camera. `main.py --camera` overrides it. **TODO: confirm on the robot.** |
| `IDLE_SENTINEL` | `tuple[None, None]` | `(None, None)` | What `ColorLocator` returns when idle. See [Idle value](#idle-value). |
| `CENTER_DEADBAND_PX` | `int` | `40` | A target is "centered" when `abs(x - IMAGE_CENTER_X) <= CENTER_DEADBAND_PX`. **TODO: tune.** |
| `TIMEOUT_SECONDS` | `float` | `20.0` | Safety cutoff. `TimerCheck` compares `time.monotonic()` readings against it. |
| `ROTATE_SPEED` | `int` | `50` | Wheel speed for rotations and spins, in motor-library units. **TODO: confirm the range and tune.** |
| `STRAFE_SPEED` | `int` | `50` | Wheel speed for strafing, in motor-library units. **TODO: confirm the range and tune.** |
| `SECONDS_PER_360` | `float` | `4.0` | Time for a full turn at `ROTATE_SPEED`; used by `StartupAction`'s spin. Rotation is open-loop (no gyro). **TODO: calibrate.** |
| `SECONDS_PER_180` | `float` | `2.0` | Length of `RedAction`'s turn at `ROTATE_SPEED`. Calibrated separately because spin-up and spin-down make it more than half of `SECONDS_PER_360`. The turn is checked once per loop pass, so it can overshoot by up to one pass. Calibrate it by running the real loop. **TODO: calibrate.** |

### Idle value

`ColorLocator` always returns a 2-tuple, so callers can always unpack it:

```python
winning_color, p_vector = ColorLocator(color_counts, frame)
if winning_color is None:   # idle
    ...
```

- When idle, it returns `config.IDLE_SENTINEL`, which is `(None, None)`. In that
  case `winning_color` and `p_vector` are **both** `None`.
- Check for idle with `winning_color is None`, or with `result == IDLE_SENTINEL`.
  **Never** use `result is IDLE_SENTINEL`: two equal tuples aren't guaranteed to
  be the same object.
- The position is `None`, not a fake value such as `(-1, -1)`. A fake position
  would quietly steer the robot toward the left edge if someone forgot the idle
  check. `None` makes that mistake fail with a `TypeError` on `p_vector[0]`.

## Red-turn sequence

*Decided 2026-11-17. This replaces the earlier blocking `spin_180` in
`RedAction`.*

When red wins, the robot makes a timed 180° turn in place. The turn is
**non-blocking**: it runs across several loop passes, so vision and
`TimerCheck` keep running while the robot turns. Its progress is held in a
`RedState` dict that `main()` creates and passes to `run_loop`.

### State shape

```python
state: RedState = {"red_start": None, "red_rearm": True}   # created once in main()
```

| Key | Type | Meaning |
|---|---|---|
| `red_start` | `float \| None` | The `time.monotonic()` reading when the current turn began. `None` means no turn is running. |
| `red_rearm` | `bool` | `True` means seeing red may start a new turn. It's set to `False` when a turn finishes, and back to `True` by the first later frame whose winning color isn't red. This stops the same red target from triggering turn after turn. |

`RedAction` and the dispatch rule below are the only things that change the
state.

### Dispatch rule (`run_loop`, every loop pass)

Steps 1 and 2 run in this order.

1. **Rearm:** if `winning_color != "red"` (including idle), set
   `state["red_rearm"] = True`.
2. **Dispatch.** Take the first case that matches:

   | # | Condition | Call |
   |---|---|---|
   | a | `state["red_start"] is not None` (a turn is running) | `state = RedAction(state, now)`, whatever vision returned |
   | b | `winning_color == "red"` and `state["red_rearm"]` | `state = RedAction(state, now)`, which starts a new turn |
   | c | `winning_color == "red"` and not rearmed | `IdleAction()` |
   | d | `winning_color is None` (idle) | `IdleAction()` |
   | e | `winning_color` is in `color_actions` (`"green"`, `"blue"`) | `color_actions[winning_color](p_vector)` |
   | f | anything else (unrecognized color) | `IdleAction()` |

- **Why rearm runs first:** if a turn finishes on a pass whose frame isn't red,
  `RedAction`'s `red_rearm = False` overwrites the rearm. A *later* non-red frame
  is then needed before red can trigger again.
- **Case c** keeps the robot still while the red target it just turned away
  from is still in view.
- **Case f** is a defensive fallback and is **intended behavior**. A color name
  with no action means the locator broke its contract. The robot stays still
  and the loop keeps running instead of crashing with a `KeyError`.
- `now` is a fresh `clock()` reading taken at the call (`time.monotonic()` on
  the robot).

## Shutdown

`run_loop` runs `StartupAction` and the whole loop inside `try/finally`.
However the run ends (timeout, Ctrl-C, or an exception from any task,
`StartupAction` included), the `finally` block calls, in this order:

1. `stop_motors()` — the safety-critical step, so it goes first.
2. `release_camera()` — inside a nested `finally`, so the camera is released
   even if stopping the motors raises.

Then the exception, if there was one, propagates. This covers a timeout in the
middle of a red turn: the wheels are stopped before `main()` returns.

**Open item (blocks any run on the robot):** the motion layer doesn't have a
stop action yet. Until it does, `main.py`'s `stop_motors` is a placeholder that
raises `NotImplementedError`, so a real (non-dry) run can't stop the wheels on
exit. The proposed fix is [`ShutdownAction()`](#shutdownaction---none-proposed)
in `motion/actions.py`.

## scheduler/loop.py

This module imports nothing from `vision/` or `motion/`. Every task is passed
in, so the caller decides which implementations run.

### `TimerCheck(start_time: float, now: float, *, timeout: float = config.TIMEOUT_SECONDS) -> bool`
- **Inputs:**
  - `start_time` — the `time.monotonic()` reading taken once, after
    `StartupAction()` and before the loop starts.
  - `now` — a fresh `time.monotonic()` reading for this loop pass.
  - `timeout` — keyword-only, defaults to `config.TIMEOUT_SECONDS`. Only
    `main.py --timeout` overrides it, for short test runs. Calls that pass
    just the two times behave as before.
- **Output:** `True` when `now - start_time > timeout` (the caller must stop
  the loop), `False` otherwise. Reaching the limit exactly is not enough.
- **Behavior:** A pure function. It reads no clock itself and holds no state.

### `round_robin(tasks: list[Callable[[], None]]) -> None`
- **Inputs:** `tasks` — zero-argument callables, each representing one task's
  single turn.
- **Behavior:** Generic reusable primitive: invokes each callable once, in order.
  `run_loop` doesn't use it. `run_loop` passes the red-turn state explicitly,
  which doesn't fit zero-argument tasks.

### `run_loop(state: RedState, *, ...) -> None`

The RASPBOT V2 control flow. It runs until the timeout and returns `None`.
Every argument after `state` is keyword-only:

| Argument | Type | Robot value (`main.py`) |
|---|---|---|
| `state` | `RedState` | `{"red_start": None, "red_rearm": True}` |
| `startup_action` | `Callable[[], None]` | `StartupAction` |
| `capture_frame` | `Callable[[], np.ndarray]` | the frame source's `read` (see [scheduler/camera.py](#schedulercamerapy)) |
| `color_counter` | `Callable[[np.ndarray], dict[str, int]]` | `ColorCounter` |
| `color_locator` | `Callable[[dict[str, int], np.ndarray], tuple[str, Position] \| tuple[None, None]]` | `ColorLocator` |
| `idle_action` | `Callable[[], None]` | `IdleAction` |
| `color_actions` | `Mapping[str, Callable[[Position], None]]` | `{"green": GreenAction, "blue": BlueAction}` |
| `red_action` | `Callable[[RedState, float], RedState]` | `RedAction` |
| `stop_motors` | `Callable[[], None]` | the motion layer's stop action. It must be safe to call when the wheels are already stopped. |
| `release_camera` | `Callable[[], None]` | the frame source's `release`. It must be safe to call more than once. |
| `clock` | `Callable[[], float]` | `time.monotonic` (the default) |
| `timeout` | `float` | `--timeout`, default `config.TIMEOUT_SECONDS` |

**Control flow:**

1. `startup_action()` — once.
2. `start_time = clock()`
3. Loop:
   1. `TimerCheck(start_time, clock(), timeout=timeout)`. Break if `True`.
   2. `frame = capture_frame()`
   3. `color_counts = color_counter(frame)`
   4. `winning_color, p_vector = color_locator(color_counts, frame)`. Vision
      runs on every pass, even mid-turn, because the rearm step needs
      `winning_color`.
   5. Apply the [Dispatch rule](#dispatch-rule-run_loop-every-loop-pass):
      rearm first, then dispatch.
4. Always, however the loop ends: [Shutdown](#shutdown).

## scheduler/camera.py

Frame sources. This is the only place that opens the camera, and it imports
nothing from `vision/` or `motion/`. Both classes have the same interface:

- `read() -> np.ndarray` — a BGR frame, shape `(height, width, 3)`,
  `dtype=uint8`. If the source delivers a different size, it's resized
  before it's returned. `main.py` passes this as `capture_frame`.
- `release() -> None` — frees the source. Safe to call more than once.
  `main.py` passes this as `release_camera`.

The open device is held on the object, which is how `capture_frame` takes no
arguments without needing a global.

### `Camera(index: int, width: int, height: int)`
- A live `cv2.VideoCapture(index)` device: the robot's USB camera, or a laptop
  webcam during `--dry-run`. `main.py` passes `config.CAMERA_INDEX` (or
  `--camera`), `config.IMAGE_WIDTH` and `config.IMAGE_HEIGHT`.
- **Raises** `RuntimeError` if the device can't be opened, and from `read()`
  if the camera returns no frame (for example, it was unplugged).
- **TODO:** camera warm-up is not done yet. It used to belong to
  `StartupAction`. The camera is opened before `StartupAction`'s blocking spin,
  so the first frames the loop reads may be stale ones buffered during the
  spin. Flushing them before `start_time` is taken is still open.

### `StaticImage(path: str, width: int, height: int)`
- One image file, returned as every frame (`--image PATH`). `read()` returns a
  copy, so a task that edits its frame can't change what later passes see.
  `release()` does nothing.
- **Raises** `FileNotFoundError` if the file is missing or isn't a readable
  image.

## scheduler/dry_run.py

### `DryRunMotion(log: Callable[[str], None] = print)`
Stand-ins for the motion actions, used by `--dry-run`. Each one prints what the
robot would do instead of driving the motors, so `motion/` (and the motor
library) is never imported.

| Method | Replaces | Behavior |
|---|---|---|
| `startup_action()` | `StartupAction` | Prints; skips the spin. |
| `idle_action()` | `IdleAction` | Prints. |
| `green_action(p_vector)` | `GreenAction` | Prints `p_vector`. |
| `blue_action(p_vector)` | `BlueAction` | Prints `p_vector`. |
| `red_action(state, now)` | `RedAction` | Follows the [`RedAction`](#redactionstate-redstate-now-float---redstate) table exactly (timing and returned state), without any motion calls. |
| `stop_motors()` | the stop action | Prints. Always printed. |

The other methods print a line only when the action changes, not on every
pass. `log` receives each line; tests pass `list.append` to capture them.

## vision/color_counter.py

### `ColorCounter(image: np.ndarray) -> dict[str, int]`
- **Input:** `image` — a BGR frame, shape `(H, W, 3)`, `dtype=uint8` (as returned
  by `cv2.VideoCapture().read()` or `cv2.imread()`). Don't assume a particular
  size: test images can be any size.
- **Output:** `dict[str, int]`:
  - The keys are **exactly** `config.TRACKED_COLORS` (`"green"`, `"blue"`, `"red"`).
    **All three keys are always present**, even when a count is 0.
  - Each value is an `int >= 0`: the number of pixels that fall in any of the
    color's `config.COMMAND_COLORS` ranges, after converting BGR to HSV.
  - Masks for one color are OR'd together, so a pixel counts at most once per
    color.
- **Constraints:** No camera or hardware calls. Must run correctly given only a
  static image array (see `tests/sample_images/`).

## vision/color_locator.py

### `ColorLocator(color_counts: dict[str, int], image: np.ndarray) -> tuple[str, Position] | tuple[None, None]`
- **Inputs:**
  - `color_counts` — the output of `ColorCounter`, so every `TRACKED_COLORS`
    key is present.
  - `image` — the **same** frame that was passed to `ColorCounter`.
- **Steps:**
  1. **Winning color:** `max(TRACKED_COLORS, key=color_counts.__getitem__)`.
     The loop goes over `TRACKED_COLORS`, not the dict, so a tie always goes to
     the earliest color in `TRACKED_COLORS` order (green, then blue, then red),
     however the dict was built.
  2. If the winner's count is `< config.MIN_PIXEL_THRESHOLD`, return
     `config.IDLE_SENTINEL`, which is `(None, None)`.
  3. Otherwise the locator **recomputes only the winning color's mask** from
     `image`, using `config.COMMAND_COLORS`: convert BGR to HSV, then OR
     together that color's ranges. It doesn't rebuild masks for the other
     colors. It returns the centroid of that mask.
- **Output:** exactly one of:
  - `(winning_color, (x, y))` — `winning_color` is a `str` from
    `TRACKED_COLORS`, and `(x, y)` is a `Position`. Because the winner met the
    threshold, the mask is non-empty.
  - `(None, None)` (`IDLE_SENTINEL`) — no color met the threshold.
- **Constraints:** No camera or hardware calls.

## motion/actions.py

These action functions are the *only* things `main.py` calls to make the robot
move or idle. They drive the wheels only through a
[`MotorDriver`](#motiondriverpy), never the motor library directly, and work
out wheel speeds with the pure helpers in [motion/kinematics.py](#motionkinematicspy)
and [motion/centering.py](#motioncenteringpy).

Every action takes an optional keyword-only `driver: MotorDriver | None = None`.
`None` (what `run_loop` always passes, by not passing it) means
`motion.driver.default_driver()`, which is looked up at call time. So importing
`motion.actions` never imports the motor library. Tests pass a
`FakeMotorDriver`. The positional signatures below are unchanged, so
`run_loop`'s calls are unaffected.

The four per-loop actions (Idle, Green, Blue, Red) **never block**. Each one
makes at most one driver call and returns, so the loop gets back to
`TimerCheck` promptly. A `set_wheels` call leaves the wheels running until the
next call changes them, so one Green or Blue "step" lasts one loop pass.

For Green and Blue, the direction comes from
[`centering_command(p_vector[0])`](#motioncenteringpy).
A target with `abs(p_vector[0] - config.IMAGE_CENTER_X) <= config.CENTER_DEADBAND_PX`
is centered, and the action stops the wheels.

### `StartupAction(*, driver=None, sleep=time.sleep) -> None`
- **Behavior:** Runs once, before the loop starts and before `start_time` is
  taken, so it may block. Getting the default driver is the one-time motor
  hardware init (for example the I2C bus). Then it does the startup 360° spin:
  `set_wheels(*rotate_in_place("cw"))`, `sleep(config.SECONDS_PER_360)`,
  `stop()`. The stop is in a `finally`, so the wheels stop even if the wait is
  interrupted. It does **not** touch the camera. `main.py` opens the camera
  through [scheduler/camera.py](#schedulercamerapy) before this runs.

### `IdleAction(*, driver=None) -> None`
- **Behavior:** Calls `driver.stop()`. Called in dispatch cases c, d and f (see
  [Dispatch rule](#dispatch-rule-run_loop-every-loop-pass)). It stops rather
  than doing nothing because Green and Blue leave the wheels running between
  passes. Without the stop, the robot would keep moving after its target
  left the frame.

### `GreenAction(p_vector: Position, *, driver=None) -> None`
- **Behavior:** `"right"` → `set_wheels(*rotate_in_place("cw"))`, `"left"` →
  `set_wheels(*rotate_in_place("ccw"))`, both at `config.ROTATE_SPEED`.
  `"centered"` → `stop()`. It is never called with `None`.

### `BlueAction(p_vector: Position, *, driver=None) -> None`
- **Behavior:** `"right"` / `"left"` → `set_wheels(*strafe(direction))` at
  `config.STRAFE_SPEED`. `"centered"` → `stop()`. It is never called with
  `None`.

### `RedAction(state: RedState, now: float, *, driver=None) -> RedState`
- **Inputs:** `state` — the current `RedState`. `now` — a fresh
  `time.monotonic()` reading.
- **Output:** the updated `RedState`. **It never modifies `state` itself.** It
  returns a new dict, and the caller must rebind: `state = RedAction(state, now)`.
- **Behavior:** Advances the turn by one step, with at most one driver call:

  | Condition | Driver call | Returned state |
  |---|---|---|
  | `red_start is None` (start) | `set_wheels(*rotate_in_place("cw"))` (at `config.ROTATE_SPEED`) | `red_start = now`; `red_rearm` unchanged |
  | `now - red_start < config.SECONDS_PER_180` (turning) | none (the motors are already running) | unchanged |
  | otherwise (finished) | `stop()` | `red_start = None`, `red_rearm = False` |

### `ShutdownAction() -> None` (proposed)
*Proposed by the scheduler. Not agreed with the motion owner yet.*
- **Behavior:** Stops all four wheels with `driver.stop()`. Safe to call when
  they're already stopped. `main.py` would pass it to `run_loop` as
  `stop_motors`, replacing the placeholder (see [Shutdown](#shutdown)). It must
  exist before `dev` is run on the robot.

## motion/kinematics.py

Pure mecanum kinematics. It imports no hardware library and keeps no state.
There is no gyro, so timed turns are open-loop, and their timings are only
valid at `config.ROTATE_SPEED`.

Chassis frame, seen from above: `vx > 0` drives forward, `vy > 0` strafes
right, `omega > 0` rotates clockwise (turns right). Wheel speeds are
`WheelSpeeds = tuple[float, float, float, float]` in the order
`(front_left, front_right, rear_left, rear_right)`, in motor-library units.

**Wheel polarity:** `SIGN_FRONT_LEFT`, `SIGN_FRONT_RIGHT`, `SIGN_REAR_LEFT` and
`SIGN_REAR_RIGHT` (each `+1` or `-1`) at the top of the file multiply every
speed the module returns. If a wheel turns the wrong way on the robot, flip
its sign there. **TODO: verify each wheel on the robot.**

| Function | Returns |
|---|---|
| `wheel_speeds(vx: float, vy: float, omega: float) -> WheelSpeeds` | `(vx+vy+ω, vx−vy−ω, vx−vy+ω, vx+vy−ω)`, times the signs |
| `rotate_in_place(direction: "cw" \| "ccw", speed: float = ROTATE_SPEED) -> WheelSpeeds` | `wheel_speeds(0, 0, ±speed)`: left wheels one way, right wheels the other |
| `strafe(direction: "left" \| "right", speed: float = STRAFE_SPEED) -> WheelSpeeds` | `wheel_speeds(0, ±speed, 0)`: the two diagonals in opposite directions |

`rotate_in_place` and `strafe` raise `ValueError` for any other direction.

## motion/centering.py

### `centering_command(x: float, image_center_x: float = IMAGE_CENTER_X, deadband: float = CENTER_DEADBAND_PX) -> str`
- **Output:** `"centered"` when `abs(x - image_center_x) <= deadband` (so
  exactly on the edge counts as centered), otherwise `"right"` if
  `x > image_center_x`, else `"left"`.
- **Raises** `ValueError` if `deadband < 0`. Pure: no hardware, no state.

## motion/driver.py

Importing this module never imports the motor library.

### `MotorDriver` (abstract base class)
- `set_wheels(front_left, front_right, rear_left, rear_right) -> None` — start
  each wheel at the given signed speed. The wheels keep turning until the next
  call. Speeds come from `motion.kinematics` with polarity already applied, so
  an implementation passes them through unchanged.
- `stop() -> None` — stop all four wheels. Safe to call when they're already
  stopped.
- Neither method waits.

### `FakeMotorDriver(MotorDriver)`
For tests. `calls` records every call in order, as `("set_wheels", (fl, fr, rl, rr))`
or `("stop", ())`. `wheels` holds the current speeds (all zero at the start and
after `stop()`).

### `default_driver() -> MotorDriver`
The robot's real driver, created on the first call and cached after that, so
the I2C bus is opened once per run. The real driver will be imported inside
this function. **Not written yet:** it raises `NotImplementedError` for now,
so a real (non-dry) run fails in `StartupAction`.

## main.py

`main.py` only wires things up: it picks the task functions and the frame
source and hands them to [`run_loop`](#schedulerlooppy), which
holds the control flow.

### Command line

| Flag | Default | Meaning |
|---|---|---|
| `--dry-run` | off | Use [`DryRunMotion`](#schedulerdry_runpy) instead of `motion/`. It prints actions instead of driving the motors. `motion/` is never imported. |
| `--image PATH` | none | Use this image as every frame ([`StaticImage`](#staticimagepath-str-width-int-height-int)) instead of the live camera. |
| `--camera INDEX` | `config.CAMERA_INDEX` | `cv2.VideoCapture` index for [`Camera`](#cameraindex-int-width-int-height-int). |
| `--timeout SECONDS` | `config.TIMEOUT_SECONDS` | Safety cutoff passed to `run_loop`. It must be greater than 0. |

### `capture_frame`
There is no `capture_frame()` function in `main.py` anymore. `main.py` passes
the frame source's bound `read` method to `run_loop` as `capture_frame`. Its
output contract is the same: a BGR frame, shape
`(IMAGE_HEIGHT, IMAGE_WIDTH, 3)`, `dtype=uint8`. It's the only camera-hardware
call in the loop. Everything downstream (`ColorCounter`, `ColorLocator`)
takes the returned array as a plain argument and needs no hardware to test.

### `color_actions: dict[str, Callable[[Position], None]]`
The table for colors that go straight to an action. It's built for each run
(the real actions, or the `--dry-run` stand-ins), not when `main.py` is
imported:

```python
color_actions = {"green": GreenAction, "blue": BlueAction}
```

Red isn't in the table because it goes through the
[Red-turn sequence](#red-turn-sequence). `build_tasks` asserts, before the
camera is opened, that `set(color_actions) | {"red"} == set(TRACKED_COLORS)`.

### `stop_motors() -> None` (placeholder)
It raises `NotImplementedError` until the motion layer provides
[`ShutdownAction()`](#shutdownaction---none-proposed). See [Shutdown](#shutdown).

### Control flow (`main(argv: list[str] | None = None) -> None`)
1. Parse the command line (`argv`, or `sys.argv[1:]` when `None`).
2. Pick the motion actions (`--dry-run` or real). Then open the frame source.
   Motion is picked first, so a failing motion import can't leave the camera
   open.
3. `state: RedState = {"red_start": None, "red_rearm": True}`
4. `run_loop(state, ...)`. Its [Shutdown](#shutdown) step stops the motors and
   releases the camera on every exit path.
5. On Ctrl-C, exit with code `130`. On timeout, print a message and return.
