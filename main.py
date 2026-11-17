"""Entry point: run StartupAction() once, then the round-robin task loop.

This is where the specific RASPBOT V2 control flow lives (as opposed to
scheduler.loop.round_robin, which is a generic reusable primitive). Every
task function is called directly here and all data between them (frame,
color_counts, winning_color, p_vector) is passed as local variables/return
values -- never through globals.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import numpy as np

from config import IMAGE_HEIGHT, IMAGE_WIDTH, TIMEOUT_SECONDS, TRACKED_COLORS, Position
from scheduler.loop import TimerCheck
from vision.color_counter import ColorCounter
from vision.color_locator import ColorLocator
from motion.actions import StartupAction, IdleAction, GreenAction, BlueAction, RedAction

# Maps each winning color name to the action that handles it. The keys must be
# exactly config.TRACKED_COLORS. This is checked at import, so adding or renaming
# a color without updating this table fails right away.
COLOR_ACTIONS: dict[str, Callable[[Position], None]] = {
    "green": GreenAction,
    "blue": BlueAction,
    "red": RedAction,
}
assert set(COLOR_ACTIONS) == set(TRACKED_COLORS), (
    "COLOR_ACTIONS keys must match config.TRACKED_COLORS"
)


def capture_frame() -> np.ndarray:
    """Grab a single frame from the robot's USB camera.

    Isolated here (rather than inlined in main()) so it's the one call in
    main.py that needs real camera hardware; everything downstream of it is
    testable with a static image instead.

    Returns:
        numpy.ndarray: a BGR image frame, shape (IMAGE_HEIGHT, IMAGE_WIDTH, 3),
        dtype uint8. If the camera delivers a different size, resize the frame
        before returning it, because downstream pixel coordinates assume this size.
    """
    raise NotImplementedError


def main() -> None:
    StartupAction()

    start_time = time.time()

    while True:
        if TimerCheck(start_time, TIMEOUT_SECONDS):
            break

        frame = capture_frame()
        color_counts = ColorCounter(frame)
        winning_color, p_vector = ColorLocator(color_counts, frame)

        if winning_color is None:
            IdleAction()
        elif winning_color in COLOR_ACTIONS:
            COLOR_ACTIONS[winning_color](p_vector)
        else:
            # Defensive fallback (intended behavior): a color name with no
            # action means the locator broke its contract. Don't move; idle
            # instead of crashing mid-run.
            IdleAction()


if __name__ == "__main__":
    main()
