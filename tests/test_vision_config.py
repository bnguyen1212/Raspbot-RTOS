"""Sanity checks on the vision constants in config.py.

The HSV ranges are placeholders that will be retuned on the robot. These tests
catch the tuning mistakes that would otherwise fail silently: cv2.inRange
accepts an out-of-scale or reversed range and just matches nothing.
"""

from __future__ import annotations

import itertools

import pytest

from config import (
    COMMAND_COLORS,
    IMAGE_CENTER_X,
    IMAGE_HEIGHT,
    IMAGE_WIDTH,
    MASK_OPEN_KERNEL_PX,
    MIN_PIXEL_THRESHOLD,
    TRACKED_COLORS,
)

CHANNEL_MAX = (179, 255, 255)  # OpenCV's H, S, V scale for uint8 images


def test_tracked_colors_are_the_command_colors_in_order():
    assert TRACKED_COLORS == ("green", "blue", "red")
    assert TRACKED_COLORS == tuple(COMMAND_COLORS)


@pytest.mark.parametrize("color", list(COMMAND_COLORS))
def test_every_range_is_valid_on_the_opencv_hsv_scale(color):
    ranges = COMMAND_COLORS[color]
    assert len(ranges) >= 1
    for lower, upper in ranges:
        assert len(lower) == len(upper) == 3
        for lo, hi, top in zip(lower, upper, CHANNEL_MAX):
            assert isinstance(lo, int) and isinstance(hi, int)
            assert 0 <= lo <= hi <= top, (
                f"{color}: bad range {lower}..{upper}. Bounds must satisfy 0 <= lower <= upper, "
                f"H <= 179, S/V <= 255. A hue that wraps past 179 needs two ranges, like red."
            )


def _overlap(a, b) -> bool:
    return all(max(lo_a, lo_b) <= min(hi_a, hi_b) for lo_a, hi_a, lo_b, hi_b in zip(*a, *b))


@pytest.mark.parametrize("first, second", list(itertools.combinations(COMMAND_COLORS, 2)))
def test_different_colors_do_not_share_any_hsv_value(first, second):
    """A pixel that counts for two colors would make the winner ambiguous."""
    for range_a in COMMAND_COLORS[first]:
        for range_b in COMMAND_COLORS[second]:
            assert not _overlap(range_a, range_b), f"{first} {range_a} overlaps {second} {range_b}"


def test_threshold_and_kernel_are_sensible():
    assert isinstance(MIN_PIXEL_THRESHOLD, int)
    assert 0 < MIN_PIXEL_THRESHOLD <= IMAGE_WIDTH * IMAGE_HEIGHT
    assert isinstance(MASK_OPEN_KERNEL_PX, int)
    assert 0 <= MASK_OPEN_KERNEL_PX < min(IMAGE_WIDTH, IMAGE_HEIGHT)
    assert MASK_OPEN_KERNEL_PX <= 1 or MASK_OPEN_KERNEL_PX % 2 == 1, "kernel must be odd"
    assert IMAGE_CENTER_X == IMAGE_WIDTH // 2
