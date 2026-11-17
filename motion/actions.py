"""Task-level robot actions dispatched from main.py's round-robin loop.

All hardware access is routed through motion.mecanum -- this module and
mecanum.py together are the only place the real robot is needed to test.

The per-loop actions (Idle, Green, Blue and Red) must return promptly, making
at most one call to the motion layer each, so that main.py's TimerCheck still
gets its turn. None of them block.
"""

from __future__ import annotations

from config import (
    CENTER_DEADBAND_PX,
    IMAGE_CENTER_X,
    ROTATE_SPEED,
    SECONDS_PER_180,
    STRAFE_SPEED,
    Position,
    RedState,
)
from motion import mecanum


def StartupAction() -> None:
    """One-time initialization run before the round-robin loop starts.

    Sets up whatever the robot/motor library needs before any per-cycle action
    can run (e.g. I2C bus init, camera warm-up), then does the startup 360-degree
    spin via mecanum.spin_360(ROTATE_SPEED). It may block, because it runs
    before the timer starts.

    Returns:
        None
    """
    raise NotImplementedError


def IdleAction() -> None:
    """Action taken when there's nothing to act on in the current frame.

    main.py calls this when no tracked color is detected, when red is seen but
    the red turn isn't rearmed yet, and as the fallback for an unrecognized
    color name.

    Returns:
        None
    """
    raise NotImplementedError


def GreenAction(p_vector: Position) -> None:
    """Respond to the green target: rotate in place toward it.

    Let error = p_vector[0] - IMAGE_CENTER_X. If |error| <= CENTER_DEADBAND_PX,
    the target is centered, so don't move. Otherwise call
    mecanum.rotate_in_place("cw" if error > 0 else "ccw", ROTATE_SPEED).

    Args:
        p_vector: Position, the (x, y) pixel position from
            vision.color_locator.ColorLocator. Never None.

    Returns:
        None
    """
    raise NotImplementedError


def BlueAction(p_vector: Position) -> None:
    """Respond to the blue target: strafe sideways toward it.

    Let error = p_vector[0] - IMAGE_CENTER_X. If |error| <= CENTER_DEADBAND_PX,
    the target is centered, so don't move. Otherwise call
    mecanum.strafe("right" if error > 0 else "left", STRAFE_SPEED).

    Args:
        p_vector: Position, the (x, y) pixel position from
            vision.color_locator.ColorLocator. Never None.

    Returns:
        None
    """
    raise NotImplementedError


def RedAction(state: RedState, now: float) -> RedState:
    """Advance the red-turn sequence (a timed 180-degree turn) by one step.

    This is non-blocking: each call makes at most one call to the motion layer
    and returns. main.py calls it once to start a turn, then on every loop pass
    until the turn finishes (see "Red-turn sequence" in
    docs/task_contracts.md).

    1. state["red_start"] is None -> start the turn: call
       mecanum.start_rotation("cw", ROTATE_SPEED) and set red_start = now.
    2. now - red_start < SECONDS_PER_180 -> keep rotating. The motors are
       already running, so make no motion call and leave the state unchanged.
    3. Otherwise the turn is done: call mecanum.stop(), then set
       red_start = None and red_rearm = False.

    `state` itself is never modified. The function returns a new dict, which
    the caller must use: state = RedAction(state, now).

    Args:
        state: RedState, {"red_start": float | None, "red_rearm": bool}.
        now: float, a fresh time.monotonic() reading.

    Returns:
        RedState: the updated state.
    """
    raise NotImplementedError
