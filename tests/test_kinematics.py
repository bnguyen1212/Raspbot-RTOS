"""Unit tests for motion.kinematics: the logical wheel sign patterns.

These are the patterns in logical wheel directions (+ = that wheel drives the
robot forward). Motor IDs and wiring inversions are motion.mecanum's job and
are tested in test_mecanum.py.
"""

from __future__ import annotations

import pytest

from config import ROTATE_SPEED, STRAFE_SPEED
from motion import kinematics
from motion.kinematics import rotate_in_place, strafe, wheel_speeds


def test_no_hardware_tunables():
    # Wiring belongs in motion.mecanum, not here.
    tunables = [n for n in vars(kinematics) if n.startswith(("SIGN_", "INVERT", "MOTOR_ID"))]
    assert tunables == []


# ---------------------------------------------------------------------------
# wheel_speeds
# ---------------------------------------------------------------------------

def test_zero_velocity_stops_every_wheel():
    assert wheel_speeds(0, 0, 0) == (0, 0, 0, 0)


def test_forward_drives_all_wheels_forward():
    assert wheel_speeds(0.3, 0, 0) == (0.3, 0.3, 0.3, 0.3)


def test_positive_vy_is_the_right_strafe_pattern():
    # Front-left and rear-right forward, the other diagonal backward.
    assert wheel_speeds(0, 0.3, 0) == (0.3, -0.3, -0.3, 0.3)


def test_positive_omega_is_the_clockwise_pattern():
    # Left side forward, right side backward: the robot turns right.
    assert wheel_speeds(0, 0, 0.3) == (0.3, -0.3, 0.3, -0.3)


def test_motions_combine_linearly():
    combined = wheel_speeds(3, 5, 7)
    parts = [wheel_speeds(3, 0, 0), wheel_speeds(0, 5, 0), wheel_speeds(0, 0, 7)]
    assert combined == tuple(sum(wheel) for wheel in zip(*parts))


# ---------------------------------------------------------------------------
# rotate_in_place
# ---------------------------------------------------------------------------

def test_rotate_cw_sign_pattern():
    s = ROTATE_SPEED
    assert rotate_in_place("cw") == (s, -s, s, -s)


def test_rotate_ccw_sign_pattern():
    s = ROTATE_SPEED
    assert rotate_in_place("ccw") == (-s, s, -s, s)


def test_rotate_ccw_is_the_opposite_of_cw():
    assert rotate_in_place("ccw") == tuple(-w for w in rotate_in_place("cw"))


def test_rotate_uses_the_given_speed():
    assert rotate_in_place("cw", 0.3) == (0.3, -0.3, 0.3, -0.3)


def test_rotation_has_no_net_forward_or_sideways_drive():
    fl, fr, rl, rr = rotate_in_place("cw")
    assert fl + fr + rl + rr == 0  # no forward component
    assert fl - fr - rl + rr == 0  # no strafe component


# ---------------------------------------------------------------------------
# strafe
# ---------------------------------------------------------------------------

def test_strafe_right_sign_pattern():
    s = STRAFE_SPEED
    assert strafe("right") == (s, -s, -s, s)


def test_strafe_left_sign_pattern():
    s = STRAFE_SPEED
    assert strafe("left") == (-s, s, s, -s)


def test_strafe_left_is_the_opposite_of_right():
    assert strafe("left") == tuple(-w for w in strafe("right"))


def test_strafe_uses_the_given_speed():
    assert strafe("right", 0.3) == (0.3, -0.3, -0.3, 0.3)


def test_strafe_has_no_net_forward_drive_or_rotation():
    fl, fr, rl, rr = strafe("right")
    assert fl + fr + rl + rr == 0  # no forward component
    assert fl - fr + rl - rr == 0  # no rotation component


# ---------------------------------------------------------------------------
# Bad input
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad", ["left", "CW", "", "clockwise"])
def test_rotate_rejects_unknown_direction(bad):
    with pytest.raises(ValueError):
        rotate_in_place(bad)


@pytest.mark.parametrize("bad", ["cw", "RIGHT", "", "forward"])
def test_strafe_rejects_unknown_direction(bad):
    with pytest.raises(ValueError):
        strafe(bad)
