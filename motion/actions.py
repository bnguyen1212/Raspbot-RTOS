"""Task-level robot actions dispatched from main.py's round-robin loop.

All hardware access is routed through motion.mecanum -- this module and
mecanum.py together are the only place the real robot is needed to test.

Every function here returns None. The per-loop actions (Idle, Green, Blue and
Red) must return promptly, making one bounded motion per call, so that main.py's
TimerCheck still gets its turn. RedAction's 180-degree spin is the longest, at
about SECONDS_PER_180.
"""

from __future__ import annotations

from config import CENTER_DEADBAND_PX, IMAGE_CENTER_X, ROTATE_SPEED, STRAFE_SPEED, Position
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
    """Action taken when no tracked color is detected in the current frame.

    Also called by main.py as the fallback for an unrecognized color name.

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


def RedAction(p_vector: Position) -> None:
    """Respond to the red target: spin 180 degrees in place.

    Calls mecanum.spin_180(ROTATE_SPEED), which blocks for about
    SECONDS_PER_180. p_vector isn't needed for the spin. The parameter is kept
    so all three color actions share one signature for main.COLOR_ACTIONS.

    Args:
        p_vector: Position, the (x, y) pixel position from
            vision.color_locator.ColorLocator. Never None. Unused.

    Returns:
        None
    """
    raise NotImplementedError
