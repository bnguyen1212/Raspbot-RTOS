"""Stand-in motion actions for --dry-run: print instead of driving motors.

main.py uses these instead of motion.actions in a dry run, so motion/ (and
the motor library it will import) is never loaded. Each method has the same
signature as the real action it replaces (see docs/task_contracts.md).

The loop runs many passes per second, so a line is printed only when the
action changes, not on every pass.
"""

from __future__ import annotations

from collections.abc import Callable

from config import SECONDS_PER_180, Position, RedState


class DryRunMotion:
    """Fake action set that prints what the robot would do.

    Args:
        log: callable that receives each output line (default: print).
            Tests pass list.append to capture the lines.
    """

    def __init__(self, log: Callable[[str], None] = print) -> None:
        self._log = log
        self._last: str | None = None

    def _say(self, key: str, message: str) -> None:
        """Print `message`, unless the previous action had the same `key`."""
        if key != self._last:
            self._log(f"[dry-run] {message}")
        self._last = key

    def startup_action(self) -> None:
        """StartupAction stand-in. Skips the 360-degree spin."""
        self._say("startup", "StartupAction: init + 360 spin (skipped)")

    def idle_action(self) -> None:
        """IdleAction stand-in."""
        self._say("idle", "IdleAction")

    def green_action(self, p_vector: Position) -> None:
        """GreenAction stand-in (the real one rotates toward the target)."""
        x, y = p_vector
        self._say("green", f"GreenAction p_vector=({x:.0f}, {y:.0f})")

    def blue_action(self, p_vector: Position) -> None:
        """BlueAction stand-in (the real one strafes toward the target)."""
        x, y = p_vector
        self._say("blue", f"BlueAction p_vector=({x:.0f}, {y:.0f})")

    def red_action(self, state: RedState, now: float) -> RedState:
        """RedAction stand-in: the contract's timing, without the motors.

        Follows the RedAction table in docs/task_contracts.md, so the
        scheduler's red-turn dispatch behaves the same as it will on the
        robot. Returns a new dict; `state` isn't modified.
        """
        if state["red_start"] is None:
            self._say("red-start", "RedAction: start 180 turn")
            return {**state, "red_start": now}
        if now - state["red_start"] < SECONDS_PER_180:
            self._last = "red-turning"  # still turning; nothing new to print
            return {**state}
        self._say("red-done", "RedAction: turn done, motors stopped")
        return {"red_start": None, "red_rearm": False}

    def stop_motors(self) -> None:
        """Shutdown stand-in. Always printed."""
        self._last = None
        self._say("stop", "stop_motors: motors stopped")
