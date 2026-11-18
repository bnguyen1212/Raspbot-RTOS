#!/usr/bin/env python3
"""Interactive motion test for the RASPBOT V2, run over SSH on the robot.

    python3 tools/motion_test.py                 # real motors
    python3 tools/motion_test.py --duration 1.0  # shorter movements
    python3 tools/motion_test.py --dry-run       # FakeMotorDriver, nothing moves

A numbered menu runs ONE movement at a time, at low speed, for a short fixed
time. Before anything moves, it says what it's about to do and waits for
Enter. Every movement runs inside the driver's context manager, so it ends
with stop() however it ends, even on an exception.

Ctrl-C, `kill <pid>` (SIGTERM) and closing the SSH session (SIGHUP) all call
stop() straight from a signal handler and then exit. That's because
Raspbot_Lib's bare `except:` can swallow a KeyboardInterrupt that arrives
during a motor write. `kill -9` (SIGKILL) can't be caught, so nothing can
stop the wheels then. Use tools/emergency_stop.py.

Uses the real driver (motion.mecanum.RaspbotMotorDriver) and the
motion.kinematics helpers. NOT VERIFIED: this has not been run on the robot.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import NamedTuple, Protocol

# Run as `python3 tools/motion_test.py`, Python puts tools/ (not the repo root)
# on sys.path. Add the repo root so `config` and `motion` can be imported.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config import MAX_SPEED, ROTATE_SPEED, STRAFE_SPEED  # noqa: E402
from motion.driver import FakeMotorDriver  # noqa: E402
from motion.kinematics import WheelSpeeds, rotate_in_place, strafe, wheel_speeds  # noqa: E402
from motion.mecanum import to_library_speed  # noqa: E402
from scheduler.signals import install_stop_handlers  # noqa: E402

DEFAULT_DURATION_S = 1.5
MAX_DURATION_S = 5.0  # refuse longer --duration values, in case of a typo
SINGLE_WHEEL_S = 1.0
# Forward/backward and single-wheel tests have no speed of their own in
# config.py, so they use the lower of the two configured speeds.
LOW_SPEED = min(ROTATE_SPEED, STRAFE_SPEED)

Read = Callable[[str], str]
Write = Callable[[str], None]
Sleep = Callable[[float], None]


class DiagnosticDriver(Protocol):
    """What this script needs from a driver."""

    def set_wheels(
        self, front_left: float, front_right: float, rear_left: float, rear_right: float
    ) -> None: ...

    def set_motor_raw(self, motor_id: int, speed: float) -> None: ...

    def stop(self) -> None: ...

    def __enter__(self) -> DiagnosticDriver: ...

    def __exit__(self, *exc_info: object) -> None: ...


class DryRunDriver(FakeMotorDriver):
    """FakeMotorDriver that prints each call and adds set_motor_raw."""

    def __init__(self, write: Write = print) -> None:
        super().__init__()
        self._write = write

    def set_wheels(
        self, front_left: float, front_right: float, rear_left: float, rear_right: float
    ) -> None:
        super().set_wheels(front_left, front_right, rear_left, rear_right)
        self._write(f"    [dry-run] set_wheels{format_speeds(self.wheels)}")

    def set_motor_raw(self, motor_id: int, speed: float) -> None:
        self.calls.append(("set_motor_raw", (motor_id, speed)))
        self._write(f"    [dry-run] set_motor_raw({motor_id}, {speed:+.2f})")

    def stop(self) -> None:
        super().stop()
        self._write("    [dry-run] stop()")


class Movement(NamedTuple):
    label: str
    speeds: WheelSpeeds


def movements() -> dict[str, Movement]:
    """The whole-robot movements, keyed by menu number."""
    return {
        "1": Movement("rotate left (counterclockwise)", rotate_in_place("ccw", ROTATE_SPEED)),
        "2": Movement("rotate right (clockwise)", rotate_in_place("cw", ROTATE_SPEED)),
        "3": Movement("strafe left", strafe("left", STRAFE_SPEED)),
        "4": Movement("strafe right", strafe("right", STRAFE_SPEED)),
        "5": Movement("forward", wheel_speeds(LOW_SPEED, 0, 0)),
        "6": Movement("backward", wheel_speeds(-LOW_SPEED, 0, 0)),
    }


MENU = """
  1  rotate left           5  forward
  2  rotate right          6  backward
  3  strafe left           7  stop all wheels
  4  strafe right
  8  single wheel: spin one motor ID for {single:.1f} s
  9  hold test: spin one motor ID until you press Enter
  q  quit"""


def format_speeds(speeds: Sequence[float]) -> str:
    return "(" + ", ".join(f"{s:+.2f}" for s in speeds) + ")"


def check_speed(speeds: Sequence[float]) -> None:
    """Refuse anything above MAX_SPEED (the driver would clamp it anyway)."""
    fastest = max(abs(s) for s in speeds)
    if fastest > MAX_SPEED:
        raise ValueError(f"speed {fastest} is above MAX_SPEED {MAX_SPEED}; refusing")


def confirm(read: Read, write: Write, plan: str) -> bool:
    """Print what's about to happen. Only a bare Enter means go."""
    write(f"\nAbout to: {plan}")
    answer = read("Press Enter to run it (type anything else to cancel): ")
    if answer.strip():
        write("Cancelled. Nothing moved.")
        return False
    return True


