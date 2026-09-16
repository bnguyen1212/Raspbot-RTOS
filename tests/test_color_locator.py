"""Unit tests for vision.color_locator.ColorLocator.

Operates purely on hand-built color_counts dicts (as ColorCounter would
produce them), so no image or robot is required.
"""

import pytest

from vision.color_locator import ColorLocator, IDLE_POSITION


def test_color_locator_returns_idle_sentinel_when_no_colors_detected():
    color_counts = {"green": 0, "blue": 0, "red": 0}

    with pytest.raises(NotImplementedError):
        ColorLocator(color_counts)


def test_color_locator_returns_position_vector_for_dominant_color():
    color_counts = {"green": 500, "blue": 10, "red": 0}

    with pytest.raises(NotImplementedError):
        ColorLocator(color_counts)
