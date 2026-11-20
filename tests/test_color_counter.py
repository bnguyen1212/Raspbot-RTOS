"""Unit tests for vision.color_counter.ColorCounter and its mask helper.

Uses synthetic numpy frames (see tests/vision_images.py), so no camera or
robot is required. Real photos are covered by tests/test_sample_images.py.
"""

from __future__ import annotations

import numpy as np
import pytest

import vision.color_counter as color_counter_module
from config import COMMAND_COLORS, IMAGE_HEIGHT, IMAGE_WIDTH, TRACKED_COLORS
from tests.vision_images import blank_frame, color_bgr, draw_rect, hsv_to_bgr, red_end_ranges, bgr_inside
from vision.color_counter import ColorCounter
from vision.hsv_mask import color_mask, mask_centroid, to_hsv


# ---------------------------------------------------------------------------
# Output shape
# ---------------------------------------------------------------------------

def test_blank_image_counts_zero_for_every_color():
    counts = ColorCounter(blank_frame())

    assert counts == {color: 0 for color in TRACKED_COLORS}


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_output_always_has_exactly_the_tracked_colors_as_plain_ints(seed):
    image = np.random.default_rng(seed).integers(0, 256, (IMAGE_HEIGHT, IMAGE_WIDTH, 3), dtype=np.uint8)

    counts = ColorCounter(image)

    assert tuple(counts) == TRACKED_COLORS  # all keys, in TRACKED_COLORS order
    for value in counts.values():
        assert type(value) is int  # not numpy.int64
        assert 0 <= value <= IMAGE_HEIGHT * IMAGE_WIDTH


# ---------------------------------------------------------------------------
# Each color
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("color", TRACKED_COLORS)
def test_solid_rectangle_is_counted_exactly_for_its_color_only(color):
    image = blank_frame()
    area = draw_rect(image, 100, 80, 300, 260, color_bgr(color))

    counts = ColorCounter(image)

    assert counts[color] == area
    assert all(counts[other] == 0 for other in TRACKED_COLORS if other != color)


@pytest.mark.parametrize(
    "color, bgr",
    [("green", (0, 255, 0)), ("blue", (255, 0, 0)), ("red", (0, 0, 255))],
)
def test_pure_bgr_primaries_are_detected(color, bgr):
    """The issue's suggested test colors. Pure primaries should stay inside
    any sensible tuning of the ranges."""
    image = blank_frame()
    area = draw_rect(image, 0, 0, 50, 40, bgr)

    assert ColorCounter(image)[color] == area


def test_red_is_counted_at_both_ends_of_the_hue_circle():
    low_range, high_range = red_end_ranges()
    assert low_range[0][0] == 0 and high_range[1][0] == 179, "red should wrap around hue 0/180"
    image = blank_frame()
    low_area = draw_rect(image, 0, 0, 100, 100, bgr_inside(low_range))
    high_area = draw_rect(image, 200, 200, 260, 300, bgr_inside(high_range))

    counts = ColorCounter(image)

    assert counts["red"] == low_area + high_area
    assert counts["green"] == counts["blue"] == 0


@pytest.mark.parametrize("hue", [0, 179])
def test_red_extreme_hues_are_counted(hue):
    image = blank_frame()
    area = draw_rect(image, 10, 10, 60, 60, hsv_to_bgr(hue, 255, 255))

    assert ColorCounter(image)["red"] == area


def test_several_colors_in_one_frame_are_counted_independently():
    image = blank_frame()
    green = draw_rect(image, 0, 0, 100, 100, color_bgr("green"))
    blue = draw_rect(image, 200, 0, 250, 300, color_bgr("blue"))
    red = draw_rect(image, 400, 300, 640, 480, color_bgr("red"))

    assert ColorCounter(image) == {"green": green, "blue": blue, "red": red}


@pytest.mark.parametrize(
    "bgr",
    [(255, 255, 255), (128, 128, 128), (30, 30, 30), (0, 0, 0)],
    ids=["white", "gray", "dark-gray", "black"],
)
def test_unsaturated_or_dark_pixels_match_no_color(bgr):
    image = np.full((IMAGE_HEIGHT, IMAGE_WIDTH, 3), bgr, dtype=np.uint8)

    assert sum(ColorCounter(image).values()) == 0


