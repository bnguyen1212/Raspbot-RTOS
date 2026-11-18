"""Unit tests for motion.kinematics: wheel sign patterns for each motion.

Expected values are written as the physical pattern (+1 = wheel drives
forward) and then passed through the module's SIGN_* constants by
`on_wheels`. So these tests stay correct after a sign is flipped to match the
real robot's wiring.
"""

from __future__ import annotations

import pytest

from config import ROTATE_SPEED, STRAFE_SPEED
from motion import kinematics
from motion.kinematics import WheelSpeeds, rotate_in_place, strafe, wheel_speeds


def on_wheels(fl: float, fr: float, rl: float, rr: float) -> WheelSpeeds:
    """Apply the module's current wheel polarity to a physical pattern."""
    return (
        kinematics.SIGN_FRONT_LEFT * fl,
        kinematics.SIGN_FRONT_RIGHT * fr,
        kinematics.SIGN_REAR_LEFT * rl,
        kinematics.SIGN_REAR_RIGHT * rr,
    )


def test_sign_constants_are_plus_or_minus_one():
    for name in ("SIGN_FRONT_LEFT", "SIGN_FRONT_RIGHT", "SIGN_REAR_LEFT", "SIGN_REAR_RIGHT"):
        assert getattr(kinematics, name) in (1, -1), name


# ---------------------------------------------------------------------------
# wheel_speeds
# ---------------------------------------------------------------------------

def test_zero_velocity_stops_every_wheel():
    assert wheel_speeds(0, 0, 0) == (0, 0, 0, 0)


def test_forward_drives_all_wheels_forward():
    assert wheel_speeds(10, 0, 0) == on_wheels(10, 10, 10, 10)


def test_positive_vy_is_the_right_strafe_pattern():
    # Front-left and rear-right forward, the other diagonal backward.
    assert wheel_speeds(0, 10, 0) == on_wheels(10, -10, -10, 10)


def test_positive_omega_is_the_clockwise_pattern():
    # Left side forward, right side backward: the robot turns right.
    assert wheel_speeds(0, 0, 10) == on_wheels(10, -10, 10, -10)


def test_motions_combine_linearly():
    combined = wheel_speeds(3, 5, 7)
    parts = [wheel_speeds(3, 0, 0), wheel_speeds(0, 5, 0), wheel_speeds(0, 0, 7)]
    assert combined == tuple(sum(wheel) for wheel in zip(*parts))


# ---------------------------------------------------------------------------
# rotate_in_place
# ---------------------------------------------------------------------------

def test_rotate_cw_sign_pattern():
    s = ROTATE_SPEED
    assert rotate_in_place("cw") == on_wheels(s, -s, s, -s)


def test_rotate_ccw_sign_pattern():
    s = ROTATE_SPEED
    assert rotate_in_place("ccw") == on_wheels(-s, s, -s, s)


def test_rotate_ccw_is_the_opposite_of_cw():
    assert rotate_in_place("ccw") == tuple(-w for w in rotate_in_place("cw"))


def test_rotate_uses_the_given_speed():
    assert rotate_in_place("cw", 7) == on_wheels(7, -7, 7, -7)


def test_rotation_has_no_net_forward_or_sideways_drive():
    # Every wheel turns at the same magnitude; the two sides cancel out.
    fl, fr, rl, rr = on_wheels(*rotate_in_place("cw"))  # back to physical
    assert fl + fr + rl + rr == 0  # no forward component
    assert fl - fr - rl + rr == 0  # no strafe component


# ---------------------------------------------------------------------------
# strafe
# ---------------------------------------------------------------------------

def test_strafe_right_sign_pattern():
    s = STRAFE_SPEED
    assert strafe("right") == on_wheels(s, -s, -s, s)


def test_strafe_left_sign_pattern():
    s = STRAFE_SPEED
    assert strafe("left") == on_wheels(-s, s, s, -s)


def test_strafe_left_is_the_opposite_of_right():
    assert strafe("left") == tuple(-w for w in strafe("right"))


def test_strafe_uses_the_given_speed():
    assert strafe("right", 7) == on_wheels(7, -7, -7, 7)


def test_strafe_has_no_net_forward_drive_or_rotation():
    fl, fr, rl, rr = on_wheels(*strafe("right"))  # back to physical
    assert fl + fr + rl + rr == 0  # no forward component
    assert fl - fr + rl - rr == 0  # no rotation component


# ---------------------------------------------------------------------------
# Bad input and polarity flips
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad", ["left", "CW", "", "clockwise"])
def test_rotate_rejects_unknown_direction(bad):
    with pytest.raises(ValueError):
        rotate_in_place(bad)


@pytest.mark.parametrize("bad", ["cw", "RIGHT", "", "forward"])
def test_strafe_rejects_unknown_direction(bad):
    with pytest.raises(ValueError):
        strafe(bad)


@pytest.mark.parametrize(
    ("name", "index"),
    [
        ("SIGN_FRONT_LEFT", 0),
        ("SIGN_FRONT_RIGHT", 1),
        ("SIGN_REAR_LEFT", 2),
        ("SIGN_REAR_RIGHT", 3),
    ],
)
def test_flipping_one_sign_flips_only_that_wheel(monkeypatch, name, index):
    before = rotate_in_place("cw")
    monkeypatch.setattr(kinematics, name, -getattr(kinematics, name))
    after = rotate_in_place("cw")
    for i in range(4):
        expected = -before[i] if i == index else before[i]
        assert after[i] == expected
