# Task Contracts

This document is the source of truth for the function signatures and data
contracts shared across `scheduler/`, `vision/`, and `motion/`. Since three
people are implementing these modules in parallel, do not change a signature
listed here without syncing with whoever owns the calling side.

All inter-task data is passed via arguments and return values. No task reads
or writes module-level globals to communicate with another task.

## scheduler/loop.py

### `TimerCheck(start_time, timeout_limit) -> bool`
- **Inputs:**
  - `start_time: float` — `time.time()` value captured once, before the loop starts.
  - `timeout_limit: float` — max allowed run time, in seconds.
- **Output:** `bool` — `True` if elapsed time has exceeded `timeout_limit` (caller
  must stop the loop), `False` otherwise.
- **Behavior:** Pure function of its two inputs; does not itself call `time.time()`
  internally in a way that hides state — `main.py` owns `start_time`.

### `round_robin(tasks) -> None`
- **Inputs:** `tasks: list[Callable[[], None]]` — zero-argument callables, each
  representing one task's single turn.
- **Output:** `None`.
- **Behavior:** Generic reusable primitive: invokes each callable once, in order.
  Not required by `main.py`'s specific control flow, but available if a module
  needs plain round-robin execution elsewhere.

## vision/color_counter.py

### `ColorCounter(image) -> dict[str, int]`
- **Input:** `image: numpy.ndarray` — a BGR frame, shape `(H, W, 3)`, `dtype=uint8`
  (as returned by `cv2.VideoCapture().read()` or `cv2.imread()`).
- **Output:** `dict[str, int]` — keys are color names from
  `vision.color_counter.TRACKED_COLORS` (`"green"`, `"blue"`, `"red"`), values are
  pixel counts matching that color's threshold range in `image`.
- **Constraints:** No camera or hardware calls. Must run correctly given only a
  static image array (see `tests/sample_images/`).

## vision/color_locator.py

### `ColorLocator(color_counts) -> tuple[float, float] | None`
- **Input:** `color_counts: dict[str, int]` — output of `ColorCounter`.
- **Output:**
  - `tuple[float, float]` — an `(x, y)` position vector locating the dominant
    color in the frame (e.g. normalized offset from image center), **or**
  - `vision.color_locator.IDLE_POSITION` (currently `None`) — the idle sentinel,
    returned when no tracked color meets the detection threshold.
- **Note on color identity:** This function reports *where*, not *which*. The
  caller (`main.py`) determines the dominant color name itself via
  `max(color_counts, key=color_counts.get)` before dispatching to the matching
  action function. Keep this in sync if `ColorLocator`'s contract changes to
  return identity as well.
- **Constraints:** No camera or hardware calls; operates only on the `dict` input.

## motion/actions.py

All action functions are the *only* things `main.py` calls to make the robot
move/idle. They in turn call `motion.mecanum` — never the motor library directly.

### `StartupAction() -> None`
- **Inputs:** None.
- **Output:** `None`.
- **Behavior:** Runs once, before the loop starts. Owns any one-time hardware
  init (I2C bus, camera warm-up, wheel homing, etc.).

### `IdleAction() -> None`
- **Inputs:** None.
- **Output:** `None`.
- **Behavior:** Called when `ColorLocator` returns `IDLE_POSITION`.

### `GreenAction(p_vector) -> None`
- **Input:** `p_vector: tuple[float, float]` — from `ColorLocator`.
- **Output:** `None`.
- **Behavior:** Rotates in place (via `motion.mecanum.rotate_in_place`) toward
  the green target.

### `BlueAction(p_vector) -> None`
- **Input:** `p_vector: tuple[float, float]` — from `ColorLocator`.
- **Output:** `None`.
- **Behavior:** Strafes sideways (via `motion.mecanum.strafe`) toward the blue
  target.

### `RedAction(p_vector) -> None`
- **Input:** `p_vector: tuple[float, float]` — from `ColorLocator`.
- **Output:** `None`.
- **Behavior:** Rotates in place (via `motion.mecanum.rotate_in_place`) toward
  the red target.

## motion/mecanum.py

Low-level kinematics. Only `motion/actions.py` should import this module.

### `rotate_in_place(direction, speed) -> None`
- **Inputs:** `direction: str` (`"cw"` | `"ccw"`), `speed: int`.
- **Output:** `None`.

### `strafe(direction, speed) -> None`
- **Inputs:** `direction: str` (`"left"` | `"right"`), `speed: int`.
- **Output:** `None`.

### `spin_180(speed) -> None`
- **Inputs:** `speed: int`.
- **Output:** `None`.

## main.py

### `capture_frame() -> numpy.ndarray`
- **Inputs:** None.
- **Output:** `numpy.ndarray` — BGR frame, shape `(H, W, 3)`.
- **Constraints:** The only camera-hardware call in `main.py`; everything
  downstream (`ColorCounter`, `ColorLocator`) takes the returned array as a
  plain argument and needs no hardware to test.

### Control flow (`main()`)
1. `StartupAction()` — once.
2. Loop:
   a. `TimerCheck(start_time, TIMEOUT_LIMIT_SECONDS)` — break if `True`.
   b. `frame = capture_frame()`
   c. `color_counts = ColorCounter(frame)`
   d. `p_vector = ColorLocator(color_counts)`
   e. If `p_vector is IDLE_POSITION`: `IdleAction()`.
      Else: determine `dominant_color` from `color_counts`, dispatch to
      `GreenAction(p_vector)` / `BlueAction(p_vector)` / `RedAction(p_vector)`.
