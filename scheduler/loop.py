"""Round-robin cooperative scheduler and timing safety cutoff.

This is NOT real threading/multitasking. Each "task" is a plain function that
runs to completion and returns before the next task gets a turn. All state that
needs to survive between turns is passed explicitly as arguments/return values
by main.py's loop -- nothing here should read or write module-level globals.
"""

from __future__ import annotations

from collections.abc import Callable

from config import TIMEOUT_SECONDS


def TimerCheck(start_time: float, now: float) -> bool:
    """Safety cutoff check for the round-robin loop.

    This is a pure function: it doesn't read a clock. The caller passes both
    times, as time.monotonic() readings.

    Args:
        start_time: float, the time.monotonic() reading taken once, before the
            loop starts.
        now: float, a fresh time.monotonic() reading for this loop pass.

    Returns:
        bool: True when now - start_time > config.TIMEOUT_SECONDS (the caller
        must stop the loop), False otherwise.
    """
    raise NotImplementedError


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
    raise NotImplementedError
