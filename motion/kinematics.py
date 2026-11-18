"""Mecanum wheel kinematics: chassis motion in, four wheel speeds out.

Pure math only. This module imports no hardware library, keeps no state and
has no hardware tunables. Which motor ID drives which wheel, and whether a
wheel is wired backwards, live in motion.mecanum. So the sign patterns here
are the logical ones: +1 means "this wheel drives the robot forward".

Chassis frame (robot-centric, seen from above):
    vx     > 0  drives forward
    vy     > 0  strafes right
    omega  > 0  rotates clockwise (turns right)

These match the direction words the rest of the project uses ("cw", "right"),
so a target right of center maps to a positive command.

Wheel speeds are normalized (1.0 = full speed forward; see config.MAX_SPEED).
Nothing here clamps them: the real driver clamps to config.MAX_SPEED.
"""

from __future__ import annotations

from typing import Literal

from config import ROTATE_SPEED, STRAFE_SPEED

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

    Args:
        vx: forward speed (negative is backward).
        vy: rightward strafe speed (negative is leftward).
        omega: clockwise rotation speed (negative is counterclockwise).

    Returns:
        WheelSpeeds: (front_left, front_right, rear_left, rear_right).
    """
    return (
        vx + vy + omega,
        vx - vy - omega,
        vx - vy + omega,
        vx + vy - omega,
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
