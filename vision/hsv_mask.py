"""Shared HSV masking used by both ColorCounter and ColorLocator.

ColorCounter decides how many pixels each color has, and ColorLocator then
finds where the winning color's pixels are. Both must agree on exactly which
pixels "match" a color, otherwise the locator could be asked to locate a color
whose mask it rebuilds differently (in the worst case, an empty mask). Keeping
the whole pipeline -- BGR to HSV, thresholding, OR-ing ranges, noise removal --
in this one module means the two can't drift apart.

No hardware/camera calls belong here. Every function is a pure function of its
arguments: no module-level state is read or written apart from the read-only
constants imported from config.py.
"""

from __future__ import annotations

from collections.abc import Sequence

import cv2
import numpy as np

import config
from config import HSVRange


def to_hsv(image: np.ndarray) -> np.ndarray:
    """Convert a BGR frame to OpenCV HSV (H 0-179, S 0-255, V 0-255).

    Args:
        image: numpy.ndarray, a non-empty BGR frame, shape (H, W, 3),
            dtype uint8.

    Returns:
        numpy.ndarray: the HSV frame, same shape, dtype uint8.

    Raises:
        TypeError: if `image` isn't a numpy array.
        ValueError: if it isn't a non-empty (H, W, 3) uint8 array. The dtype
            check matters: cv2.cvtColor silently accepts float images but then
            uses a different hue scale (0-360), which would make every
            threshold in config.COMMAND_COLORS wrong without any error.
    """
    if not isinstance(image, np.ndarray):
        raise TypeError(f"image must be a numpy.ndarray, got {type(image).__name__}")
    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError(f"image must have shape (H, W, 3), got {image.shape}")
    if image.dtype != np.uint8:
        raise ValueError(f"image must have dtype uint8, got {image.dtype}")
    if image.shape[0] == 0 or image.shape[1] == 0:
        raise ValueError(f"image must not be empty, got shape {image.shape}")
    return cv2.cvtColor(image, cv2.COLOR_BGR2HSV)


def color_mask(
    hsv: np.ndarray,
    ranges: Sequence[HSVRange],
    open_kernel_px: int | None = None,
) -> np.ndarray:
    """Binary mask of the pixels that fall in ANY of `ranges`.

    1. One cv2.inRange mask per (lower, upper) range (bounds inclusive).
    2. OR them together, so a pixel inside two overlapping ranges still counts
       once. This is how red's two hue ranges (both ends of the hue circle)
       become one mask.
    3. Morphological opening with an open_kernel_px x open_kernel_px square,
       which removes isolated speckles smaller than the kernel (sensor noise,
       stray reflections) while leaving solid regions such as a card intact.

    Args:
        hsv: numpy.ndarray, an HSV frame from to_hsv(), shape (H, W, 3).
        ranges: one or more (lower, upper) HSV ranges, e.g. one entry of
            config.COMMAND_COLORS.
        open_kernel_px: int | None, side of the opening kernel in pixels.
            Must be odd (or <= 1, which disables the opening). None, the
            default, means config.MASK_OPEN_KERNEL_PX, read at call time.

    Returns:
        numpy.ndarray: shape (H, W), dtype uint8, 255 where the pixel matches
        and 0 elsewhere.

    Raises:
        ValueError: if `ranges` is empty (that color could never match, which
            is almost certainly a config mistake), or if open_kernel_px is
            even and > 1. An even kernel has no center pixel, and OpenCV's
            opening then shifts the whole mask by one pixel down and right,
            which would bias every count and centroid.
    """
    if len(ranges) == 0:
        raise ValueError("a color needs at least one HSV range")
    if open_kernel_px is None:
        open_kernel_px = config.MASK_OPEN_KERNEL_PX
    if open_kernel_px > 1 and open_kernel_px % 2 == 0:
        raise ValueError(f"open_kernel_px must be odd (or <= 1 to disable), got {open_kernel_px}")

    mask = None
    for lower, upper in ranges:
        # np.uint8 arrays rather than tuples: a plain tuple is treated as a
        # cv2.Scalar, which works for 3 channels but hides shape mistakes.
        part = cv2.inRange(hsv, np.array(lower, dtype=np.uint8), np.array(upper, dtype=np.uint8))
        mask = part if mask is None else cv2.bitwise_or(mask, part)

    if open_kernel_px > 1:
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (open_kernel_px, open_kernel_px))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    return mask


def mask_centroid(mask: np.ndarray) -> tuple[float, float] | None:
    """Mean (x, y) position of the nonzero pixels in a binary mask.

    Same result as taking np.nonzero(mask) and averaging the column (x) and
    row (y) indices, but computed with image moments, which avoids building
    the large index arrays on every loop pass.

    Args:
        mask: numpy.ndarray, a binary mask from color_mask(), shape (H, W).

    Returns:
        (x, y) as plain Python floats, origin at the top-left, with
        0 <= x <= W - 1 and 0 <= y <= H - 1; or None if the mask is empty.
    """
    moments = cv2.moments(mask, binaryImage=True)
    area = moments["m00"]
    if area == 0:
        return None
    return float(moments["m10"] / area), float(moments["m01"] / area)