def run_movement(
    driver: DiagnosticDriver, move: Movement, duration: float, read: Read, write: Write, sleep: Sleep
) -> None:
    check_speed(move.speeds)
    library = "(" + ", ".join(f"{to_library_speed(s):+d}" for s in move.speeds) + ")"
    plan = (
        f"{move.label} for {duration:.1f} s\n"
        f"  wheel speeds (fl, fr, rl, rr) = {format_speeds(move.speeds)}"
        f"  ~ library {library}"
    )
    if not confirm(read, write, plan):
        return
    with driver:  # stop() on the way out, whatever happens
        driver.set_wheels(*move.speeds)
        sleep(duration)
    write("Done: wheels stopped.")


def ask_motor(read: Read, write: Write) -> tuple[int, int] | None:
    """Ask for a motor ID and a direction. Returns (motor_id, +1 or -1), or None."""
    motor = read("Motor ID (0-3): ").strip()
    if motor not in ("0", "1", "2", "3"):
        write(f"{motor!r} isn't a motor ID 0-3. Back to the menu.")
        return None
    direction = read("Direction: f = library forward, b = library backward: ").strip().lower()
    if direction not in ("f", "b"):
        write(f"{direction!r} isn't f or b. Back to the menu.")
        return None
    return int(motor), (1 if direction == "f" else -1)


def describe_raw(motor_id: int, sign: int, how_long: str) -> str:
    speed = sign * LOW_SPEED
    word = "forward" if sign > 0 else "backward"
    return (
        f"spin motor ID {motor_id} library-{word} at {speed:+.2f} {how_long}\n"
        f"  Ctrl_Muto({motor_id}, {to_library_speed(speed):+d}), bypassing the wiring block"
    )


def run_single_wheel(driver: DiagnosticDriver, read: Read, write: Write, sleep: Sleep) -> None:
    choice = ask_motor(read, write)
    if choice is None:
        return
    motor_id, sign = choice
    if not confirm(read, write, describe_raw(motor_id, sign, f"for {SINGLE_WHEEL_S:.1f} s")):
        return
    with driver:
        driver.set_motor_raw(motor_id, sign * LOW_SPEED)
        sleep(SINGLE_WHEEL_S)
    write(
        "Done: wheels stopped. Note which physical wheel turned and whether that\n"
        "direction would push the robot forward. Then update the VERIFY ON ROBOT\n"
        "block in motion/mecanum.py."
    )


