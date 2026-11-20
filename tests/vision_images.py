"""Synthetic-image helpers shared by the vision tests.

The test colors are derived from config.COMMAND_COLORS instead of being
hardcoded BGR values, so the tests keep passing when the HSV ranges get tuned
on the robot (the ranges in config.py are placeholders).
"""

from __future__ import annotations

import cv2
import numpy as np

from config import COMMAND_COLORS, IMAGE_HEIGHT, IMAGE_WIDTH, HSVRange

BGR = tuple[int, int, int]


def blank_frame(height: int = IMAGE_HEIGHT, width: int = IMAGE_WIDTH) -> np.ndarray:
    """An all-black BGR frame (matches no color: V = 0)."""
    return np.zeros((height, width, 3), dtype=np.uint8)


def hsv_to_bgr(h: int, s: int, v: int) -> BGR:
    """Convert one OpenCV HSV value to a BGR tuple."""
    b, g, r = cv2.cvtColor(np.uint8([[[h, s, v]]]), cv2.COLOR_HSV2BGR)[0, 0]
    return int(b), int(g), int(r)


def in_range(hsv: tuple[int, int, int], hsv_range: HSVRange) -> bool:
    lower, upper = hsv_range
    return all(lo <= value <= hi for value, lo, hi in zip(hsv, lower, upper))


def bgr_inside(hsv_range: HSVRange) -> BGR:
    """A BGR color whose HSV lands inside `hsv_range` after the round trip.

    Aims for the middle of the hue range and the upper part of the S and V
    ranges (a saturated, well-lit card), then checks that BGR -> HSV really
    lands back inside, since the HSV -> BGR -> HSV round trip rounds.
    """
    (h_lo, s_lo, v_lo), (h_hi, s_hi, v_hi) = hsv_range
    target = ((h_lo + h_hi) // 2, (s_lo + 3 * s_hi) // 4, (v_lo + 3 * v_hi) // 4)
    bgr = hsv_to_bgr(*target)
    back = tuple(int(c) for c in cv2.cvtColor(np.uint8([[bgr]]), cv2.COLOR_BGR2HSV)[0, 0])
    assert in_range(back, hsv_range), f"test color {bgr} -> HSV {back} left {hsv_range}"
    return bgr


def color_bgr(color: str) -> BGR:
    """A BGR color that config.COMMAND_COLORS classifies as `color`."""
    return bgr_inside(COMMAND_COLORS[color][0])


def red_end_ranges() -> tuple[HSVRange, HSVRange]:
    """Red's (low-hue, high-hue) ranges: the two ends of the hue circle."""
    ranges = sorted(COMMAND_COLORS["red"], key=lambda r: r[0][0])
    return ranges[0], ranges[-1]


def draw_rect(image: np.ndarray, x0: int, y0: int, x1: int, y1: int, bgr: BGR) -> int:
    """Fill columns x0..x1-1, rows y0..y1-1 with `bgr`. Returns the pixel area."""
    image[y0:y1, x0:x1] = bgr
    return (x1 - x0) * (y1 - y0)


def rect_center(x0: int, y0: int, x1: int, y1: int) -> tuple[float, float]:
    """The exact mean pixel position of the rectangle drawn by draw_rect."""
    return (x0 + x1 - 1) / 2, (y0 + y1 - 1) / 2
