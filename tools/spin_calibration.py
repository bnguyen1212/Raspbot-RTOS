#!/usr/bin/env python3
"""Spin-in-place calibration for SECONDS_PER_360 / SECONDS_PER_180.

    python3 tools/spin_calibration.py <seconds> [--direction left|right]
                                      [--speed X] [--repeat N] [--dry-run]

Spins the robot in place for <seconds>, then stops. Measure how far it turned
and adjust the times in config.py. --repeat N runs N trials, with a pause and
an Enter prompt before each one so you can reposition the robot and note the
result. It prints a CSV log of all trials at the end.

The rotation goes through motion.actions.timed_spin -> start_rotation ->
kinematics.rotate_in_place, the same path StartupAction and RedAction use,
with the same driver (motion.driver.default_driver()). Only the duration,
direction and speed come from the command line.

Ctrl-C, SIGTERM and SIGHUP stop the wheels and exit (motion.stop_on_signal).
Each spin also runs inside `with driver:`, so it ends with stop() however it
ends.

NOT VERIFIED: this has not been run on the robot.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

# Run as `python3 tools/spin_calibration.py`, Python puts tools/ (not the repo
# root) on sys.path. Add the repo root so `config` and `motion` can be imported.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config import MAX_SPEED, ROTATE_SPEED, SECONDS_PER_180, SECONDS_PER_360  # noqa: E402
from motion.actions import TIMED_TURN_DIRECTION, timed_spin  # noqa: E402
from motion.driver import FakeMotorDriver, MotorDriver, default_driver  # noqa: E402
from motion.kinematics import RotationDirection  # noqa: E402
from motion.mecanum import to_library_speed  # noqa: E402
from motion.stop_on_signal import install_stop_handlers  # noqa: E402

MAX_SECONDS = 30.0  # refuse longer spins, in case of a typo
SETTLE_S = 1.0      # pause after each stop so the robot comes to rest
DIRECTIONS: dict[str, RotationDirection] = {"left": "ccw", "right": "cw"}

Read = Callable[[str], str]
Write = Callable[[str], None]
Sleep = Callable[[float], None]
Clock = Callable[[], float]


class Settings(NamedTuple):
    seconds: float
    direction: str  # "left" or "right"
    speed: float
    repeat: int

    @property
    def rotation(self) -> RotationDirection:
        return DIRECTIONS[self.direction]


class Trial(NamedTuple):
    number: int
    seconds: float
    measured: float  # how long the wheels were commanded on
    direction: str
    speed: float
    note: str


class DryRunDriver(FakeMotorDriver):
    """FakeMotorDriver that prints each call."""

    def __init__(self, write: Write = print) -> None:
        super().__init__()
        self._write = write

    def set_wheels(
        self, front_left: float, front_right: float, rear_left: float, rear_right: float
    ) -> None:
        super().set_wheels(front_left, front_right, rear_left, rear_right)
        speeds = ", ".join(f"{s:+.2f}" for s in self.wheels)
        self._write(f"    [dry-run] set_wheels({speeds})")

    def stop(self) -> None:
        super().stop()
        self._write("    [dry-run] stop()")


def describe(settings: Settings) -> list[str]:
    """The settings, and warnings when they don't match what the actions use."""
    lines = [
        f"  duration   {settings.seconds:.3f} s per trial",
        f"  direction  {settings.direction} ({settings.rotation})",
        f"  speed      {settings.speed} (library {to_library_speed(settings.speed)}),"
        f" config.ROTATE_SPEED = {ROTATE_SPEED}, MAX_SPEED = {MAX_SPEED}",
        f"  trials     {settings.repeat}",
        "  path       motion.actions.timed_spin, the same rotation as StartupAction/RedAction",
        f"  config now SECONDS_PER_360 = {SECONDS_PER_360}, SECONDS_PER_180 = {SECONDS_PER_180}",
    ]
    if settings.rotation != TIMED_TURN_DIRECTION:
        lines.append(
            "  NOTE: StartupAction and RedAction turn right (cw). A left trial only\n"
            "        applies to them if left and right turns take the same time;\n"
            "        check with --direction right."
        )
    if settings.speed != ROTATE_SPEED:
        lines.append(
            f"  NOTE: speed {settings.speed} isn't config.ROTATE_SPEED ({ROTATE_SPEED}). The\n"
            "        actions use ROTATE_SPEED, so these timings only apply after you\n"
            "        set ROTATE_SPEED to this value."
        )
    lines.append(
        "  NOTE: RedAction's turn is checked once per loop pass, so it can overshoot\n"
        "        by up to one pass. Confirm SECONDS_PER_180 in the real loop too."
    )
    return lines


