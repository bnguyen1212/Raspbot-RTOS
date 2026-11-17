"""Entry point: run StartupAction() once, then the round-robin task loop.

This is where the specific RASPBOT V2 control flow lives (as opposed to
scheduler.loop.round_robin, which is a generic reusable primitive). Every
task function is called directly here and all data between them (frame,
color_counts, p_vector, dominant_color) is passed as local variables/return
values -- never through globals.
"""

import time

from config import IDLE_SENTINEL, IMAGE_HEIGHT, IMAGE_WIDTH, TIMEOUT_SECONDS, TRACKED_COLORS
from scheduler.loop import TimerCheck
from vision.color_counter import ColorCounter
from vision.color_locator import ColorLocator
from motion.actions import StartupAction, IdleAction, GreenAction, BlueAction, RedAction

# Maps each dominant color name to the action that handles it. The keys must be
# exactly config.TRACKED_COLORS. This is checked at import, so adding or renaming
# a color without updating this table fails right away.
COLOR_ACTIONS = {
    "green": GreenAction,
    "blue": BlueAction,
    "red": RedAction,
}
assert set(COLOR_ACTIONS) == set(TRACKED_COLORS), (
    "COLOR_ACTIONS keys must match config.TRACKED_COLORS"
)


def capture_frame():
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


def main():
    StartupAction()

    start_time = time.time()

    while True:
        if TimerCheck(start_time, TIMEOUT_SECONDS):
            break

        frame = capture_frame()
        color_counts = ColorCounter(frame)
        p_vector = ColorLocator(color_counts)

        if p_vector is IDLE_SENTINEL:
            IdleAction()
        else:
            # On a tie, the color listed first in TRACKED_COLORS wins.
            dominant_color = max(TRACKED_COLORS, key=color_counts.__getitem__)
            COLOR_ACTIONS[dominant_color](p_vector)


if __name__ == "__main__":
    main()
