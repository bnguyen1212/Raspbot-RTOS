"""Unit tests for vision.color_locator.ColorLocator.

Uses synthetic frames (see tests/vision_images.py) plus either ColorCounter's
real output or hand-built color_counts dicts, so no camera or robot is
required.
"""

from __future__ import annotations

import time

import numpy as np
import pytest

import vision.color_locator as color_locator_module
from config import IDLE_SENTINEL, IMAGE_HEIGHT, IMAGE_WIDTH, MIN_PIXEL_THRESHOLD, TRACKED_COLORS
from tests.vision_images import (
    bgr_inside,
    blank_frame,
    color_bgr,
    draw_rect,
    rect_center,
    red_end_ranges,
)
from vision.color_counter import ColorCounter
from vision.color_locator import ColorLocator


# 31 px wide and just tall enough to reach MIN_PIXEL_THRESHOLD (odd size, so
# the centroid lands on a pixel), derived so retuning the threshold can't
# turn this into an idle case.
_SMALL_H = -(-MIN_PIXEL_THRESHOLD // 31) | 1
SMALL_CORNER_RECT = (0, 0, 31, _SMALL_H)
TIE = 2 * MIN_PIXEL_THRESHOLD  # a count comfortably above the threshold


def locate(image):
    """The real pipeline, as run_loop runs it."""
    return ColorLocator(ColorCounter(image), image)


# ---------------------------------------------------------------------------
# Idle
# ---------------------------------------------------------------------------

def test_blank_image_is_idle():
    result = locate(blank_frame())

    assert result == IDLE_SENTINEL == (None, None)
    winning_color, p_vector = result  # always unpackable
    assert winning_color is None and p_vector is None


def test_all_zero_counts_are_idle():
    assert ColorLocator({"green": 0, "blue": 0, "red": 0}, blank_frame()) == IDLE_SENTINEL


@pytest.mark.parametrize("color", TRACKED_COLORS)
def test_winner_below_threshold_is_idle(color):
    image = blank_frame()
    area = draw_rect(image, 100, 100, 100 + 10, 100 + (MIN_PIXEL_THRESHOLD - 1) // 10, color_bgr(color))
    assert area < MIN_PIXEL_THRESHOLD

    assert locate(image) == IDLE_SENTINEL


@pytest.mark.parametrize("color", TRACKED_COLORS)
def test_winner_exactly_at_threshold_is_detected(color):
    """'Below the threshold' means idle, so exactly the threshold is detected."""
    counts = {c: 0 for c in TRACKED_COLORS}
    counts[color] = MIN_PIXEL_THRESHOLD
    image = blank_frame()
    draw_rect(image, 0, 0, 40, 40, color_bgr(color))

    assert ColorLocator(counts, image)[0] == color


def test_several_colors_each_below_threshold_are_idle_even_if_their_sum_is_not():
    image = blank_frame()
    side = int((MIN_PIXEL_THRESHOLD - 1) ** 0.5)
    for i, color in enumerate(TRACKED_COLORS):
        draw_rect(image, 100 * i, 0, 100 * i + side, side, color_bgr(color))
    counts = ColorCounter(image)
    assert sum(counts.values()) >= MIN_PIXEL_THRESHOLD

    assert ColorLocator(counts, image) == IDLE_SENTINEL


def test_counts_that_do_not_match_the_image_give_idle_not_a_bogus_position():
    """Defensive: if the caller passes counts from a different frame, the
    winner's rebuilt mask can be empty. That must not produce NaN or a made-up
    position that would steer the robot."""
    counts = {"green": 10_000, "blue": 0, "red": 0}

    assert ColorLocator(counts, blank_frame()) == IDLE_SENTINEL


# ---------------------------------------------------------------------------
# Winner and position
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("color", TRACKED_COLORS)
@pytest.mark.parametrize(
    "rect",
    [
        (100, 80, 300, 260),     # left of center
        (270, 190, 371, 291),    # centered, odd size -> exact integer center
        (500, 300, 640, 480),    # touching the bottom-right corner
        SMALL_CORNER_RECT,       # just over the threshold, top-left corner
    ],
)
def test_detects_color_and_returns_its_rectangle_center(color, rect):
    image = blank_frame()
    draw_rect(image, *rect, color_bgr(color))

    winning_color, (x, y) = locate(image)

    expected_x, expected_y = rect_center(*rect)
    assert winning_color == color
    assert x == pytest.approx(expected_x, abs=0.5)
    assert y == pytest.approx(expected_y, abs=0.5)


def test_position_is_a_tuple_of_plain_floats_inside_the_frame():
    image = blank_frame()
    draw_rect(image, 600, 440, 640, 480, color_bgr("blue"))

    winning_color, p_vector = locate(image)

    assert winning_color == "blue"
    assert type(p_vector) is tuple and len(p_vector) == 2
    x, y = p_vector
    assert type(x) is float and type(y) is float
    assert 0 <= x < IMAGE_WIDTH and 0 <= y < IMAGE_HEIGHT


@pytest.mark.parametrize("end", ["low", "high"])
def test_red_is_located_at_either_end_of_the_hue_circle(end):
    low_range, high_range = red_end_ranges()
    hsv_range = low_range if end == "low" else high_range
    image = blank_frame()
    rect = (400, 50, 520, 210)
    draw_rect(image, *rect, bgr_inside(hsv_range))

    winning_color, (x, y) = locate(image)

    assert winning_color == "red"
    assert (x, y) == pytest.approx(rect_center(*rect), abs=0.5)


def test_red_split_across_both_hue_ends_is_one_object():
    """A card whose pixels straddle hue 0/180 (common for real red) is
    located as one object, at the mean position of all of its pixels."""
    low_range, high_range = red_end_ranges()
    image = blank_frame()
    draw_rect(image, 100, 100, 200, 300, bgr_inside(low_range))   # left half of the card
    draw_rect(image, 200, 100, 300, 300, bgr_inside(high_range))  # right half

    winning_color, (x, y) = locate(image)

    assert winning_color == "red"
    assert (x, y) == pytest.approx(rect_center(100, 100, 300, 300), abs=0.5)


def test_larger_color_wins_and_its_position_is_returned():
    image = blank_frame()
    draw_rect(image, 0, 0, 100, 100, color_bgr("green"))          # 10,000 px
    big = (300, 100, 500, 400)
    draw_rect(image, *big, color_bgr("red"))                      # 60,000 px
    draw_rect(image, 560, 400, 640, 480, color_bgr("blue"))       # 6,400 px

    winning_color, (x, y) = locate(image)

    assert winning_color == "red"
    assert (x, y) == pytest.approx(rect_center(*big), abs=0.5)


def test_other_colors_do_not_pull_the_winners_position():
    image = blank_frame()
    target = (50, 50, 250, 250)
    draw_rect(image, *target, color_bgr("blue"))
    draw_rect(image, 500, 300, 600, 400, color_bgr("green"))  # smaller, far away

    assert locate(image)[1] == pytest.approx(rect_center(*target), abs=0.5)


def test_speckle_noise_does_not_move_the_position():
    image = blank_frame()
    target = (270, 190, 371, 291)
    draw_rect(image, *target, color_bgr("green"))
    image[0:480:6, 0:200:6] = color_bgr("green")  # isolated noise on the left

    assert locate(image)[1] == pytest.approx(rect_center(*target), abs=0.5)


def test_two_blobs_of_the_winning_color_give_their_mean_position():
    """The assignment's 'average position of all matching pixels'."""
    image = blank_frame()
    draw_rect(image, 0, 0, 100, 100, color_bgr("green"))
    draw_rect(image, 500, 0, 600, 100, color_bgr("green"))

    assert locate(image) == ("green", pytest.approx((299.5, 49.5), abs=0.5))


# ---------------------------------------------------------------------------
# Tie-break: TRACKED_COLORS order, whatever the dict order
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "counts, expected",
    [
        ({"green": TIE, "blue": TIE, "red": TIE}, "green"),
        ({"red": TIE, "blue": TIE, "green": TIE}, "green"),  # dict order ignored
        ({"red": TIE, "blue": TIE, "green": 0}, "blue"),
        ({"green": 5, "blue": TIE, "red": TIE}, "blue"),
    ],
)
def test_ties_go_to_the_earliest_color_in_tracked_colors_order(counts, expected):
    image = blank_frame()
    for i, color in enumerate(TRACKED_COLORS):
        draw_rect(image, 200 * i, 0, 200 * i + 50, 50, color_bgr(color))

    assert ColorLocator(counts, image)[0] == expected


# ---------------------------------------------------------------------------
# Contract details
# ---------------------------------------------------------------------------

def test_only_the_winning_colors_mask_is_rebuilt(monkeypatch):
    calls = []
    real_color_mask = color_locator_module.color_mask

    def spy(hsv, ranges, *args, **kwargs):
        calls.append(ranges)
        return real_color_mask(hsv, ranges, *args, **kwargs)

    monkeypatch.setattr(color_locator_module, "color_mask", spy)
    image = blank_frame()
    draw_rect(image, 0, 0, 100, 100, color_bgr("blue"))
    draw_rect(image, 200, 200, 230, 230, color_bgr("green"))

    assert locate(image)[0] == "blue"
    assert calls == [color_locator_module.COMMAND_COLORS["blue"]]


def test_no_mask_is_built_when_idle(monkeypatch):
    monkeypatch.setattr(color_locator_module, "color_mask", pytest.fail)

    assert ColorLocator({"green": 0, "blue": 1, "red": 2}, blank_frame()) == IDLE_SENTINEL


def test_missing_color_key_raises_key_error():
    with pytest.raises(KeyError):
        ColorLocator({"green": 1000, "blue": 0}, blank_frame())


def test_threshold_comes_from_config(monkeypatch):
    image = blank_frame()
    draw_rect(image, 0, 0, 100, 100, color_bgr("green"))  # 10,000 px
    counts = ColorCounter(image)

    monkeypatch.setattr(color_locator_module, "MIN_PIXEL_THRESHOLD", 10_001)
    assert ColorLocator(counts, image) == IDLE_SENTINEL
    monkeypatch.setattr(color_locator_module, "MIN_PIXEL_THRESHOLD", 10_000)
    assert ColorLocator(counts, image)[0] == "green"


def test_input_frame_is_not_modified():
    image = blank_frame()
    draw_rect(image, 10, 10, 200, 200, color_bgr("red"))
    before = image.copy()

    locate(image)

    np.testing.assert_array_equal(image, before)


# ---------------------------------------------------------------------------
# Speed: the loop runs these on every pass on a Raspberry Pi
# ---------------------------------------------------------------------------

def test_full_resolution_frame_is_processed_well_under_50_ms():
    """Median of several runs, on a noisy frame (worst case for masking).
    A dev machine should be far below this; the Pi is slower, which is why
    the bound is set at the issue's budget and not tighter."""
    rng = np.random.default_rng(0)
    image = rng.integers(0, 256, (IMAGE_HEIGHT, IMAGE_WIDTH, 3), dtype=np.uint8)
    draw_rect(image, 200, 100, 400, 300, color_bgr("green"))
    locate(image)  # warm-up

    durations = []
    for _ in range(15):
        start = time.perf_counter()
        locate(image)
        durations.append(time.perf_counter() - start)

    assert sorted(durations)[len(durations) // 2] < 0.050
