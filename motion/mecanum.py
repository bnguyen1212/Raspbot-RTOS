"""Low-level mecanum wheel kinematics.

This is the ONLY module that should call into the Yahboom/RASPBOT motor
library (I2C wheel control). motion.actions builds on these primitives;
vision/ and scheduler/ must never import this module directly.
"""


def rotate_in_place(direction, speed):
    """Rotate the robot chassis in place (used by Green/Red actions).

    Args:
        direction: str, "cw" or "ccw" (clockwise / counter-clockwise).
        speed: int, wheel speed magnitude (implementation-defined units/range,
            e.g. 0-100).

    Returns:
        None
    """
    raise NotImplementedError


def strafe(direction, speed):
    """Move the robot sideways without rotating (used by Blue action).

    Args:
        direction: str, "left" or "right".
        speed: int, wheel speed magnitude (implementation-defined units/range,
            e.g. 0-100).

    Returns:
        None
    """
    raise NotImplementedError


def spin_180(speed):
    """Spin the chassis a half turn in place.

    Args:
        speed: int, wheel speed magnitude (implementation-defined units/range,
            e.g. 0-100).

    Returns:
        None
    """
    raise NotImplementedError
