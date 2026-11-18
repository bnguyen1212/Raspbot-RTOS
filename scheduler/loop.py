"""Round-robin cooperative scheduler and timing safety cutoff.

This is NOT real threading/multitasking. Each "task" is a plain function that
runs to completion and returns before the next task gets a turn. All state that
needs to survive between turns is passed explicitly as arguments/return values
by run_loop -- nothing here should read or write module-level globals.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping

import numpy as np

from config import TIMEOUT_SECONDS, Position, RedState


def TimerCheck(start_time: float, now: float, *, timeout: float = TIMEOUT_SECONDS) -> bool:
    """Safety cutoff check for the round-robin loop.

    This is a pure function: it doesn't read a clock. The caller passes both
    times, as time.monotonic() readings.

    Args:
        start_time: float, the time.monotonic() reading taken once, before the
            loop starts.
        now: float, a fresh time.monotonic() reading for this loop pass.
        timeout: float, keyword-only, defaults to config.TIMEOUT_SECONDS.
            Only overridden by main.py's --timeout flag for quick test runs.

    Returns:
        bool: True when now - start_time > timeout (the caller must stop the
        loop), False otherwise.
    """

    if (now - start_time > timeout):
        return True
    else:
        return False
    


def round_robin(tasks: list[Callable[[], None]]) -> None:
    """Run a list of zero-argument task callables once each, in order.

    Generic cooperative-scheduling primitive: each task in `tasks` is invoked
    exactly once per call, in sequence, and must return promptly (no blocking
    waits) so the next task gets its turn. Intended as a building block if a
    module needs a plain round-robin pass separate from main.py's specific
    control flow.

    Args:
        tasks: list of no-argument callables.

    Returns:
        None
    """

    for task in tasks:
        task()

    return


def run_loop(
    state: RedState,
    *,
    startup_action: Callable[[], None],
    capture_frame: Callable[[], np.ndarray],
    color_counter: Callable[[np.ndarray], dict[str, int]],
    color_locator: Callable[
        [dict[str, int], np.ndarray], tuple[str, Position] | tuple[None, None]
    ],
    idle_action: Callable[[], None],
    color_actions: Mapping[str, Callable[[Position], None]],
    red_action: Callable[[RedState, float], RedState],
    stop_motors: Callable[[], None],
    release_camera: Callable[[], None],
    clock: Callable[[], float] = time.monotonic,
    timeout: float = TIMEOUT_SECONDS,
) -> None:
    """Run StartupAction once, then the round-robin task loop until timeout.

    However the run ends -- timeout, Ctrl-C (KeyboardInterrupt), or an
    exception from any task, StartupAction included -- stop_motors() and then
    release_camera() are called before this function returns or the exception
    propagates, so the robot is never left driving.

    The task functions are passed in rather than imported, so this module
    never imports vision/ or motion/, and the caller decides which
    implementations run.

    Args:
        state: RedState, the initial red-turn state, created by main().
        startup_action: StartupAction().
        capture_frame: zero-arg callable returning a BGR frame.
        color_counter: ColorCounter(image).
        color_locator: ColorLocator(color_counts, image).
        idle_action: IdleAction().
        color_actions: maps "green"/"blue" to GreenAction/BlueAction.
        red_action: RedAction(state, now).
        stop_motors: zero-arg callable that stops all wheels. Must be safe to
            call when they're already stopped.
        release_camera: zero-arg callable that frees the camera. Must be safe
            to call more than once.
        clock: zero-arg callable returning monotonic seconds; every time
            reading in the loop goes through it. main() passes time.monotonic;
            tests pass a fake clock so timeouts happen instantly.
        timeout: float, seconds before TimerCheck stops the loop. Defaults to
            config.TIMEOUT_SECONDS; main.py's --timeout overrides it.

    Returns:
        None
    """
    try:
        startup_action()

        start_time = clock()

        while True:
            if TimerCheck(start_time, clock(), timeout=timeout):
                break

            # Vision runs on every pass, even mid-turn, because the rearm rule
            # needs the winning color.
            frame = capture_frame()
            color_counts = color_counter(frame)
            winning_color, p_vector = color_locator(color_counts, frame)

            # Rearm before dispatching. If a turn finishes on this pass, RedAction's
            # red_rearm = False then wins, so red can't start another turn until a
            # later frame shows something other than red.
            if winning_color != "red":
                state["red_rearm"] = True

            if state["red_start"] is not None:
                # A red turn is in progress: keep going until it finishes,
                # whatever vision says.
                state = red_action(state, clock())
            elif winning_color == "red":
                if state["red_rearm"]:
                    state = red_action(state, clock())  # starts a new turn
                else:
                    # Red is still in view right after a turn. Wait until it's rearmed.
                    idle_action()
            elif winning_color is None:
                idle_action()
            elif winning_color in color_actions:
                color_actions[winning_color](p_vector)
            else:
                # Defensive fallback (intended behavior): a color name with no
                # action means the locator broke its contract. Don't move; idle
                # instead of crashing mid-run.
                idle_action()
    finally:
        # Motors first: they're the safety-critical step. The nested
        # try/finally makes sure the camera is still released even if
        # stopping the motors raises.
        try:
            stop_motors()
        finally:
            release_camera()
