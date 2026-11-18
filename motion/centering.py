"""Decide which way a target is from the image center.

Pure: no hardware, no state. GreenAction and BlueAction both use this, then
turn the answer into a rotation or a strafe.
"""

from __future__ import annotations

from typing import Literal

from config import CENTER_DEADBAND_PX, IMAGE_CENTER_X

CenteringCommand = Literal["left", "right", "centered"]


def centering_command(
    x: float,
    image_center_x: float = IMAGE_CENTER_X,
    deadband: float = CENTER_DEADBAND_PX,
) -> CenteringCommand:
    """Say whether the target at pixel column `x` is left of, right of, or at center.

    Let error = x - image_center_x. The target is "centered" when
    abs(error) <= deadband, so a target exactly on the deadband edge counts
    as centered (docs/task_contracts.md). Otherwise a positive error means
    the target is to the right.

    Args:
        x: the target's column in pixels (p_vector[0] from ColorLocator).
        image_center_x: the image's center column, default
            config.IMAGE_CENTER_X.
        deadband: half-width of the centered zone in pixels, default
            config.CENTER_DEADBAND_PX.

    Returns:
        "left", "right" or "centered".

    Raises:
        ValueError: if `deadband` is negative.
    """
    if deadband < 0:
        raise ValueError(f"deadband must be >= 0, got {deadband!r}")
    error = x - image_center_x
    if abs(error) <= deadband:
        return "centered"
    return "right" if error > 0 else "left"
