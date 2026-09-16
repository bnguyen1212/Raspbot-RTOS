"""Entry point: run StartupAction() once, then the round-robin task loop.

This is where the specific RASPBOT V2 control flow lives (as opposed to
scheduler.loop.round_robin, which is a generic reusable primitive). Every
task function is called directly here and all data between them (frame,
color_counts, p_vector, dominant_color) is passed as local variables/return
values -- never through globals.
"""

import time

from scheduler.loop import TimerCheck
from vision.color_counter import ColorCounter
from vision.color_locator import ColorLocator, IDLE_POSITION
from motion.actions import StartupAction, IdleAction, GreenAction, BlueAction, RedAction

TIMEOUT_LIMIT_SECONDS = 120  # placeholder safety cutoff; tune per assignment spec


def capture_frame():
    """Grab a single frame from the robot's USB camera.

    Isolated here (rather than inlined in main()) so it's the one call in
    main.py that needs real camera hardware; everything downstream of it is
    testable with a static image instead.

    Returns:
        numpy.ndarray: a BGR image frame, shape (H, W, 3).
    """
    raise NotImplementedError


def main():
    StartupAction()

    start_time = time.time()

    while True:
        if TimerCheck(start_time, TIMEOUT_LIMIT_SECONDS):
            break

        frame = capture_frame()
        color_counts = ColorCounter(frame)
        p_vector = ColorLocator(color_counts)

        if p_vector is IDLE_POSITION:
            IdleAction()
        else:
            dominant_color = max(color_counts, key=color_counts.get)
            if dominant_color == "green":
                GreenAction(p_vector)
            elif dominant_color == "blue":
                BlueAction(p_vector)
            elif dominant_color == "red":
                RedAction(p_vector)
            else:
                IdleAction()


if __name__ == "__main__":
    main()
