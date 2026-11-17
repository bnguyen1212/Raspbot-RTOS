"""Entry point: run StartupAction() once, then the round-robin task loop.

This is where the specific RASPBOT V2 control flow lives (as opposed to
scheduler.loop.round_robin, which is a generic reusable primitive). Every
task function is called directly here, and all data between them (frame,
color_counts, winning_color, p_vector, the red-turn state) is passed as local
variables/return values -- never through globals.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import numpy as np

from config import IMAGE_HEIGHT, IMAGE_WIDTH, TRACKED_COLORS, Position, RedState
from scheduler.loop import TimerCheck
from vision.color_counter import ColorCounter
from vision.color_locator import ColorLocator
from motion.actions import StartupAction, IdleAction, GreenAction, BlueAction, RedAction

# Colors that dispatch straight to an action that takes p_vector. Red isn't in
# this table because it runs the stateful red-turn sequence (see main()). The
# table's keys plus "red" must be exactly config.TRACKED_COLORS. This is checked
# at import, so adding or renaming a color without updating this table fails
# right away.
COLOR_ACTIONS: dict[str, Callable[[Position], None]] = {
    "green": GreenAction,
    "blue": BlueAction,
}
assert set(COLOR_ACTIONS) | {"red"} == set(TRACKED_COLORS), (
    "COLOR_ACTIONS keys plus 'red' must match config.TRACKED_COLORS"
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

    # Red-turn sequence state. It's created once, here. It only changes through
    # RedAction's return value and the rearm rule below.
    state: RedState = {"red_start": None, "red_rearm": True}

    start_time = time.monotonic()

    while True:
        if TimerCheck(start_time, time.monotonic()):
            break

        # Vision runs on every pass, even mid-turn, because the rearm rule
        # needs the winning color.
        frame = capture_frame()
        color_counts = ColorCounter(frame)
        winning_color, p_vector = ColorLocator(color_counts, frame)

        # Rearm before dispatching. If a turn finishes on this pass, RedAction's
        # red_rearm = False then wins, so red can't start another turn until a
        # later frame shows something other than red.
        if winning_color != "red":
            state["red_rearm"] = True

        if state["red_start"] is not None:
            # A red turn is in progress: keep going until it finishes,
            # whatever vision says.
            state = RedAction(state, time.monotonic())
        elif winning_color == "red":
            if state["red_rearm"]:
                state = RedAction(state, time.monotonic())  # starts a new turn
            else:
                # Red is still in view right after a turn. Wait until it's rearmed.
                IdleAction()
        elif winning_color is None:
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
