"""Pick the winning tracked color and locate it in the frame.

No hardware/camera calls belong in this module. It works only on the
color_counts dict from ColorCounter and on the same frame ColorCounter saw, so
it can be unit tested with static images (no robot required).
"""

from __future__ import annotations

import numpy as np

from config import COMMAND_COLORS, IDLE_SENTINEL, MIN_PIXEL_THRESHOLD, TRACKED_COLORS, Position


def ColorLocator(
    color_counts: dict[str, int], image: np.ndarray
) -> tuple[str, Position] | tuple[None, None]:
    """Pick the winning color from the counts, then find where it is in `image`.

    1. Winning color: max(TRACKED_COLORS, key=color_counts.__getitem__).
       On a tie, the color listed first in TRACKED_COLORS wins.
    2. If the winner's count is below MIN_PIXEL_THRESHOLD, return
       IDLE_SENTINEL.
    3. Otherwise, recompute ONLY the winning color's mask from `image`
       (convert BGR to HSV, then OR together that color's
       config.COMMAND_COLORS ranges), and return the centroid of that mask.
       Don't rebuild masks for the other colors.

    Args:
        color_counts: dict[str, int], as returned by
            vision.color_counter.ColorCounter (every key in
            config.TRACKED_COLORS is present).
        image: numpy.ndarray, the same BGR frame that was passed to
            ColorCounter, shape (H, W, 3), dtype uint8.

    Returns:
        tuple[str, Position] | tuple[None, None]:
          - (winning_color, (x, y)): winning_color is one of TRACKED_COLORS,
            and (x, y) is the centroid of its mask in pixel coordinates, with
            the origin at the top-left, 0 <= x < W and 0 <= y < H.
          - IDLE_SENTINEL, i.e. (None, None), if no color reaches
            MIN_PIXEL_THRESHOLD.
    """
    raise NotImplementedError
