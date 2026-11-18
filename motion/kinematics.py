"""Mecanum wheel kinematics: chassis motion in, four wheel speeds out.

Pure functions only. This module imports no hardware library and keeps no
state, so everything here can be tested on any machine. motion.actions turns
these tuples into motor commands through a motion.driver.MotorDriver.

Chassis frame (robot-centric, seen from above):
    vx     > 0  drives forward
    vy     > 0  strafes right
    omega  > 0  rotates clockwise (turns right)

These match the direction words the rest of the project uses ("cw", "right"),
so a target right of center maps to a positive command.

Wheel speeds are in the motor library's units (see config.ROTATE_SPEED). They
are not normalized: callers pass speeds that are already in range.
"""

from __future__ import annotations

from typing import Final, Literal

from config import ROTATE_SPEED, STRAFE_SPEED

# ---------------------------------------------------------------------------
# Wheel polarity
# ---------------------------------------------------------------------------
# +1 means a positive speed drives that wheel forward. If a wheel turns out to
# be wired or mounted backwards on the real robot, set its sign to -1 here.
# That is the only change needed: every speed this module returns goes through
# these signs.
#
# TODO: verify each wheel on the robot (drive forward slowly and watch it).
SIGN_FRONT_LEFT: Final[int] = 1
SIGN_FRONT_RIGHT: Final[int] = 1
SIGN_REAR_LEFT: Final[int] = 1
SIGN_REAR_RIGHT: Final[int] = 1

# (front_left, front_right, rear_left, rear_right)
WheelSpeeds = tuple[float, float, float, float]

RotationDirection = Literal["cw", "ccw"]
StrafeDirection = Literal["left", "right"]


def wheel_speeds(vx: float, vy: float, omega: float) -> WheelSpeeds:
    """Convert a chassis velocity into the four wheel speeds.

    Standard inverse kinematics for mecanum wheels in the usual "X" roller
    layout, with the geometry factor folded into `omega`'s units:

        front_left  = vx + vy + omega
        front_right = vx - vy - omega
        rear_left   = vx - vy + omega
        rear_right  = vx + vy - omega

    Each result is then multiplied by that wheel's SIGN_* constant.

    Args:
        vx: forward speed (negative is backward).
        vy: rightward strafe speed (negative is leftward).
        omega: clockwise rotation speed (negative is counterclockwise).

    Returns:
        WheelSpeeds: (front_left, front_right, rear_left, rear_right).
    """
    return (
        SIGN_FRONT_LEFT * (vx + vy + omega),
        SIGN_FRONT_RIGHT * (vx - vy - omega),
        SIGN_REAR_LEFT * (vx - vy + omega),
        SIGN_REAR_RIGHT * (vx + vy - omega),
    )


def rotate_in_place(direction: RotationDirection, speed: float = ROTATE_SPEED) -> WheelSpeeds:
    """Wheel speeds that spin the robot on the spot.

    Args:
        direction: "cw" (clockwise from above, i.e. turn right) or "ccw".
        speed: rotation speed magnitude, default config.ROTATE_SPEED.

    Returns:
        WheelSpeeds: left wheels one way, right wheels the other.

    Raises:
        ValueError: if `direction` is not "cw" or "ccw".
    """
    if direction == "cw":
        return wheel_speeds(0, 0, speed)
    if direction == "ccw":
        return wheel_speeds(0, 0, -speed)
    raise ValueError(f"direction must be 'cw' or 'ccw', got {direction!r}")


def strafe(direction: StrafeDirection, speed: float = STRAFE_SPEED) -> WheelSpeeds:
    """Wheel speeds that slide the robot sideways without turning.

    Args:
        direction: "left" or "right".
        speed: strafe speed magnitude, default config.STRAFE_SPEED.

    Returns:
        WheelSpeeds: the diagonal pairs (front_left/rear_right and
        front_right/rear_left) driven in opposite directions.

    Raises:
        ValueError: if `direction` is not "left" or "right".
    """
    if direction == "right":
        return wheel_speeds(0, speed, 0)
    if direction == "left":
        return wheel_speeds(0, -speed, 0)
    raise ValueError(f"direction must be 'left' or 'right', got {direction!r}")
