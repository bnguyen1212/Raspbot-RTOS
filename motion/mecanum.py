"""Low-level mecanum wheel kinematics.

This is the ONLY module that should call into the Yahboom/RASPBOT motor
library (I2C wheel control). motion.actions builds on these primitives;
vision/ and scheduler/ must never import this module directly.

There is no gyro, so timed turns are open-loop. spin_360 times itself with
config.SECONDS_PER_360. RedAction times its own 180-degree turn with
config.SECONDS_PER_180, using start_rotation() and stop(). Both timings are
only valid at config.ROTATE_SPEED.
"""

from __future__ import annotations

from config import SECONDS_PER_360


def rotate_in_place(direction: str, speed: int) -> None:
    """Rotate the robot chassis in place briefly (used by GreenAction).

    "cw" means clockwise as seen from above, i.e. turning right. Each call runs
    one short, bounded rotation and returns; it must not block the round-robin
    loop.

    Args:
        direction: str, "cw" or "ccw".
        speed: int, wheel speed magnitude (motor library units),
            normally config.ROTATE_SPEED.

    Returns:
        None
    """
    raise NotImplementedError


def strafe(direction: str, speed: int) -> None:
    """Move the robot sideways without rotating (used by BlueAction).

    Each call runs one short, bounded strafe and returns; it must not block the
    round-robin loop.

    Args:
        direction: str, "left" or "right".
        speed: int, wheel speed magnitude (motor library units),
            normally config.STRAFE_SPEED.

    Returns:
        None
    """
    raise NotImplementedError


def start_rotation(direction: str, speed: int) -> None:
    """Start rotating in place and return right away (used by RedAction).

    This is non-blocking: it sets the wheels turning and returns without
    waiting. The robot keeps rotating until stop() is called. The caller is
    responsible for the timing.

    Args:
        direction: str, "cw" or "ccw" (as in rotate_in_place).
        speed: int, wheel speed magnitude (motor library units). Must be
            config.ROTATE_SPEED when timing a turn with SECONDS_PER_180.

    Returns:
        None
    """
    raise NotImplementedError


def stop() -> None:
    """Stop all four wheels right away (used by RedAction to end its turn).

    Safe to call when the wheels are already stopped.

    Returns:
        None
    """
    raise NotImplementedError


def spin_360(speed: int) -> None:
    """Spin the chassis a full turn in place (open-loop; used by StartupAction).

    Drives the wheels for SECONDS_PER_360 seconds, then stops. It blocks for
    that long, which is fine because it only runs before the loop starts.

    Args:
        speed: int, wheel speed magnitude (motor library units). Must be
            config.ROTATE_SPEED, because SECONDS_PER_360 is calibrated at that
            speed.

    Returns:
        None
    """
    raise NotImplementedError
