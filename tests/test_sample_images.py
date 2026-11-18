"""Vision pipeline on real photos from the robot's camera.

Every image in tests/sample_images/ whose filename starts with a tracked color
or "none" is a test case (see tests/sample_images/README.md):

    <expected>_<details>.<png|jpg|jpeg|bmp>

- <expected> is the color that must win ("green", "blue", "red"), or "none"
  for a frame where the robot must stay idle.
- If <details> contains the word "left", "center" or "right", the position is
  checked too, using the same centering rule as GreenAction/BlueAction
  (config.CENTER_DEADBAND_PX around config.IMAGE_CENTER_X).

Images are loaded through scheduler.camera.StaticImage, so they are resized to
the configured frame size exactly as `main.py --image` would feed them to the
loop (MIN_PIXEL_THRESHOLD assumes that size).

The tests skip themselves until photos are added.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from config import CENTER_DEADBAND_PX, IMAGE_CENTER_X, IMAGE_HEIGHT, IMAGE_WIDTH, TRACKED_COLORS
from scheduler.camera import StaticImage
from vision.color_counter import ColorCounter
from vision.color_locator import ColorLocator

SAMPLE_IMAGES_DIR = Path(__file__).resolve().parent / "sample_images"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp"}
NAME_PATTERN = re.compile(rf"^({'|'.join(TRACKED_COLORS)}|none)(_.*)?$", re.IGNORECASE)


def sample_images() -> list[Path]:
    """Every labeled sample image, sorted so test ids are stable."""
    if not SAMPLE_IMAGES_DIR.is_dir():
        return []
    return sorted(
        path
        for path in SAMPLE_IMAGES_DIR.iterdir()
        if path.suffix.lower() in IMAGE_SUFFIXES and is_sample_name(path.stem)
    )


def is_sample_name(stem: str) -> bool:
    """A labeled photo, and not tools/vision_debug.py output (<stem>_debug)."""
    return bool(NAME_PATTERN.match(stem)) and not stem.lower().endswith("_debug")


def expected_from_name(stem: str) -> tuple[str | None, str | None]:
    """(expected winning color or None, expected side or None) from a filename stem."""
    words = stem.lower().split("_")
    color = None if words[0] == "none" else words[0]
    sides = [word for word in words[1:] if word in ("left", "center", "right")]
    return color, (sides[0] if sides else None)


@pytest.mark.parametrize(
    "stem, expected",
    [
        ("green_center_near", ("green", "center")),
        ("Blue_left", ("blue", "left")),
        ("red", ("red", None)),
        ("none_empty_room", (None, None)),
        ("red_far_right_dim", ("red", "right")),
    ],
)
def test_filename_convention_is_parsed(stem, expected):
    assert is_sample_name(stem)
    assert expected_from_name(stem) == expected


@pytest.mark.parametrize(
    "stem", ["yellow_card", "greenish", "debug_green", "notes", "green_center_near_debug"]
)
def test_unlabeled_files_and_debug_output_are_ignored(stem):
    assert not is_sample_name(stem)


_IMAGES = sample_images()


@pytest.mark.skipif(not _IMAGES, reason="no labeled photos in tests/sample_images/ yet")
@pytest.mark.parametrize("path", _IMAGES, ids=[path.name for path in _IMAGES])
def test_sample_image_gives_the_expected_result(path):
    frame = StaticImage(str(path), IMAGE_WIDTH, IMAGE_HEIGHT).read()
    expected_color, expected_side = expected_from_name(path.stem)

    counts = ColorCounter(frame)
    winning_color, p_vector = ColorLocator(counts, frame)

    assert winning_color == expected_color, f"counts: {counts}"
    if expected_color is None:
        assert p_vector is None
        return

    x, _ = p_vector
    error = x - IMAGE_CENTER_X
    if expected_side == "center":
        assert abs(error) <= CENTER_DEADBAND_PX, f"x = {x:.1f}"
    elif expected_side == "left":
        assert error < -CENTER_DEADBAND_PX, f"x = {x:.1f}"
    elif expected_side == "right":
        assert error > CENTER_DEADBAND_PX, f"x = {x:.1f}"
