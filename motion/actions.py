"""Task-level robot actions dispatched from scheduler.loop.run_loop.

Each action works out what the wheels should do with the pure helpers in
motion.kinematics and motion.centering, then makes the call on a
motion.driver.MotorDriver. Every action takes the driver as an optional
keyword-only argument:

    GreenAction(p_vector)                            # robot: default_driver()
    GreenAction(p_vector, driver=FakeMotorDriver())  # tests

The default is looked up on each call, not when this module is imported, so
importing motion.actions never loads the motor library.

The per-loop actions (Idle, Green, Blue and Red) never block. Each one makes at
most one driver call and returns, so the loop gets back to TimerCheck promptly.
A driver call leaves the wheels running until the next call changes them. So a
Green or Blue "step" lasts one loop pass, and the next pass corrects it or stops.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from config import SECONDS_PER_180, SECONDS_PER_360, Position, RedState
from motion.centering import centering_command
from motion.driver import MotorDriver, default_driver
from motion.kinematics import rotate_in_place, strafe


def _resolve(driver: MotorDriver | None) -> MotorDriver:
    """Return `driver`, or the real default driver when it's None."""
    return default_driver() if driver is None else driver


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
    motors = _resolve(driver)
    motors.set_wheels(*rotate_in_place("cw"))
    try:
        sleep(SECONDS_PER_360)
    finally:
        motors.stop()


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
    | now - red_start < SECONDS_PER_180  | none                 | unchanged                               |
    | otherwise (finished)               | stop()               | red_start = None, red_rearm = False     |

    `state` itself is never modified. A new dict is returned every time, and
    the caller must rebind: state = RedAction(state, now).

    Args:
        state: RedState, {"red_start": float | None, "red_rearm": bool}.
        now: a fresh time.monotonic() reading.
        driver: MotorDriver to use; None means default_driver(). It's looked
            up only on the passes that make a driver call.

    Returns:
        RedState: the updated state.
    """
    red_start = state["red_start"]
    if red_start is None:
        _resolve(driver).set_wheels(*rotate_in_place("cw"))
        return {**state, "red_start": now}
    if now - red_start < SECONDS_PER_180:
        return {**state}
    _resolve(driver).stop()
    return {**state, "red_start": None, "red_rearm": False}
