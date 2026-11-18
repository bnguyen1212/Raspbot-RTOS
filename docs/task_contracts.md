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
| `COMMAND_COLORS` | `dict[str, tuple[HSVRange, ...]]` | see file | HSV ranges for each color. A pixel belongs to a color if it falls in **any** of that color's ranges. `"green"` and `"blue"` have one range each. `"red"` has two (H 0–10 and H 170–179) because red hue wraps around 0/180. Red's minimum saturation is 160, higher than the others, so skin isn't counted as red. **TODO: tune under real lighting.** |
| `TRACKED_COLORS` | `tuple[str, ...]` | `("green", "blue", "red")` | `tuple(COMMAND_COLORS)`. Its order is the tie-break order for the winning color. |
| `MASK_OPEN_KERNEL_PX` | `int` | `3` | Noise removal: each color's mask gets a morphological opening with a square kernel this many pixels wide before it is counted or located, which drops specks smaller than the kernel. Must be odd (an even kernel shifts the mask by a pixel); `1` (or `0`) turns it off. **TODO: tune.** |
| `MIN_PIXEL_THRESHOLD` | `int` | `1500` | A color with a count **below** this is "not detected". **TODO: tune.** |
| `IMAGE_WIDTH` | `int` | `640` | Frame width that `capture_frame()` must return. |
| `IMAGE_HEIGHT` | `int` | `480` | Frame height that `capture_frame()` must return. |
| `IMAGE_CENTER_X` | `int` | `320` | `IMAGE_WIDTH // 2` |
| `CAMERA_INDEX` | `int` | `0` | `cv2.VideoCapture` device index for the USB camera. `main.py --camera` overrides it. **TODO: confirm on the robot.** |
| `IDLE_SENTINEL` | `tuple[None, None]` | `(None, None)` | What `ColorLocator` returns when idle. See [Idle value](#idle-value). |
| `CENTER_DEADBAND_PX` | `int` | `40` | A target is "centered" when `abs(x - IMAGE_CENTER_X) <= CENTER_DEADBAND_PX`. **TODO: tune.** |
| `TIMEOUT_SECONDS` | `float` | `20.0` | Safety cutoff. `TimerCheck` compares `time.monotonic()` readings against it. |
| `MAX_SPEED` | `float` | `0.4` | Safety cap on every wheel speed, normalized (1.0 = full speed = the library's 255). `motion.mecanum` clamps every wheel to ±`MAX_SPEED` before sending. `config.py` asserts `0 < MAX_SPEED <= 1.0`. **TODO: raise only after testing at this cap.** |
| `ROTATE_SPEED` | `float` | `0.2` | Wheel speed for rotations and spins, normalized. `config.py` asserts `0 < ROTATE_SPEED <= MAX_SPEED`. **TODO: tune.** |
| `STRAFE_SPEED` | `float` | `0.2` | Wheel speed for strafing, normalized. `config.py` asserts `0 < STRAFE_SPEED <= MAX_SPEED`. **TODO: tune.** |
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

In a real run, `stop_motors` is
[`motion.actions.ShutdownAction`](#shutdownaction-drivernone---none). In a
`--dry-run` it's `DryRunMotion.stop_motors`.

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
| `stop_motors` | `Callable[[], None]` | `ShutdownAction`. It must be safe to call when the wheels are already stopped. |
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
  - Each color's mask is then opened with a `config.MASK_OPEN_KERNEL_PX`
    square kernel to remove speckle noise, and the remaining pixels are
    counted.
- **Shared helper:** the BGR-to-HSV conversion, the thresholding and the
  opening live in `vision/hsv_mask.py` (`to_hsv`, `color_mask`,
  `mask_centroid`). `ColorCounter` and `ColorLocator` both use it, so they
  always agree on which pixels match a color.
- **Raises** `TypeError`/`ValueError` if `image` isn't a non-empty
  `(H, W, 3)` `uint8` array. (A float image would otherwise be converted on a
  0–360 hue scale and silently match the wrong pixels.)
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
     together that color's ranges, then open it, exactly as `ColorCounter`
     does (same helper). It doesn't rebuild masks for the other colors. It
     returns the centroid of that mask: the mean `(x, y)` of its pixels.
- **Output:** exactly one of:
  - `(winning_color, (x, y))` — `winning_color` is a `str` from
    `TRACKED_COLORS`, and `(x, y)` is a `Position` made of plain `float`s.
    Because the winner met the threshold, the mask is non-empty.
  - `(None, None)` (`IDLE_SENTINEL`) — no color met the threshold. It's also
    returned, defensively, if `color_counts` didn't come from `image` and the
    winner's mask turns out empty, so a mismatch never yields a made-up
    position.
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

### Rule: every call sets the wheels explicitly

Raspbot_Lib has no watchdog, and the motor board most likely keeps running the
last command it received until it gets another. So **every action function
must set the wheels explicitly on every call**, with `set_wheels(...)` or
`stop()`. It must never rely on "the wheels are already doing the right thing"
or on the motors stopping by themselves. In particular:

- `IdleAction` stops the wheels.
- `GreenAction` and `BlueAction` stop the wheels when the target is centered.
- `RedAction` sends the rotation again on every turning pass.

The four per-loop actions (Idle, Green, Blue, Red) make **exactly one** driver
call each and **never block**, so the loop gets back to `TimerCheck` promptly.
A real `stop()` pauses for a few milliseconds between its two writes (see
[motion/mecanum.py](#motionmecanumpy)). One Green or Blue "step" lasts one
loop pass, until the next pass's call replaces it.

`tests/test_actions.py` checks this rule for every action: each case starts
with the wheels left running by something else, and the action's own call
must decide what the wheels do.

For Green and Blue, the direction comes from
[`centering_command(p_vector[0])`](#motioncenteringpy).
A target with `abs(p_vector[0] - config.IMAGE_CENTER_X) <= config.CENTER_DEADBAND_PX`
is centered.

### Shared rotation helpers
Every timed turn goes through these two helpers, so a calibration made with
[tools/spin_calibration.py](#toolsspin_calibrationpy) applies to the actions.

- `TIMED_TURN_DIRECTION = "cw"` — the direction of `StartupAction`'s 360 and
  `RedAction`'s 180. `SECONDS_PER_360` and `SECONDS_PER_180` are calibrated
  for this direction at `config.ROTATE_SPEED`.
- `start_rotation(motors, direction=TIMED_TURN_DIRECTION, speed=ROTATE_SPEED) -> None`
  — `motors.set_wheels(*rotate_in_place(direction, speed))`. Doesn't block.
- `timed_spin(motors, seconds, *, direction=TIMED_TURN_DIRECTION, speed=ROTATE_SPEED, sleep=time.sleep) -> None`
  — `start_rotation`, `sleep(seconds)`, then `stop()` in a `finally`.
  Blocks for the whole spin.

### `StartupAction(*, driver=None, sleep=time.sleep) -> None`
- **Behavior:** Runs once, before the loop starts and before `start_time` is
  taken, so it may block. Getting the default driver is the one-time motor
  hardware init (it opens the I2C bus). Then it does the startup 360° spin:
  `timed_spin(motors, config.SECONDS_PER_360)`. That is a clockwise rotation
  at `ROTATE_SPEED`, then `stop()` in a `finally`, so the wheels stop even if
  the wait is interrupted. It does **not** touch the camera. `main.py` opens the camera
  through [scheduler/camera.py](#schedulercamerapy) before this runs.

### `IdleAction(*, driver=None) -> None`
- **Behavior:** Calls `stop()`. Called in dispatch cases c, d and f (see
  [Dispatch rule](#dispatch-rule-run_loop-every-loop-pass)).

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
- **Behavior:** Advances the turn by one step, with exactly one driver call:

  | Condition | Driver call | Returned state |
  |---|---|---|
  | `red_start is None` (start) | `set_wheels(*rotate_in_place("cw"))` (at `config.ROTATE_SPEED`) | `red_start = now`; `red_rearm` unchanged |
  | `now - red_start < config.SECONDS_PER_180` (turning) | the same `set_wheels(*rotate_in_place("cw"))` again | unchanged |
  | otherwise (finished) | `stop()` | `red_start = None`, `red_rearm = False` |

  The state transitions are the same as before. Only the turning row's driver
  call changed: it used to be "none", and it now follows the
  [every-call rule](#rule-every-call-sets-the-wheels-explicitly). Re-sending
  the same rotation doesn't change the motion, and it restarts the turn if
  the library silently dropped the first write.

### `ShutdownAction(*, driver=None) -> None`
- **The function `run_loop` calls in its `finally` block**, as `stop_motors`
  (see [Shutdown](#shutdown)). `main.py` passes it in a real run. It replaces
  the old `stop_motors` placeholder in `main.py`, which raised
  `NotImplementedError`.
- **Behavior:** With no `driver`, it calls `stop()` on the cached default
  driver if one has been created
  ([`existing_default_driver()`](#existing_default_driver---motordriver--none)),
  and does nothing otherwise. It never creates a driver, so a run that failed
  before touching the motors doesn't open the I2C bus just to stop them.
  Safe to call any number of times.
- **Limits:** the library swallows I2C errors, so `ShutdownAction` can't
  confirm the wheels stopped. If no driver exists, it does nothing, even if an
  earlier process left the wheels running. Use
  [tools/emergency_stop.py](#toolsemergency_stoppy) for that.

## motion/kinematics.py

Pure mecanum kinematics. It imports no hardware library, keeps no state and
has **no hardware tunables**: motor IDs and wiring inversions live in
[motion/mecanum.py](#motionmecanumpy). The sign patterns here are logical:
`+` means that wheel drives the robot forward. There is no gyro, so timed turns
are open-loop, and their timings are only valid at `config.ROTATE_SPEED`.

Chassis frame, seen from above: `vx > 0` drives forward, `vy > 0` strafes
right, `omega > 0` rotates clockwise (turns right). Wheel speeds are
`WheelSpeeds = tuple[float, float, float, float]` in the order
`(front_left, front_right, rear_left, rear_right)`. They are normalized
(1.0 = full speed forward) and not clamped here.

| Function | Returns |
|---|---|
| `wheel_speeds(vx: float, vy: float, omega: float) -> WheelSpeeds` | `(vx+vy+ω, vx−vy−ω, vx−vy+ω, vx+vy−ω)` |
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
  each wheel at the given normalized, signed speed, in logical wheel
  directions from `motion.kinematics`. The wheels keep turning until the next
  call. The implementation maps wheels to motor IDs, applies inversions and
  clamps to `config.MAX_SPEED`.
- `stop() -> None` — stop all four wheels. Safe to call when they're already
  stopped.
- Neither method waits for the wheels to change speed. A real `stop()` pauses
  for a few milliseconds.
- **Context manager (defined on the base class, so every driver has it):**
  `with driver:` calls `stop()` however the block ends (normally, by an
  exception or by `KeyboardInterrupt`), then lets the exception propagate. It
  can be entered any number of times. It only covers exceptions that reach
  Python, not one the library swallowed.

### `FakeMotorDriver(MotorDriver)`
For tests. `calls` records every call in order, as `("set_wheels", (fl, fr, rl, rr))`
or `("stop", ())`. `wheels` holds the current speeds (all zero at the start and
after `stop()`).

### `default_driver() -> MotorDriver`
The robot's real driver,
[`motion.mecanum.RaspbotMotorDriver()`](#motionmecanumpy).
It's created on the first call and cached after that, so there's one
`Raspbot` and one open I2C bus per run. `motion.mecanum` is imported inside
this function. It raises `ImportError` where Raspbot_Lib isn't installed (use
`--dry-run` there). If creating the driver raises, nothing is cached.

### `existing_default_driver() -> MotorDriver | None`
The cached default driver if `default_driver()` has already created one, else
`None`. It never creates a driver.

## motion/mecanum.py

The real `MotorDriver`, and the **only** file that imports Raspbot_Lib
(`from Raspbot_Lib import Raspbot`, inside the constructor). Importing the
module doesn't need the library. **Nothing in it has been run on the robot.**

### What Raspbot_Lib (0.0.2) does, from its source
- `Raspbot()` opens I2C bus 1, address `0x2B`, as soon as it's constructed,
  and never closes it.
- `Ctrl_Muto(motor_id, speed)` takes a signed speed in −255…255 and does no
  type conversion. It's the only library method this project uses.
  `LightShow` is not used.
- Every I/O method wraps its I2C write in a bare `except:` that just prints a
  message. **I2C errors never reach our code, so a failed write, including a
  failed stop, can't be detected.** The bare `except:` also catches
  `KeyboardInterrupt`, so a Ctrl-C that arrives during a write is swallowed.
- There's no stop method and no watchdog (hence the
  [every-call rule](#rule-every-call-sets-the-wheels-explicitly)).

### Wiring block: VERIFY ON ROBOT
One labeled constants block at the top of the file holds, for each wheel, a
`Wheel(motor_id, inverted)`. The defaults are guesses from the library's
commented motor test (`0 = "L1"`, `1 = "L2"`, `2 = "R1"`, `3 = "R2"`):

| Wheel | Motor ID | Inverted | Library label |
|---|---|---|---|
| `FRONT_LEFT` | 0 | `False` | L1 |
| `REAR_LEFT` | 1 | `False` | L2 |
| `FRONT_RIGHT` | 2 | `False` | R1 |
| `REAR_RIGHT` | 3 | `False` | R2 |

The library doesn't say whether "1" is front or rear, or which way "forward"
spins each wheel. **None of this is verified.**

### `to_library_speed(speed: float, max_speed: float = MAX_SPEED) -> int`
Clamps to ±`max_speed`, scales so 1.0 is 255, rounds, and returns an `int`.
It never returns a float. It raises `ValueError` for NaN.

### `RaspbotMotorDriver(max_speed: float = MAX_SPEED, *, board=None, sleep=time.sleep)`
- **Constructor:** checks that `max_speed` is in (0, 1.0] and that the
  wiring block maps the four wheels to motor IDs 0–3 once each (`ValueError`
  otherwise), before opening the bus. Then it creates one `Raspbot` (unless a
  `board` is passed, as tests do) and reuses it for every call.
- **`set_wheels(fl, fr, rl, rr)`:** for each wheel, applies `inverted`, then
  `to_library_speed`, then makes one `Ctrl_Muto(motor_id, int)` call. All
  four values are converted before anything is sent, so a NaN sends nothing.
- **`stop()`:** writes 0 to all four motors, waits `STOP_REPEAT_GAP_S`
  (5 ms), and writes 0 to all four again. The second pass guards against one
  dropped write. It doesn't confirm anything, because the library hides
  failures.
- **`set_motor_raw(motor_id, speed)` (diagnostic):** drives one motor by its
  library ID, **bypassing the wiring block**: no mapping and no inversion, so
  a positive speed is the library's own "forward". It still clamps to
  `max_speed` and sends an int, and it raises `ValueError` for an ID other
  than 0–3. Only `tools/motion_test.py` uses it, to work out the wiring. The
  rest of the project uses `set_wheels`.
- **Context manager:** inherited from [`MotorDriver`](#motordriver-abstract-base-class):
  `with RaspbotMotorDriver() as driver:` stops the wheels however the block
  ends.

## tools/emergency_stop.py

A standalone script for the robot: `python3 tools/emergency_stop.py`. It
imports only Raspbot_Lib and the standard library, nothing from this
repository, so it works even when the project code is broken. It creates a
`Raspbot`, writes `Ctrl_Muto(id, 0)` to motors 0–3, does that twice, and
prints each call. It can't confirm the wheels stopped (the library hides I2C
errors), so it tells you to look for `I2C error` lines and to check the
robot. **Not run on the robot yet.**

## tools/motion_test.py

An interactive menu for testing the motors over SSH, one movement at a time.
See the README for how to use it. It uses `motion.mecanum.RaspbotMotorDriver`
and the `motion.kinematics` helpers. With `--dry-run` it uses a printing
`FakeMotorDriver` subclass. **Not run on the robot yet.**

- Every movement runs inside `with driver:`, so it ends with `stop()` however
  it ends. Nothing moves until the user presses Enter on a description of the
  movement.
- Speeds are `ROTATE_SPEED` / `STRAFE_SPEED` (forward, backward and single
  wheel use the lower of the two). The script refuses anything above
  `MAX_SPEED`.
- **Signals:** uses [`motion.stop_on_signal`](#motionstop_on_signalpy).

## tools/spin_calibration.py

`python3 tools/spin_calibration.py <seconds> [--direction left|right] [--speed X] [--repeat N] [--dry-run]`.
See the README for how to use it. **Not run on the robot yet.**

- It rotates with [`timed_spin`](#shared-rotation-helpers) on
  `default_driver()`, the same helper, wheel pattern and driver the actions
  use. Only the duration, direction and speed come from the command line.
- Defaults: direction `left`, speed `config.ROTATE_SPEED`. Speeds above
  `MAX_SPEED` (or ≤ 0) are rejected, and so are durations over 30 s. It warns
  when the direction isn't `TIMED_TURN_DIRECTION` (`right`) or the speed isn't
  `ROTATE_SPEED`, because then the results don't apply to the actions as
  configured.
- Each trial waits for Enter, spins inside `with driver:`, pauses 1 s to
  settle, prints the requested and measured time, direction and speed, and asks
  for a note. `--repeat N` runs N trials, and it prints a CSV log at the end.
  `--dry-run` uses a printing `FakeMotorDriver`.
- **Signals:** uses [`motion.stop_on_signal`](#motionstop_on_signalpy).

## motion/stop_on_signal.py

### `install_stop_handlers(driver, write=print) -> None`
For the scripts in `tools/`. On SIGINT, SIGTERM or SIGHUP (SIGHUP only where
the OS has it), the handler:

1. ignores further stop signals,
2. calls `driver.stop()`,
3. prints a message (it says so if `stop()` raised), and
4. leaves with `os._exit(128 + signum)`.

It never raises. Python runs signal handlers between bytecodes, which may be
inside Raspbot_Lib's bare `except:`, and an exception raised there would be
swallowed. `os._exit` can't be caught. SIGKILL can't be handled. Use
[tools/emergency_stop.py](#toolsemergency_stoppy).

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

### Control flow (`main(argv: list[str] | None = None) -> None`)
1. Parse the command line (`argv`, or `sys.argv[1:]` when `None`).
2. Pick the motion actions (`--dry-run` or real). Then open the frame source.
   Motion is picked first, so a failing motion import can't leave the camera
   open.
3. `state: RedState = {"red_start": None, "red_rearm": True}`
4. `run_loop(state, ...)`. Its [Shutdown](#shutdown) step stops the motors and
   releases the camera on every exit path.
5. On Ctrl-C, exit with code `130`. On timeout, print a message and return.
