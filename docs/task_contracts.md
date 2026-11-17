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
or stretch it.

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
| `IDLE_SENTINEL` | `tuple[None, None]` | `(None, None)` | What `ColorLocator` returns when idle. See [Idle value](#idle-value). |
| `CENTER_DEADBAND_PX` | `int` | `40` | A target is "centered" when `abs(x - IMAGE_CENTER_X) <= CENTER_DEADBAND_PX`. **TODO: tune.** |
| `TIMEOUT_SECONDS` | `float` | `20.0` | Safety cutoff. `TimerCheck` compares `time.monotonic()` readings against it. |
| `ROTATE_SPEED` | `int` | `50` | Wheel speed for rotations and spins, in motor-library units. **TODO: confirm the range and tune.** |
| `STRAFE_SPEED` | `int` | `50` | Wheel speed for strafing, in motor-library units. **TODO: confirm the range and tune.** |
| `SECONDS_PER_360` | `float` | `4.0` | Time for a full turn at `ROTATE_SPEED`; used by `mecanum.spin_360` (startup). Rotation is open-loop (no gyro). **TODO: calibrate.** |
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
`RedState` dict that `main()` owns.

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

### Dispatch rule (`main()`, every loop pass)

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
   | e | `winning_color` is in `COLOR_ACTIONS` (`"green"`, `"blue"`) | `COLOR_ACTIONS[winning_color](p_vector)` |
   | f | anything else (unrecognized color) | `IdleAction()` |

- **Why rearm runs first:** if a turn finishes on a pass whose frame isn't red,
  `RedAction`'s `red_rearm = False` overwrites the rearm. A *later* non-red frame
  is then needed before red can trigger again.
- **Case c** keeps the robot still while the red target it just turned away
  from is still in view.
- **Case f** is a defensive fallback and is **intended behavior**. A color name
  with no action means the locator broke its contract. The robot stays still
  and the loop keeps running instead of crashing with a `KeyError`.
- `now` is a fresh `time.monotonic()` reading taken at the call.

### Known gap: timeout during a turn

If `TimerCheck` stops the loop while a turn is running, nothing calls
`mecanum.stop()`, so the wheels keep turning after `main()` returns. This
contract doesn't fix that yet. One option is to add a `ShutdownAction()` that
`main()` calls after the loop.

## scheduler/loop.py

### `TimerCheck(start_time: float, now: float) -> bool`
- **Inputs:**
  - `start_time` — the `time.monotonic()` reading taken once, after
    `StartupAction()` and before the loop starts.
  - `now` — a fresh `time.monotonic()` reading for this loop pass.
- **Output:** `True` when `now - start_time > config.TIMEOUT_SECONDS` (the
  caller must stop the loop), `False` otherwise.
- **Behavior:** A pure function. It reads no clock itself and holds no state.
  The timeout comes from `config`, not from an argument.

### `round_robin(tasks: list[Callable[[], None]]) -> None`
- **Inputs:** `tasks` — zero-argument callables, each representing one task's
  single turn.
- **Behavior:** Generic reusable primitive: invokes each callable once, in order.
  `main.py`'s control flow doesn't use it. That flow passes the red-turn state
  explicitly, which doesn't fit zero-argument tasks.

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
move or idle. They call `motion.mecanum`, never the motor library directly.
The four per-loop actions (Idle, Green, Blue, Red) **never block**. Each one
makes at most one call to the motion layer and returns, so the loop gets back to
`TimerCheck` promptly.

For Green and Blue, let `error = p_vector[0] - config.IMAGE_CENTER_X`. A positive
error means the target is right of center. If
`abs(error) <= config.CENTER_DEADBAND_PX`, the target is centered and the action
does not move the robot.

### `StartupAction() -> None`
- **Behavior:** Runs once, before the loop starts and before `start_time` is
  taken, so it may block. Owns one-time hardware init (I2C bus, camera
  warm-up), then does the startup 360° spin with
  `mecanum.spin_360(config.ROTATE_SPEED)`.

### `IdleAction() -> None`
- **Behavior:** Doesn't move the robot. Called in dispatch cases c, d and f
  (see [Dispatch rule](#dispatch-rule-main-every-loop-pass)).

### `GreenAction(p_vector: Position) -> None`
- **Behavior:** If the target isn't centered, calls
  `mecanum.rotate_in_place("cw" if error > 0 else "ccw", config.ROTATE_SPEED)`.
  It is never called with `None`.

### `BlueAction(p_vector: Position) -> None`
- **Behavior:** If the target isn't centered, calls
  `mecanum.strafe("right" if error > 0 else "left", config.STRAFE_SPEED)`.
  It is never called with `None`.

### `RedAction(state: RedState, now: float) -> RedState`
- **Inputs:** `state` — the current `RedState`. `now` — a fresh
  `time.monotonic()` reading.
- **Output:** the updated `RedState`. **It never modifies `state` itself.** It
  returns a new dict, and the caller must rebind: `state = RedAction(state, now)`.
- **Behavior:** Advances the turn by one step, with at most one motion call:

  | Condition | Motion call | Returned state |
  |---|---|---|
  | `red_start is None` (start) | `mecanum.start_rotation("cw", config.ROTATE_SPEED)` | `red_start = now`; `red_rearm` unchanged |
  | `now - red_start < config.SECONDS_PER_180` (turning) | none (the motors are already running) | unchanged |
  | otherwise (finished) | `mecanum.stop()` | `red_start = None`, `red_rearm = False` |

## motion/mecanum.py

Low-level kinematics. Only `motion/actions.py` should import this module, and
only this module calls the Yahboom motor library. There is no gyro, so timed
turns are open-loop. Their timings are only valid at `config.ROTATE_SPEED`.

| Function | Used by | Blocks? | Behavior |
|---|---|---|---|
| `rotate_in_place(direction: str, speed: int) -> None` | `GreenAction` | no | `direction`: `"cw"` \| `"ccw"` (clockwise as seen from above, so `"cw"` turns right). Runs one short, bounded rotation and returns. |
| `strafe(direction: str, speed: int) -> None` | `BlueAction` | no | `direction`: `"left"` \| `"right"`. Runs one short, bounded strafe and returns. |
| `start_rotation(direction: str, speed: int) -> None` | `RedAction` | no | Starts the wheels rotating in place and returns right away. They keep turning until `stop()` is called. The caller does the timing. |
| `stop() -> None` | `RedAction` | no | Stops all four wheels. Safe to call when they're already stopped. |
| `spin_360(speed: int) -> None` | `StartupAction` | yes | Drives the wheels for `SECONDS_PER_360`, then stops. Blocking is fine because it runs before the loop. `speed` must be `ROTATE_SPEED`. |

## main.py

### `capture_frame() -> np.ndarray`
- **Output:** a BGR frame, shape `(IMAGE_HEIGHT, IMAGE_WIDTH, 3)`, `dtype=uint8`.
  If the camera doesn't deliver that size, resize the frame before returning it.
- **Constraints:** The only camera-hardware call in `main.py`. Everything
  downstream (`ColorCounter`, `ColorLocator`) takes the returned array as a
  plain argument and needs no hardware to test.

### `COLOR_ACTIONS: dict[str, Callable[[Position], None]]`
The table for colors that go straight to an action:

```python
COLOR_ACTIONS = {"green": GreenAction, "blue": BlueAction}
```

Red isn't in the table because it goes through the
[Red-turn sequence](#red-turn-sequence). `main.py` asserts at import that
`set(COLOR_ACTIONS) | {"red"} == set(TRACKED_COLORS)`.

### Control flow (`main() -> None`)
1. `StartupAction()` — once.
2. `state: RedState = {"red_start": None, "red_rearm": True}`
3. `start_time = time.monotonic()`
4. Loop:
   1. `TimerCheck(start_time, time.monotonic())`. Break if `True`.
   2. `frame = capture_frame()`
   3. `color_counts = ColorCounter(frame)`
   4. `winning_color, p_vector = ColorLocator(color_counts, frame)`. Vision runs
      on every pass, even mid-turn, because the rearm step needs
      `winning_color`.
   5. Apply the [Dispatch rule](#dispatch-rule-main-every-loop-pass): rearm
      first, then dispatch.
