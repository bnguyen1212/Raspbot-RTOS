"""Low-level mecanum wheel kinematics.

This is the ONLY module that should call into the Yahboom/RASPBOT motor
library (I2C wheel control). motion.actions builds on these primitives;
vision/ and scheduler/ must never import this module directly.

There is no gyro, so rotations are open-loop and timed with
config.SECONDS_PER_360 and config.SECONDS_PER_180. Those timings are only valid
at config.ROTATE_SPEED.
"""

from config import SECONDS_PER_180, SECONDS_PER_360


def rotate_in_place(direction, speed):
    """Rotate the robot chassis in place (used by Green/Red actions).

    "cw" means clockwise as seen from above, i.e. turning right. Each call runs
    one short, bounded rotation and returns; it must not block the round-robin
    loop. A turn through a known angle takes
    SECONDS_PER_360 * (degrees / 360) seconds.

    Args:
        direction: str, "cw" or "ccw".
        speed: int, wheel speed magnitude (motor library units),
            normally config.ROTATE_SPEED.

    Returns:
        None
    """
    raise NotImplementedError


def strafe(direction, speed):
    """Move the robot sideways without rotating (used by Blue action).

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


def spin_180(speed):
    """Spin the chassis a half turn in place (open-loop).

    Drives the wheels for SECONDS_PER_180 seconds, then stops. It may block,
    because it's only called from StartupAction, before the loop starts.

    Args:
        speed: int, wheel speed magnitude (motor library units). Must be
            config.ROTATE_SPEED, because SECONDS_PER_180 is calibrated at that
            speed.

    Returns:
        None
    """
    raise NotImplementedError
