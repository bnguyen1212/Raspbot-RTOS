"""Unit tests for vision.color_counter.ColorCounter.

Uses static images from tests/sample_images/ (or synthetic numpy arrays) so
no camera or robot is required. Add sample images there before filling these
in, e.g. tests/sample_images/green_target.png.
"""

import os

import numpy as np
import pytest

from vision.color_counter import ColorCounter

SAMPLE_IMAGES_DIR = os.path.join(os.path.dirname(__file__), "sample_images")


def test_color_counter_returns_dict_of_counts():
    image = np.zeros((10, 10, 3), dtype=np.uint8)

    with pytest.raises(NotImplementedError):
        ColorCounter(image)
