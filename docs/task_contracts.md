# Task Contracts

This document is the source of truth for the function signatures and data
contracts shared across `scheduler/`, `vision/`, and `motion/`. Since three
people are implementing these modules in parallel, do not change a signature
listed here without syncing with whoever owns the calling side.

All inter-task data is passed via arguments and return values. No task reads
or writes module-level globals to communicate with another task.

## config.py

Every shared constant lives in `config.py` at the repo root. Modules import them
(`from config import ...`) and never hardcode these values. `config.py` imports
nothing from the project, so it can't create a circular import. Values marked
**TODO** are placeholders that must be tuned or calibrated on the robot.

### Type aliases used below

| Alias | Definition | Meaning |
|---|---|---|
| `HSV` | `tuple[int, int, int]` | `(H, S, V)` on OpenCV's scale: H 0–179, S 0–255, V 0–255 |
| `HSVRange` | `tuple[HSV, HSV]` | `(lower, upper)`, both bounds inclusive (`cv2.inRange` semantics) |
| `Position` | `tuple[float, float]` | `(x, y)` in pixels, origin at the top-left, `0 <= x < IMAGE_WIDTH`, `0 <= y < IMAGE_HEIGHT` |

### Constants

| Name | Type | Default | Meaning |
|---|---|---|---|
| `COMMAND_COLORS` | `dict[str, tuple[HSVRange, ...]]` | see file | HSV ranges for each color. A pixel belongs to a color if it falls in **any** of that color's ranges. `"green"` and `"blue"` have one range each. `"red"` has two (H 0–10 and H 170–179) because red hue wraps around 0/180. **TODO: tune under real lighting.** |
| `TRACKED_COLORS` | `tuple[str, ...]` | `("green", "blue", "red")` | `tuple(COMMAND_COLORS)`. Its order is the tie-break order for the dominant color. |
| `MIN_PIXEL_THRESHOLD` | `int` | `500` | A color with a count **below** this is "not detected". **TODO: tune.** |
| `IMAGE_WIDTH` | `int` | `640` | Frame width that `capture_frame()` must return. |
| `IMAGE_HEIGHT` | `int` | `480` | Frame height that `capture_frame()` must return. |
| `IMAGE_CENTER_X` | `int` | `320` | `IMAGE_WIDTH // 2` |
| `IDLE_SENTINEL` | `None` | `None` | What `ColorLocator` returns when idle. Test for it with `is IDLE_SENTINEL`. |
| `CENTER_DEADBAND_PX` | `int` | `40` | A target is "centered" when `abs(x - IMAGE_CENTER_X) <= CENTER_DEADBAND_PX`. **TODO: tune.** |
| `TIMEOUT_SECONDS` | `float` | `20.0` | Safety cutoff for the main loop. |
| `ROTATE_SPEED` | `int` | `50` | Wheel speed for rotations, in motor-library units. **TODO: confirm the range and tune.** |
| `STRAFE_SPEED` | `int` | `50` | Wheel speed for strafing, in motor-library units. **TODO: confirm the range and tune.** |
| `SECONDS_PER_360` | `float` | `4.0` | Time for a full turn at `ROTATE_SPEED`. Rotation is open-loop (no gyro). **TODO: calibrate.** |
| `SECONDS_PER_180` | `float` | `2.0` | Time for a half turn at `ROTATE_SPEED`, calibrated separately because spin-up and spin-down make it more than half of `SECONDS_PER_360`. **TODO: calibrate.** |

**Why `IDLE_SENTINEL` is `None` and not `(-1, -1)`:** `(-1, -1)` has the same
type as a real `Position`. Code that forgets the idle check would steer toward
the left edge without any error. `None` makes the same mistake fail with a
`TypeError` on `p_vector[0]`.

## scheduler/loop.py

### `TimerCheck(start_time: float, timeout_limit: float) -> bool`
- **Inputs:**
  - `start_time: float` — `time.time()` value captured once, before the loop starts.
  - `timeout_limit: float` — max allowed run time, in seconds. `main.py` passes
    `config.TIMEOUT_SECONDS`.
- **Output:** `bool` — `True` if `time.time() - start_time > timeout_limit` (the
  caller must stop the loop), `False` otherwise.
- **Behavior:** Holds no state of its own. It may read `time.time()` to get the
  current time, but `main.py` owns `start_time`.

### `round_robin(tasks: list[Callable[[], None]]) -> None`
- **Inputs:** `tasks` — zero-argument callables, each representing one task's
  single turn.
- **Output:** `None`.
- **Behavior:** Generic reusable primitive: invokes each callable once, in order.
  `main.py`'s specific control flow doesn't need it, but it's available if a
  module needs plain round-robin execution elsewhere.

## vision/color_counter.py

### `ColorCounter(image: numpy.ndarray) -> dict[str, int]`
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

### `ColorLocator(color_counts: dict[str, int]) -> Position | None`
- **Input:** `color_counts` — the output of `ColorCounter`, so every
  `TRACKED_COLORS` key is present.
- **Output:** exactly one of:
  - `config.IDLE_SENTINEL` (`None`), if and only if **every** count is
    `< config.MIN_PIXEL_THRESHOLD`.
  - `Position` (`tuple[float, float]`): the centroid of the dominant color, in
    pixel coordinates (see the `Position` alias above).
