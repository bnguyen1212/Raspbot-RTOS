"""Unit tests for motion.centering.centering_command.

Inputs are built from config constants, so the tests stay correct after
IMAGE_CENTER_X or CENTER_DEADBAND_PX is tuned.
"""

from __future__ import annotations

import pytest

from config import CENTER_DEADBAND_PX, IMAGE_CENTER_X, IMAGE_WIDTH
from motion.centering import centering_command

C = IMAGE_CENTER_X
D = CENTER_DEADBAND_PX


def test_dead_center_is_centered():
    assert centering_command(C) == "centered"


@pytest.mark.parametrize("offset", [1, D / 2, D - 1])
def test_inside_deadband_is_centered_on_both_sides(offset):
    assert centering_command(C + offset) == "centered"
    assert centering_command(C - offset) == "centered"


def test_exactly_on_the_right_boundary_is_centered():
    assert centering_command(C + D) == "centered"


def test_exactly_on_the_left_boundary_is_centered():
    assert centering_command(C - D) == "centered"


@pytest.mark.parametrize("past", [0.001, 1, 100])
def test_just_past_the_right_boundary_is_right(past):
    assert centering_command(C + D + past) == "right"


@pytest.mark.parametrize("past", [0.001, 1, 100])
def test_just_past_the_left_boundary_is_left(past):
    assert centering_command(C - D - past) == "left"


def test_image_edges():
    assert centering_command(0) == "left"
    assert centering_command(IMAGE_WIDTH - 1) == "right"


def test_defaults_come_from_config():
    for x in (0, C - D - 1, C - D, C, C + D, C + D + 1, IMAGE_WIDTH - 1):
        assert centering_command(x) == centering_command(x, C, D)


def test_explicit_center_and_deadband():
    assert centering_command(105, image_center_x=100, deadband=5) == "centered"
    assert centering_command(106, image_center_x=100, deadband=5) == "right"
    assert centering_command(94, image_center_x=100, deadband=5) == "left"


def test_zero_deadband_only_exact_center_is_centered():
    assert centering_command(C, deadband=0) == "centered"
    assert centering_command(C + 0.5, deadband=0) == "right"
    assert centering_command(C - 0.5, deadband=0) == "left"


def test_negative_deadband_is_rejected():
    with pytest.raises(ValueError):
        centering_command(C, deadband=-1)
