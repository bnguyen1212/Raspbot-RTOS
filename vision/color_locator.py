"""Locate the dominant tracked color's position from pixel counts.

No hardware/camera calls belong in this module -- it consumes only the dict
produced by vision.color_counter.ColorCounter, so it can be unit tested with
hand-built dicts (no image or robot required).
"""

# Sentinel returned by ColorLocator when no tracked color is present in
# sufficient quantity to act on. main.py treats this as "go idle".
IDLE_POSITION = None


def ColorLocator(color_counts):
    """Determine the 2D position of the dominant tracked color.

    Args:
        color_counts: dict[str, int], per-color pixel counts as produced by
            vision.color_counter.ColorCounter (keys are color names, values
            are pixel counts).

    Returns:
        tuple[float, float] | None: an (x, y) position vector describing where
        the dominant color is in the frame (e.g. normalized offset from
        center), or IDLE_POSITION (None) if no color meets the detection
        threshold. Callers determine *which* color is dominant themselves
        (e.g. via max(color_counts, key=color_counts.get)) since this
        function only reports position, not identity.
    """
    raise NotImplementedError
