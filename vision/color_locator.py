"""Locate the dominant tracked color's position from pixel counts.

No hardware/camera calls belong in this module -- it consumes only the dict
produced by vision.color_counter.ColorCounter, so it can be unit tested with
hand-built dicts (no image or robot required).
"""

from config import IDLE_SENTINEL, MIN_PIXEL_THRESHOLD, TRACKED_COLORS


def ColorLocator(color_counts):
    """Determine the 2D position of the dominant tracked color.

    Args:
        color_counts: dict[str, int], as returned by
            vision.color_counter.ColorCounter (every key in
            config.TRACKED_COLORS is present).

    Returns:
        tuple[float, float] | None:
          - config.IDLE_SENTINEL (None) if every count is below
            config.MIN_PIXEL_THRESHOLD.
          - Otherwise (x, y): the centroid of the dominant color in pixel
            coordinates, with the origin at the top-left,
            0 <= x < IMAGE_WIDTH and 0 <= y < IMAGE_HEIGHT.
        This function reports only where the color is, not which color it is.
        The caller works out the dominant color itself (see "Dominant color"
        in docs/task_contracts.md).

    Note:
        OPEN ISSUE: pixel counts carry no location, so the centroid can't be
        computed from color_counts alone. See docs/task_contracts.md.
    """
    raise NotImplementedError