@pytest.mark.parametrize(
    "hsv",
    [(8, 150, 120), (9, 137, 105), (10, 113, 82), (10, 155, 180), (2, 120, 70), (176, 130, 100)],
)
def test_skin_tones_are_not_red(hsv):
    """HSV values measured on skin (face, neck, arm) in webcam frames, which
    the original red range (S >= 120) counted as red: a person in view could
    win as "red" with no card present."""
    image = blank_frame()
    draw_rect(image, 100, 100, 300, 300, hsv_to_bgr(*hsv))

    assert ColorCounter(image)["red"] == 0


# ---------------------------------------------------------------------------
# Noise removal (morphological opening)
# ---------------------------------------------------------------------------

def test_isolated_speckles_are_not_counted():
    image = blank_frame()
    rng = np.random.default_rng(42)
    ys = rng.integers(0, IMAGE_HEIGHT, 2000)
    xs = rng.integers(0, IMAGE_WIDTH, 2000)
    image[ys, xs] = color_bgr("green")  # scattered single pixels
    # Keep every speck isolated so the expectation is exact.
    image[::2, :] = 0
    image[:, ::2] = 0

    assert ColorCounter(image)["green"] == 0


def test_speckles_do_not_change_the_count_of_a_solid_card():
    image = blank_frame()
    area = draw_rect(image, 300, 200, 400, 300, color_bgr("blue"))
    image[10:200:4, 10:200:4] = color_bgr("blue")  # isolated noise, away from the card

    assert ColorCounter(image)["blue"] == area


def test_card_touching_the_frame_edges_is_counted_fully():
    """Opening must not erode a card cut off by the image border."""
    image = blank_frame()
    area = draw_rect(image, 0, 0, 120, IMAGE_HEIGHT, color_bgr("green"))
    area += draw_rect(image, IMAGE_WIDTH - 50, 0, IMAGE_WIDTH, 50, color_bgr("green"))

    assert ColorCounter(image)["green"] == area


def test_color_mask_opening_can_be_disabled():
    hsv = to_hsv(blank_frame())
    hsv[5, 5] = (60, 255, 255)  # one green speck
    green = COMMAND_COLORS["green"]

    assert np.count_nonzero(color_mask(hsv, green, open_kernel_px=1)) == 1
    assert np.count_nonzero(color_mask(hsv, green, open_kernel_px=0)) == 1
    assert np.count_nonzero(color_mask(hsv, green, open_kernel_px=3)) == 0


# ---------------------------------------------------------------------------
# Ranges come from config, and any valid ranges work
# ---------------------------------------------------------------------------

def test_overlapping_ranges_count_each_pixel_once(monkeypatch):
    overlapping = {
        **COMMAND_COLORS,
        "red": (((0, 100, 100), (10, 255, 255)), ((0, 100, 100), (5, 255, 255))),
    }
    monkeypatch.setattr(color_counter_module, "COMMAND_COLORS", overlapping)
    image = blank_frame()
    area = draw_rect(image, 0, 0, 40, 40, hsv_to_bgr(2, 255, 255))  # in both ranges

    assert ColorCounter(image)["red"] == area


def test_counter_uses_the_configured_ranges(monkeypatch):
    """Retuning COMMAND_COLORS changes what counts, with no code change.
    Here "green" is retuned to a narrow yellow band."""
    yellow_band = {**COMMAND_COLORS, "green": (((25, 100, 100), (32, 255, 255)),)}
    monkeypatch.setattr(color_counter_module, "COMMAND_COLORS", yellow_band)
    image = blank_frame()
    yellow = draw_rect(image, 0, 0, 50, 50, hsv_to_bgr(28, 255, 255))
    draw_rect(image, 100, 100, 150, 150, hsv_to_bgr(60, 255, 255))  # pure green, now out of range

    assert ColorCounter(image)["green"] == yellow


def test_counter_supports_any_number_of_tracked_colors(monkeypatch):
    extended = {**COMMAND_COLORS, "yellow": (((25, 100, 100), (32, 255, 255)),)}
    monkeypatch.setattr(color_counter_module, "COMMAND_COLORS", extended)
    monkeypatch.setattr(color_counter_module, "TRACKED_COLORS", tuple(extended))
    image = blank_frame()
    area = draw_rect(image, 0, 0, 50, 50, hsv_to_bgr(28, 255, 255))

    counts = ColorCounter(image)

    assert tuple(counts) == tuple(extended)
    assert counts["yellow"] == area


