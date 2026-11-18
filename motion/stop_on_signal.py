"""Stop the wheels when the process gets SIGINT, SIGTERM or SIGHUP.

Used by the scripts in tools/. It's one shared implementation because it's
safety-critical.

Why not just let KeyboardInterrupt unwind into a `with driver:` block?
Raspbot_Lib wraps every I2C write in a bare `except:`. Python runs a signal
handler between bytecodes, which may be inside that `try`. So an exception
raised by the handler (the default SIGINT handler raises KeyboardInterrupt)
can be swallowed by the library. These handlers never raise. They call stop()
themselves and leave with os._exit(), which can't be caught.

SIGKILL (`kill -9`) can't be handled at all. Use tools/emergency_stop.py.
"""

from __future__ import annotations

import os
import signal
import sys
from collections.abc import Callable
from types import FrameType
from typing import Final, Protocol

# Windows has no SIGHUP. That only matters for --dry-run on a laptop.
STOP_SIGNALS: Final[tuple[signal.Signals, ...]] = tuple(
    getattr(signal, name) for name in ("SIGINT", "SIGTERM", "SIGHUP") if hasattr(signal, name)
)


class Stoppable(Protocol):
    def stop(self) -> None: ...


def install_stop_handlers(driver: Stoppable, write: Callable[[str], None] = print) -> None:
    """On SIGINT, SIGTERM or SIGHUP: call driver.stop(), then exit(128 + signum).

    Further stop signals are ignored while it stops, so a second Ctrl-C can't
    interrupt the stop. If stop() raises, the handler says so and still exits.

    Args:
        driver: what to stop.
        write: where the exit message goes (default print).
    """

    def handle(signum: int, frame: FrameType | None) -> None:
        for sig in STOP_SIGNALS:
            signal.signal(sig, signal.SIG_IGN)
        name = signal.Signals(signum).name
        try:
            driver.stop()
            message = f"\n{name}: stop sent to all four motors. Exiting."
        except BaseException as err:  # still exit, and say the stop failed
            message = (
                f"\n{name}: stop() FAILED ({err!r}). "
                "Run python3 tools/emergency_stop.py now."
            )
        write(message)
        sys.stdout.flush()
        os._exit(128 + signum)

    for sig in STOP_SIGNALS:
        signal.signal(sig, handle)
