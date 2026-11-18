"""Entry point: run StartupAction() once, then the round-robin task loop.

main.py wires the real task functions into scheduler.loop.run_loop, which
holds the RASPBOT V2 control flow (as opposed to scheduler.loop.round_robin,
a generic reusable primitive). All data between tasks (frame, color_counts,
winning_color, p_vector, the red-turn state) is passed as arguments/return
values -- never through globals.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from config import IMAGE_HEIGHT, IMAGE_WIDTH, TRACKED_COLORS, Position, RedState
from scheduler.loop import run_loop
from vision.color_counter import ColorCounter
from vision.color_locator import ColorLocator
from motion.actions import StartupAction, IdleAction, GreenAction, BlueAction, RedAction

# Colors that dispatch straight to an action that takes p_vector. Red isn't in
# this table because it runs the stateful red-turn sequence (see scheduler.loop.run_loop). The
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
    # Red-turn sequence state. It's created once, here, and passed into the
    # loop. It only changes through RedAction's return value and the rearm rule.
    state: RedState = {"red_start": None, "red_rearm": True}

    run_loop(
        state,
        startup_action=StartupAction,
        capture_frame=capture_frame,
        color_counter=ColorCounter,
        color_locator=ColorLocator,
        idle_action=IdleAction,
        color_actions=COLOR_ACTIONS,
        red_action=RedAction,
    )


if __name__ == "__main__":
    main()
