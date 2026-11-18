"""Color pixel counting from a camera frame.

No hardware/camera calls belong in this module -- it must be testable against
static images loaded from tests/sample_images/ with nothing but numpy/OpenCV.
"""

from __future__ import annotations

import cv2
import numpy as np

from config import COMMAND_COLORS, TRACKED_COLORS
from vision.hsv_mask import color_mask, to_hsv


def ColorCounter(image: np.ndarray) -> dict[str, int]:
    """Count pixels of each tracked color in a camera frame.

    Convert the frame from BGR to HSV, build one mask for each HSV range in
    config.COMMAND_COLORS, and OR each color's masks together. That way a pixel
    is counted at most once per color, even for red, which has two ranges.
    Each color's mask is then opened (config.MASK_OPEN_KERNEL_PX) to drop
    speckle noise before counting. ColorLocator builds its mask with the same
    helper (vision.hsv_mask), so the two always agree on which pixels match.

    Args:
        image: numpy.ndarray, a BGR image frame (as returned by cv2.VideoCapture
            or cv2.imread), shape (H, W, 3), dtype uint8. Any size works.

    Returns:
        dict[str, int]: one entry for every name in config.TRACKED_COLORS. All
        keys are always present. Each value is the number of matching pixels
        (>= 0; 0 when the color is absent).

    Raises:
        TypeError / ValueError: if `image` isn't a non-empty (H, W, 3) uint8
            numpy array (see vision.hsv_mask.to_hsv).
    """
    hsv = to_hsv(image)  # converted once, shared by every color
    return {
        color: int(cv2.countNonZero(color_mask(hsv, COMMAND_COLORS[color])))
        for color in TRACKED_COLORS
    }
