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

## config.py

Every shared constant lives in `config.py` at the repo root. Modules import them
(`from config import ...`) and never hardcode these values. `config.py` imports
nothing from the project, so it can't create a circular import. Values marked
**TODO** are placeholders that must be tuned or calibrated on the robot.

### Type aliases (defined in `config.py`)

| Alias | Definition | Meaning |
|---|---|---|
| `HSV` | `tuple[int, int, int]` | `(H, S, V)` on OpenCV's scale: H 0–179, S 0–255, V 0–255 |
| `HSVRange` | `tuple[HSV, HSV]` | `(lower, upper)`, both bounds inclusive (`cv2.inRange` semantics) |
| `Position` | `tuple[float, float]` | `(x, y)` in pixels, origin at the top-left, `0 <= x < W`, `0 <= y < H` |

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
| `TIMEOUT_SECONDS` | `float` | `20.0` | Safety cutoff for the main loop. |
| `ROTATE_SPEED` | `int` | `50` | Wheel speed for rotations and spins, in motor-library units. **TODO: confirm the range and tune.** |
| `STRAFE_SPEED` | `int` | `50` | Wheel speed for strafing, in motor-library units. **TODO: confirm the range and tune.** |
| `SECONDS_PER_360` | `float` | `4.0` | Time for a full turn at `ROTATE_SPEED`; used by `spin_360`. Rotation is open-loop (no gyro). **TODO: calibrate.** |
| `SECONDS_PER_180` | `float` | `2.0` | Time for a half turn at `ROTATE_SPEED`; used by `spin_180`. Calibrated separately because spin-up and spin-down make it more than half of `SECONDS_PER_360`. **TODO: calibrate.** |

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

## scheduler/loop.py

### `TimerCheck(start_time: float, timeout_limit: float) -> bool`
- **Inputs:**
  - `start_time` — `time.time()` value captured once, before the loop starts.
  - `timeout_limit` — max allowed run time, in seconds. `main.py` passes
    `config.TIMEOUT_SECONDS`.
- **Output:** `True` if `time.time() - start_time > timeout_limit` (the caller
  must stop the loop), `False` otherwise.
- **Behavior:** Holds no state of its own. It may read `time.time()` to get the
  current time, but `main.py` owns `start_time`.

### `round_robin(tasks: list[Callable[[], None]]) -> None`
- **Inputs:** `tasks` — zero-argument callables, each representing one task's
  single turn.
- **Behavior:** Generic reusable primitive: invokes each callable once, in order.
  `main.py`'s specific control flow doesn't need it, but it's available if a
  module needs plain round-robin execution elsewhere.

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
**Every action returns `None`.** The four per-loop actions (Idle, Green, Blue,
Red) must **return promptly**, making one bounded motion per call, so the loop
gets back to `TimerCheck`. The longest is `RedAction`, which blocks for about
`SECONDS_PER_180`. The run can therefore end up to that long after
`TIMEOUT_SECONDS`.

`Green`, `Blue` and `Red` all take `p_vector: Position` so that they share one
signature for `COLOR_ACTIONS`. They are never called with `None`.

For Green and Blue, let `error = p_vector[0] - config.IMAGE_CENTER_X`. A positive
error means the target is right of center. If
`abs(error) <= config.CENTER_DEADBAND_PX`, the target is centered and the action
does not move the robot.

### `StartupAction() -> None`
- **Behavior:** Runs once, before the loop starts and before `start_time` is
  captured, so it may block. Owns one-time hardware init (I2C bus, camera
  warm-up), then does the startup 360° spin with
  `mecanum.spin_360(config.ROTATE_SPEED)`.

### `IdleAction() -> None`
- **Behavior:** Called when `ColorLocator` returns idle, and as `main.py`'s
  fallback for an unrecognized color (see [Control flow](#control-flow-main)).
  Doesn't move the robot.

### `GreenAction(p_vector: Position) -> None`
- **Behavior:** If the target isn't centered, calls
  `mecanum.rotate_in_place("cw" if error > 0 else "ccw", config.ROTATE_SPEED)`.

### `BlueAction(p_vector: Position) -> None`
- **Behavior:** If the target isn't centered, calls
  `mecanum.strafe("right" if error > 0 else "left", config.STRAFE_SPEED)`.

### `RedAction(p_vector: Position) -> None`
- **Behavior:** Spins 180° in place by calling
  `mecanum.spin_180(config.ROTATE_SPEED)`. It doesn't need `p_vector`.

## motion/mecanum.py

Low-level kinematics. Only `motion/actions.py` should import this module, and
only this module calls the Yahboom motor library. There is no gyro, so the
spins are open-loop and timed with `SECONDS_PER_360` and `SECONDS_PER_180`.
Those timings are only valid at `config.ROTATE_SPEED`.

| Function | Used by | Behavior |
|---|---|---|
| `rotate_in_place(direction: str, speed: int) -> None` | `GreenAction` | `direction`: `"cw"` \| `"ccw"` (clockwise as seen from above, so `"cw"` turns right). Runs one short, bounded rotation and returns, without blocking the loop. |
| `strafe(direction: str, speed: int) -> None` | `BlueAction` | `direction`: `"left"` \| `"right"`. Runs one short, bounded strafe and returns, without blocking the loop. |
| `spin_180(speed: int) -> None` | `RedAction` | Drives the wheels for `SECONDS_PER_180`, then stops. Blocks for that long. `speed` must be `ROTATE_SPEED`. |
| `spin_360(speed: int) -> None` | `StartupAction` | Drives the wheels for `SECONDS_PER_360`, then stops. Blocks for that long, which is fine because it runs before the loop. `speed` must be `ROTATE_SPEED`. |

## main.py

### `capture_frame() -> np.ndarray`
- **Output:** a BGR frame, shape `(IMAGE_HEIGHT, IMAGE_WIDTH, 3)`, `dtype=uint8`.
  If the camera doesn't deliver that size, resize the frame before returning it.
- **Constraints:** The only camera-hardware call in `main.py`. Everything
  downstream (`ColorCounter`, `ColorLocator`) takes the returned array as a
  plain argument and needs no hardware to test.

### `COLOR_ACTIONS: dict[str, Callable[[Position], None]]`
The scheduler maps the winning color name to its action through this table:

```python
COLOR_ACTIONS = {"green": GreenAction, "blue": BlueAction, "red": RedAction}
```

Its keys must equal `config.TRACKED_COLORS`. `main.py` asserts this at import,
so adding a color to `COMMAND_COLORS` without adding its action fails right away.

### Control flow (`main() -> None`)
1. `StartupAction()` — once.
2. `start_time = time.time()`
3. Loop:
   1. `TimerCheck(start_time, TIMEOUT_SECONDS)`. Break if `True`.
   2. `frame = capture_frame()`
   3. `color_counts = ColorCounter(frame)`
   4. `winning_color, p_vector = ColorLocator(color_counts, frame)`
   5. Dispatch:
      - `winning_color is None` (idle): call `IdleAction()`.
      - `winning_color in COLOR_ACTIONS`: call
        `COLOR_ACTIONS[winning_color](p_vector)`.
      - **Anything else: call `IdleAction()`.** This defensive fallback is
        **intended behavior**. A color name with no action means the locator
        broke its contract, and in that case the robot stays still and the loop
        keeps running instead of crashing mid-run with a `KeyError`. The
        import-time assert covers the table side; this branch covers the
        locator side.
