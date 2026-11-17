"""Unit tests for vision.color_locator.ColorLocator.

Uses hand-built color_counts dicts (as ColorCounter would produce them) plus a
synthetic frame, so no camera or robot is required.
"""

import numpy as np
import pytest

from config import IMAGE_HEIGHT, IMAGE_WIDTH
from vision.color_locator import ColorLocator


def _blank_frame():
    return np.zeros((IMAGE_HEIGHT, IMAGE_WIDTH, 3), dtype=np.uint8)


def test_color_locator_returns_idle_sentinel_when_no_colors_detected():
    color_counts = {"green": 0, "blue": 0, "red": 0}

    with pytest.raises(NotImplementedError):
        ColorLocator(color_counts, _blank_frame())


def test_color_locator_returns_winning_color_and_position():
    color_counts = {"green": 500, "blue": 10, "red": 0}

    with pytest.raises(NotImplementedError):
        ColorLocator(color_counts, _blank_frame())