@pytest.mark.parametrize("kernel", [2, 4, 6])
def test_color_mask_rejects_even_kernels(kernel):
    """An even kernel would shift the mask (and the centroid) by a pixel."""
    with pytest.raises(ValueError, match="odd"):
        color_mask(to_hsv(blank_frame()), COMMAND_COLORS["green"], open_kernel_px=kernel)


@pytest.mark.parametrize("kernel", [3, 5, 7])
def test_odd_kernels_keep_a_card_in_place(kernel):
    image = blank_frame()
    draw_rect(image, 20, 20, 60, 50, color_bgr("green"))
    mask = color_mask(to_hsv(image), COMMAND_COLORS["green"], open_kernel_px=kernel)

    ys, xs = np.nonzero(mask)
    assert (xs.min(), xs.max(), ys.min(), ys.max()) == (20, 59, 20, 49)


def test_kernel_size_is_read_from_config_at_call_time(monkeypatch):
    import config

    image = blank_frame()
    draw_rect(image, 100, 100, 104, 104, color_bgr("green"))  # 4x4: survives 3x3, not 5x5
    assert ColorCounter(image)["green"] == 16
    monkeypatch.setattr(config, "MASK_OPEN_KERNEL_PX", 5)
    assert ColorCounter(image)["green"] == 0


def test_color_mask_rejects_a_color_with_no_ranges():
    with pytest.raises(ValueError):
        color_mask(to_hsv(blank_frame()), ())


# ---------------------------------------------------------------------------
# Input handling
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("shape", [(1, 1), (37, 53), (240, 320), (720, 1280)])
def test_any_frame_size_works(shape):
    height, width = shape
    image = blank_frame(height, width)
    area = draw_rect(image, 0, 0, width, height, color_bgr("red"))

    assert ColorCounter(image) == {"green": 0, "blue": 0, "red": area}


def test_non_contiguous_view_works():
    image = blank_frame()
    area = draw_rect(image, 0, 0, 100, 100, color_bgr("green"))
    flipped = image[:, ::-1]  # a view, not C-contiguous
    assert not flipped.flags["C_CONTIGUOUS"]

    assert ColorCounter(flipped)["green"] == area


def test_input_frame_is_not_modified():
    image = blank_frame()
    draw_rect(image, 10, 10, 200, 200, color_bgr("blue"))
    before = image.copy()

    ColorCounter(image)

    np.testing.assert_array_equal(image, before)


@pytest.mark.parametrize(
    "bad_image, error",
    [
        (np.zeros((10, 10), dtype=np.uint8), ValueError),          # grayscale
        (np.zeros((10, 10, 4), dtype=np.uint8), ValueError),       # BGRA
        (np.zeros((10, 10, 3), dtype=np.float32), ValueError),     # float: different hue scale
        (np.zeros((0, 10, 3), dtype=np.uint8), ValueError),        # empty
        ([[[0, 0, 0]]], TypeError),                                # not an array
        (None, TypeError),                                         # e.g. a failed cv2.imread
    ],
    ids=["grayscale", "4-channel", "float32", "empty", "list", "None"],
)
def test_invalid_frames_fail_loudly(bad_image, error):
    with pytest.raises(error):
        ColorCounter(bad_image)


# ---------------------------------------------------------------------------
# mask_centroid
# ---------------------------------------------------------------------------

def test_mask_centroid_of_empty_mask_is_none():
    assert mask_centroid(np.zeros((10, 10), dtype=np.uint8)) is None


def test_mask_centroid_matches_mean_of_nonzero_indices():
    rng = np.random.default_rng(7)
    mask = np.where(rng.random((IMAGE_HEIGHT, IMAGE_WIDTH)) > 0.7, 255, 0).astype(np.uint8)
    ys, xs = np.nonzero(mask)

    x, y = mask_centroid(mask)

    assert type(x) is float and type(y) is float
    assert x == pytest.approx(xs.mean(), abs=1e-6)
    assert y == pytest.approx(ys.mean(), abs=1e-6)