def run_hold_test(driver: DiagnosticDriver, read: Read, write: Write) -> None:
    choice = ask_motor(read, write)
    if choice is None:
        return
    motor_id, sign = choice
    if not confirm(read, write, describe_raw(motor_id, sign, "and KEEP it spinning")):
        return
    pid = os.getpid()
    with driver:
        driver.set_motor_raw(motor_id, sign * LOW_SPEED)
        write(
            f"\nMotor {motor_id} is spinning. This script's PID is {pid}.\n"
            "From a second SSH session, try one of:\n"
            f"  kill -9 {pid}\n"
            "      SIGKILL simulates a crash: no cleanup can run. If the wheel keeps\n"
            "      spinning, the board holds its last command. Stop it with:\n"
            "      python3 tools/emergency_stop.py\n"
            f"  kill {pid}\n"
            "      SIGTERM tests this script's signal handler, which should stop\n"
            "      the wheel and exit."
        )
        read("Press Enter here to stop the wheel and go back to the menu: ")
    write("Done: wheels stopped.")


def run_menu(
    driver: DiagnosticDriver,
    *,
    duration: float = DEFAULT_DURATION_S,
    read: Read = input,
    write: Write = print,
    sleep: Sleep = time.sleep,
) -> None:
    """Show the menu until the user quits (q or end of input)."""
    moves = movements()
    while True:
        write(MENU.format(single=SINGLE_WHEEL_S))
        try:
            choice = read("> ").strip().lower()
            if choice in moves:
                run_movement(driver, moves[choice], duration, read, write, sleep)
            elif choice == "7":
                driver.stop()  # no confirmation: stopping is never delayed
                write("Stop sent to all four motors.")
            elif choice == "8":
                run_single_wheel(driver, read, write, sleep)
            elif choice == "9":
                run_hold_test(driver, read, write)
            elif choice in ("q", "quit", "exit"):
                return
            elif choice:
                write(f"Unknown choice {choice!r}.")
        except EOFError:  # Ctrl-D, or the end of piped input
            write("")
            return


def positive_duration(text: str) -> float:
    value = float(text)
    if not 0 < value <= MAX_DURATION_S:
        raise argparse.ArgumentTypeError(f"must be more than 0 and at most {MAX_DURATION_S}")
    return value


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Interactive RASPBOT V2 motion test.")
    parser.add_argument(
        "--duration",
        type=positive_duration,
        default=DEFAULT_DURATION_S,
        metavar="SECONDS",
        help=f"length of each menu movement 1-6 (default {DEFAULT_DURATION_S}, max {MAX_DURATION_S})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="use FakeMotorDriver: print the calls, move nothing",
    )
    return parser.parse_args(argv)


def make_driver(dry_run: bool) -> DiagnosticDriver:
    if dry_run:
        return DryRunDriver()
    from motion.mecanum import RaspbotMotorDriver  # imports Raspbot_Lib lazily

    return RaspbotMotorDriver()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        driver = make_driver(args.dry_run)
    except ImportError as err:
        print(f"motion_test: cannot load the motor driver: {err}", file=sys.stderr)
        print("On a laptop, use --dry-run.", file=sys.stderr)
        return 1
    install_stop_handlers(driver.stop)

    if args.dry_run:
        print("DRY RUN: FakeMotorDriver. Nothing will move.")
    else:
        print("REAL MOTORS. Keep the wheels off the ground for the first tests.")
    print(
        f"Speeds: rotate {ROTATE_SPEED}, strafe {STRAFE_SPEED}, other {LOW_SPEED} "
        f"(MAX_SPEED {MAX_SPEED}). Movements last {args.duration} s.\n"
        "Ctrl-C at any time stops all wheels and exits.\n"
        "Tip: use 8 (single wheel) first. Menu 1-6 rely on the unverified wiring block."
    )
    with driver:  # one final stop on the way out
        run_menu(driver, duration=args.duration)
    print("Bye: wheels stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
