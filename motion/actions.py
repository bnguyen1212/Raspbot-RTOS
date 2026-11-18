"""Task-level robot actions dispatched from scheduler.loop.run_loop.

Each action works out what the wheels should do with the pure helpers in
motion.kinematics and motion.centering, then makes the call on a
motion.driver.MotorDriver. Every action takes the driver as an optional
keyword-only argument:

    GreenAction(p_vector)                            # robot: default_driver()
    GreenAction(p_vector, driver=FakeMotorDriver())  # tests

The default is looked up on each call, not when this module is imported, so
importing motion.actions never loads the motor library.

Every action sets the wheels explicitly on every call. The motor board has no
watchdog and keeps running the last command it got, so an action that skipped
its call would leave whatever the previous action sent still running. The
per-loop actions (Idle, Green, Blue and Red) make exactly one driver call
each and return without blocking, so the loop gets back to TimerCheck
promptly. A Green or Blue "step" lasts one loop pass, and the next pass
corrects it or stops.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Final

from config import ROTATE_SPEED, SECONDS_PER_180, SECONDS_PER_360, Position, RedState
from motion.centering import centering_command
from motion.driver import MotorDriver, default_driver, existing_default_driver
from motion.kinematics import RotationDirection, rotate_in_place, strafe

# The direction StartupAction's 360 and RedAction's 180 turn. Both timings in
# config.py (SECONDS_PER_360, SECONDS_PER_180) are for this direction at
# config.ROTATE_SPEED.
TIMED_TURN_DIRECTION: Final[RotationDirection] = "cw"


def _resolve(driver: MotorDriver | None) -> MotorDriver:
    """Return `driver`, or the real default driver when it's None."""
    return default_driver() if driver is None else driver


def start_rotation(
    motors: MotorDriver,
    direction: RotationDirection = TIMED_TURN_DIRECTION,
    speed: float = ROTATE_SPEED,
) -> None:
    """Start rotating in place and return right away. The one rotate-in-place path.

    StartupAction, RedAction and tools/spin_calibration.py all start their
    timed turns here, so a calibration made with the tool applies to the
    actions, as long as it uses the same direction and speed.
    """
    motors.set_wheels(*rotate_in_place(direction, speed))


def timed_spin(
    motors: MotorDriver,
    seconds: float,
    *,
    direction: RotationDirection = TIMED_TURN_DIRECTION,
    speed: float = ROTATE_SPEED,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Rotate in place for `seconds`, then stop. Blocks for the whole spin.

    The stop is in a `finally`, so the wheels stop even if the wait is
    interrupted. StartupAction and tools/spin_calibration.py both use this.
    """
    start_rotation(motors, direction, speed)
    try:
        sleep(seconds)
    finally:
        motors.stop()


def StartupAction(
    *,
    driver: MotorDriver | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """One-time setup before the loop starts, then a 360-degree spin.

    Getting the default driver does the one-time motor hardware init. The spin
    is open-loop: rotate clockwise at config.ROTATE_SPEED for
    config.SECONDS_PER_360, then stop. It blocks, which is fine because it runs
    before the loop and before start_time is taken. The wheels are stopped even
    if the wait is interrupted (for example by Ctrl-C).

    Args:
        driver: MotorDriver to use; None means default_driver().
        sleep: how to wait; tests pass a fake that doesn't really sleep.
    """
    timed_spin(_resolve(driver), SECONDS_PER_360, sleep=sleep)


def IdleAction(*, driver: MotorDriver | None = None) -> None:
    """Hold still: stop the wheels.

    Called when nothing should move the robot (dispatch cases c, d and f). It
    stops the wheels instead of doing nothing. GreenAction and BlueAction
    leave the wheels running between passes, so without this the robot would
    keep moving after the target leaves the frame.

    Args:
        driver: MotorDriver to use; None means default_driver().
    """
    _resolve(driver).stop()


def GreenAction(p_vector: Position, *, driver: MotorDriver | None = None) -> None:
    """Rotate in place toward the green target, or stop once it's centered.

    Uses centering_command(p_vector[0]): "right" rotates clockwise, "left"
    rotates counterclockwise, both at config.ROTATE_SPEED. "centered" stops
    the wheels.

    Args:
        p_vector: Position from ColorLocator. Never None.
        driver: MotorDriver to use; None means default_driver().
    """
    motors = _resolve(driver)
    command = centering_command(p_vector[0])
    if command == "centered":
        motors.stop()
    else:
        motors.set_wheels(*rotate_in_place("cw" if command == "right" else "ccw"))


def BlueAction(p_vector: Position, *, driver: MotorDriver | None = None) -> None:
    """Strafe sideways toward the blue target, or stop once it's centered.

    Uses centering_command(p_vector[0]): "left" or "right" strafes that way at
    config.STRAFE_SPEED. "centered" stops the wheels.

    Args:
        p_vector: Position from ColorLocator. Never None.
        driver: MotorDriver to use; None means default_driver().
    """
    motors = _resolve(driver)
    command = centering_command(p_vector[0])
    if command == "centered":
        motors.stop()
    else:
        motors.set_wheels(*strafe(command))


def RedAction(
    state: RedState, now: float, *, driver: MotorDriver | None = None
) -> RedState:
    """Advance the red-turn sequence (a timed 180-degree turn) by one step.

    Follows the RedAction table in docs/task_contracts.md:

    | Condition                          | Driver call          | Returned state                          |
    |------------------------------------|----------------------|-----------------------------------------|
    | red_start is None (start)          | set_wheels(cw)       | red_start = now; red_rearm unchanged    |
    | now - red_start < SECONDS_PER_180  | set_wheels(cw) again | unchanged                               |
    | otherwise (finished)               | stop()               | red_start = None, red_rearm = False     |

    The turning passes send the clockwise rotation again rather than nothing,
    so every call sets the wheels explicitly. Re-sending the same command
    doesn't change the motion, and it restarts the turn if Raspbot_Lib
    silently dropped the first write.

    `state` itself is never modified. A new dict is returned every time, and
    the caller must rebind: state = RedAction(state, now).

    Args:
        state: RedState, {"red_start": float | None, "red_rearm": bool}.
        now: a fresh time.monotonic() reading.
        driver: MotorDriver to use; None means default_driver().

    Returns:
        RedState: the updated state.
    """
    motors = _resolve(driver)
    red_start = state["red_start"]
    if red_start is None:
        start_rotation(motors)
        return {**state, "red_start": now}
    if now - red_start < SECONDS_PER_180:
        start_rotation(motors)
        return {**state}
    motors.stop()
    return {**state, "red_start": None, "red_rearm": False}


def ShutdownAction(*, driver: MotorDriver | None = None) -> None:
    """Stop the wheels at the end of a run. run_loop calls it as stop_motors.

    With no `driver`, it stops the cached default driver if one has been
    created, and does nothing otherwise. It never creates a driver, so a run
    that failed before touching the motors doesn't open the I2C bus just to
    stop them. Safe to call any number of times.

    Raspbot_Lib swallows I2C errors, so this can't confirm the wheels stopped
    (see motion.mecanum).

    Args:
        driver: MotorDriver to stop; None means the existing default driver,
            if there is one.
    """
    motors = existing_default_driver() if driver is None else driver
    if motors is not None:
        motors.stop()
