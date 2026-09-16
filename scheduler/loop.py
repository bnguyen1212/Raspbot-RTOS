"""Round-robin cooperative scheduler and timing safety cutoff.

This is NOT real threading/multitasking. Each "task" is a plain function that
runs to completion and returns before the next task gets a turn. All state that
needs to survive between turns is passed explicitly as arguments/return values
by main.py's loop -- nothing here should read or write module-level globals.
"""

import time


def TimerCheck(start_time, timeout_limit):
    """Safety cutoff check for the round-robin loop.

    Args:
        start_time: float, the time.time() value captured when the run began.
        timeout_limit: float, maximum number of seconds the loop is allowed to run.

    Returns:
        bool: True if the elapsed time has exceeded timeout_limit (the caller
        should stop the loop), False otherwise.
    """
    raise NotImplementedError


def round_robin(tasks):
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