def ask(read: Read, prompt: str) -> str | None:
    """read(prompt), or None at the end of input (Ctrl-D or end of a pipe)."""
    try:
        return read(prompt)
    except EOFError:
        return None


def run_trials(
    driver: MotorDriver,
    settings: Settings,
    *,
    read: Read = input,
    write: Write = print,
    sleep: Sleep = time.sleep,
    clock: Clock = time.monotonic,
) -> list[Trial]:
    """Run up to settings.repeat trials, each started with Enter.

    Stops early if the user types anything at the start prompt, or input ends.

    Returns:
        The trials that ran, with their notes.
    """
    trials: list[Trial] = []
    for number in range(1, settings.repeat + 1):
        answer = ask(
            read,
            f"\nTrial {number}/{settings.repeat}: place the robot and mark its heading,\n"
            "then press Enter to spin (type anything else to quit): ",
        )
        if answer is None or answer.strip():
            write("Stopping here. Nothing more will move.")
            break

        spun: list[float] = []

        def timed_sleep(seconds: float) -> None:
            start = clock()
            try:
                sleep(seconds)
            finally:
                spun.append(clock() - start)

        write(f"Spinning {settings.direction} for {settings.seconds:.3f} s ...")
        with driver:  # stop() on the way out, whatever happens
            timed_spin(
                driver,
                settings.seconds,
                direction=settings.rotation,
                speed=settings.speed,
                sleep=timed_sleep,
            )
        write(f"Stopped. Settling for {SETTLE_S:.1f} s ...")
        sleep(SETTLE_S)
        write(
            f"Trial {number}: duration {settings.seconds:.3f} s requested, "
            f"{spun[0]:.3f} s measured (start command to stop command), "
            f"direction {settings.direction}, speed {settings.speed}"
        )
        note = ask(read, f"Result for trial {number} (e.g. degrees turned; Enter to skip): ")
        trials.append(
            Trial(
                number, settings.seconds, spun[0], settings.direction, settings.speed,
                (note or "").strip(),
            )
        )
        if note is None:
            break
    return trials


def csv_log(trials: list[Trial]) -> list[str]:
    lines = ["trial,seconds,measured_s,direction,speed,note"]
    for t in trials:
        note = t.note.replace(",", ";")
        lines.append(
            f"{t.number},{t.seconds:.3f},{t.measured:.3f},{t.direction},{t.speed},{note}"
        )
    return lines


def seconds_arg(text: str) -> float:
    value = float(text)
    if not 0 < value <= MAX_SECONDS:
        raise argparse.ArgumentTypeError(f"must be more than 0 and at most {MAX_SECONDS}")
    return value


def speed_arg(text: str) -> float:
    value = float(text)
    if not 0 < value <= MAX_SPEED:
        raise argparse.ArgumentTypeError(
            f"must be more than 0 and at most config.MAX_SPEED ({MAX_SPEED})"
        )
    return value


def repeat_arg(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Spin-in-place calibration for the RASPBOT V2.")
    parser.add_argument("seconds", type=seconds_arg, help=f"spin time per trial (max {MAX_SECONDS})")
    parser.add_argument("--direction", choices=sorted(DIRECTIONS), default="left")
    parser.add_argument(
        "--speed",
        type=speed_arg,
        default=ROTATE_SPEED,
        help=f"rotation speed (default config.ROTATE_SPEED = {ROTATE_SPEED}, max {MAX_SPEED})",
    )
    parser.add_argument("--repeat", type=repeat_arg, default=1, metavar="N", help="number of trials")
    parser.add_argument(
        "--dry-run", action="store_true", help="use FakeMotorDriver: print the calls, move nothing"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = Settings(args.seconds, args.direction, args.speed, args.repeat)
    try:
        driver: MotorDriver = DryRunDriver() if args.dry_run else default_driver()
    except ImportError as err:
        print(f"spin_calibration: cannot load the motor driver: {err}", file=sys.stderr)
        print("On a laptop, use --dry-run.", file=sys.stderr)
        return 1
    install_stop_handlers(driver)

    print("DRY RUN: FakeMotorDriver. Nothing will move." if args.dry_run
          else "REAL MOTORS. Clear space around the robot.")
    print("Spin calibration settings:")
    for line in describe(settings):
        print(line)
    print("Ctrl-C at any time stops the wheels and exits.")

    with driver:  # one final stop on the way out
        trials = run_trials(driver, settings)

    if trials:
        print("\nLog (CSV):")
        for line in csv_log(trials):
            print(line)
    print("Done: wheels stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
