"""Stop the motors when the process gets SIGINT, SIGTERM or SIGHUP.

Used by main.py and by the scripts in tools/. It's one shared implementation
because it's safety-critical. It imports nothing from the project, so
main.py --dry-run can use it without importing motion/.

Why not let KeyboardInterrupt unwind into a try/finally? Two reasons:

- SIGTERM (`kill`, systemd) and SIGHUP (the SSH session closing) don't raise
  anything by default: they end the process at once, so no `finally` runs and
  the wheels keep the last command they were sent (the board has no watchdog).
- Raspbot_Lib wraps every I2C write in a bare `except:`. Python runs a signal
  handler between bytecodes, which may be inside that `try`, so an exception
  raised by the handler (the default SIGINT handler raises KeyboardInterrupt)
  can be swallowed by the library.

So these handlers never raise. They stop the motors themselves and leave with
os._exit(), which can't be caught. The interrupted code never resumes, so it
can't send another wheel command after the stop.

A handler only runs once control is back in Python: a C call that blocks
(for example a camera read waiting on a frame) delays it until the call
returns. SIGKILL (`kill -9`) can't be handled at all; use
tools/emergency_stop.py.
"""

from __future__ import annotations

import os
import signal
import sys
from collections.abc import Callable
from types import FrameType
from typing import Final, Union

# Windows has no SIGHUP. That only matters for --dry-run on a laptop.
STOP_SIGNALS: Final[tuple[signal.Signals, ...]] = tuple(
    getattr(signal, name) for name in ("SIGINT", "SIGTERM", "SIGHUP") if hasattr(signal, name)
)

# What signal.signal() accepts and returns. None means the previous handler
# wasn't installed from Python.
Handler = Union[Callable[[int, Union[FrameType, None]], object], int, signal.Handlers, None]


def install_stop_handlers(
    stop: Callable[[], None],
    *,
    release: Callable[[], None] | None = None,
    write: Callable[[str], None] = print,
) -> dict[signal.Signals, Handler]:
    """On SIGINT, SIGTERM or SIGHUP: stop, release, then exit(128 + signum).

    The handler:

    1. ignores further stop signals, so a second Ctrl-C can't interrupt the stop,
    2. calls stop() (if it raises, the message says so and it still exits),
    3. calls release(), if given (errors are ignored: the process is exiting),
    4. writes a message (errors are ignored: after SIGHUP the terminal is gone
       and writing to it can raise EIO), and
    5. leaves with os._exit(128 + signum).

    Args:
        stop: stops the motors. Must be safe to call when they're already
            stopped, and at any point of the interrupted code.
        release: optional, frees other resources (main.py: the camera).
        write: where the exit message goes (default print).

    Returns:
        The previous handlers, for restore_handlers().
    """

    def handle(signum: int, frame: FrameType | None) -> None:
        for sig in STOP_SIGNALS:
            signal.signal(sig, signal.SIG_IGN)
        name = signal.Signals(signum).name
        try:
            stop()
            message = f"\n{name}: stop sent to the motors. Exiting."
        except BaseException as err:  # still exit, and say the stop failed
            message = (
                f"\n{name}: stop FAILED ({err!r}). "
                "Run python3 tools/emergency_stop.py now."
            )
        if release is not None:
            try:
                release()
            except BaseException:
                pass  # exiting anyway; the OS frees the device
        try:
            write(message)
            sys.stdout.flush()
            sys.stderr.flush()
        except BaseException:
            pass  # a dead terminal must not keep the process alive
        os._exit(128 + signum)

    return {sig: signal.signal(sig, handle) for sig in STOP_SIGNALS}


def restore_handlers(previous: dict[signal.Signals, Handler]) -> None:
    """Put back the handlers install_stop_handlers() returned.

    A previous handler of None (one not installed from Python) is restored
    as SIG_DFL, because signal.signal() doesn't accept None.
    """
    for sig, handler in previous.items():
        signal.signal(sig, signal.SIG_DFL if handler is None else handler)