- **Color identity:** This function reports *where*, not *which*. The caller
  works out the dominant color using the rule below. When it doesn't return
  idle, the dominant color is guaranteed to meet `MIN_PIXEL_THRESHOLD`.
- **Constraints:** No camera or hardware calls.
- **⚠ OPEN ISSUE (Person B and Person C must resolve this before vision is
  implemented):** pixel counts contain no location, so a centroid **cannot** be
  computed from `color_counts` alone. Possible fixes: pass the frame or the
  color's mask as well, or have `ColorCounter` also return centroids. Either way,
  this signature changes.

### Dominant color

Every caller uses this one rule:

```python
dominant_color = max(TRACKED_COLORS, key=color_counts.__getitem__)
```

The loop goes over `TRACKED_COLORS`, not the dict, so a tie always goes to the
earliest color in `TRACKED_COLORS` order (green, then blue, then red), however
the dict was built.

## motion/actions.py

These action functions are the *only* things `main.py` calls to make the robot
move or idle. They call `motion.mecanum`, never the motor library directly.
**Every action returns `None`.** The four per-loop actions (Idle, Green, Blue,
Red) must **return promptly**, making at most one bounded motion per call, so the
loop gets back to `TimerCheck`.

For the targeted actions, let `error = p_vector[0] - config.IMAGE_CENTER_X`.
A positive error means the target is right of center. If
`abs(error) <= config.CENTER_DEADBAND_PX`, the target is centered and the action
does not move the robot.

### `StartupAction() -> None`
- **Behavior:** Runs once, before the loop starts and before `start_time` is
  captured, so it may block. Owns one-time hardware init (I2C bus, camera
  warm-up) and the startup spin (`mecanum.spin_180(config.ROTATE_SPEED)`).

### `IdleAction() -> None`
- **Behavior:** Called when `ColorLocator` returns `IDLE_SENTINEL`.

### `GreenAction(p_vector: Position) -> None`
- **Behavior:** If the target isn't centered, calls
  `mecanum.rotate_in_place("cw" if error > 0 else "ccw", config.ROTATE_SPEED)`.
  It is never called with `IDLE_SENTINEL`.

### `BlueAction(p_vector: Position) -> None`
- **Behavior:** If the target isn't centered, calls
  `mecanum.strafe("right" if error > 0 else "left", config.STRAFE_SPEED)`.
  It is never called with `IDLE_SENTINEL`.

### `RedAction(p_vector: Position) -> None`
- **Behavior:** Same as `GreenAction`: rotates in place toward the target at
  `config.ROTATE_SPEED`. It is never called with `IDLE_SENTINEL`.

## motion/mecanum.py

Low-level kinematics. Only `motion/actions.py` should import this module, and
only this module calls the Yahboom motor library. There is no gyro, so all
rotation is open-loop and timed with `SECONDS_PER_360` and `SECONDS_PER_180`.
Those timings are only valid at `config.ROTATE_SPEED`.

### `rotate_in_place(direction: str, speed: int) -> None`
- **Inputs:** `direction`: `"cw"` | `"ccw"` (clockwise as seen from above, so
  `"cw"` turns right). `speed`: normally `config.ROTATE_SPEED`.
- **Behavior:** Runs one short, bounded rotation and returns, without blocking
  the loop. Turning through a known angle takes
  `SECONDS_PER_360 * degrees / 360` seconds.

### `strafe(direction: str, speed: int) -> None`
- **Inputs:** `direction`: `"left"` | `"right"`. `speed`: normally
  `config.STRAFE_SPEED`.
- **Behavior:** Runs one short, bounded strafe and returns, without blocking the
  loop.

### `spin_180(speed: int) -> None`
- **Inputs:** `speed`: must be `config.ROTATE_SPEED`.
- **Behavior:** Drives the wheels for `SECONDS_PER_180` seconds, then stops. It
  blocks, which is fine because only `StartupAction` calls it.

## main.py

### `capture_frame() -> numpy.ndarray`
- **Output:** a BGR frame, shape `(IMAGE_HEIGHT, IMAGE_WIDTH, 3)`, `dtype=uint8`.
  If the camera doesn't deliver that size, resize the frame before returning it.
- **Constraints:** The only camera-hardware call in `main.py`. Everything
  downstream (`ColorCounter`, `ColorLocator`) takes the returned array as a
  plain argument and needs no hardware to test.

### `COLOR_ACTIONS: dict[str, Callable[[Position], None]]`
The scheduler maps the dominant color name to an action through this table,
not through an `if`/`elif` chain:

```python
COLOR_ACTIONS = {"green": GreenAction, "blue": BlueAction, "red": RedAction}
```

Its keys must equal `config.TRACKED_COLORS`. `main.py` asserts this at import,
so adding a color to `COMMAND_COLORS` without adding its action fails right away.

### Control flow (`main()`)
1. `StartupAction()` — once.
2. `start_time = time.time()`
3. Loop:
   1. `TimerCheck(start_time, TIMEOUT_SECONDS)`. Break if `True`.
   2. `frame = capture_frame()`
   3. `color_counts = ColorCounter(frame)`
   4. `p_vector = ColorLocator(color_counts)`
   5. If `p_vector is IDLE_SENTINEL`, call `IdleAction()`.
      Otherwise, find `dominant_color` with the rule under
      [Dominant color](#dominant-color), then call
      `COLOR_ACTIONS[dominant_color](p_vector)`.
