"""Entry point: run StartupAction() once, then the round-robin task loop.

    python main.py                                   # on the robot
    python main.py --dry-run                         # laptop webcam, no motors
    python main.py --dry-run --image path/to.png     # static image, no motors
    python main.py --dry-run --image path/to.png --timeout 3

main.py wires the task functions into scheduler.loop.run_loop, which holds
the RASPBOT V2 control flow (as opposed to scheduler.loop.round_robin, a
generic reusable primitive). All data between tasks (frame, color_counts,
winning_color, p_vector, the red-turn state) is passed as arguments/return
values -- never through globals.

In --dry-run, motion/ is never imported, so neither is the motor library.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable
from typing import Any

from config import (
    CAMERA_INDEX,
    IMAGE_HEIGHT,
    IMAGE_WIDTH,
    TIMEOUT_SECONDS,
    TRACKED_COLORS,
    Position,
    RedState,
)
from scheduler.camera import Camera, StaticImage
from scheduler.dry_run import DryRunMotion
from scheduler.loop import run_loop
from vision.color_counter import ColorCounter
from vision.color_locator import ColorLocator


def stop_motors() -> None:
    """Stop all wheels. Placeholder until motion/ provides a stop action.

    TODO: replace with the motion layer's stop action (e.g. a ShutdownAction()
    in motion/actions.py that calls mecanum.stop()). Agree on it with the
    motion owner -- see "Known gap" in docs/task_contracts.md.
    """
    raise NotImplementedError


def _positive_float(text: str) -> float:
    """argparse type for --timeout: a number greater than 0."""
    value = float(text)
    if value <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return value


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the command line.

    Args:
        argv: list[str] | None, the arguments without the program name.
            None means use sys.argv[1:].

    Returns:
        argparse.Namespace with dry_run, image, camera and timeout.
    """
    parser = argparse.ArgumentParser(description="RASPBOT V2 round-robin scheduler.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print motion commands instead of driving motors (no motor library needed)",
    )
    parser.add_argument(
        "--image",
        metavar="PATH",
        help="use this image as every frame instead of a live camera",
    )
    parser.add_argument(
        "--camera",
        type=int,
        default=CAMERA_INDEX,
        metavar="INDEX",
        help=f"camera device index (default: config.CAMERA_INDEX = {CAMERA_INDEX})",
    )
    parser.add_argument(
        "--timeout",
        type=_positive_float,
        default=TIMEOUT_SECONDS,
        metavar="SECONDS",
        help=f"safety cutoff (default: config.TIMEOUT_SECONDS = {TIMEOUT_SECONDS})",
    )
    return parser.parse_args(argv)


def motion_tasks(dry_run: bool) -> dict[str, Any]:
    """Pick the motion actions: printing fakes, or the real motion/ module.

    Args:
        dry_run: bool, True for the printing fakes in scheduler.dry_run.

    Returns:
        dict of run_loop keyword arguments: startup_action, idle_action,
        color_actions, red_action and stop_motors.
    """
    if dry_run:
        fake = DryRunMotion()
        return {
            "startup_action": fake.startup_action,
            "idle_action": fake.idle_action,
            "color_actions": {"green": fake.green_action, "blue": fake.blue_action},
            "red_action": fake.red_action,
            "stop_motors": fake.stop_motors,
        }

    # Imported here rather than at the top of the file, so a dry run never
    # loads motion/ (and, through it, the Yahboom motor library).
    from motion.actions import BlueAction, GreenAction, IdleAction, RedAction, StartupAction

    return {
        "startup_action": StartupAction,
        "idle_action": IdleAction,
        "color_actions": {"green": GreenAction, "blue": BlueAction},
        "red_action": RedAction,
        "stop_motors": stop_motors,
    }


def build_tasks(args: argparse.Namespace) -> dict[str, Any]:
    """Assemble every run_loop keyword argument for this run.

    Motion is picked before the frame source is opened, so a failing motion
    import can't leave a camera open.

    Args:
        args: the parsed command line (see parse_args).

    Returns:
        dict of keyword arguments for run_loop (everything except `state`).
    """
    tasks = motion_tasks(args.dry_run)

    # Colors that dispatch straight to an action taking p_vector. Red isn't in
    # the table because it runs the stateful red-turn sequence. The keys plus
    # "red" must be exactly config.TRACKED_COLORS, so adding or renaming a
    # color without wiring up its action fails right away.
    color_actions: dict[str, Callable[[Position], None]] = tasks["color_actions"]
    assert set(color_actions) | {"red"} == set(TRACKED_COLORS), (
        "color_actions keys plus 'red' must match config.TRACKED_COLORS"
    )

    if args.image:
        source = StaticImage(args.image, IMAGE_WIDTH, IMAGE_HEIGHT)
    else:
        source = Camera(args.camera, IMAGE_WIDTH, IMAGE_HEIGHT)

    tasks.update(
        capture_frame=source.read,
        release_camera=source.release,
        color_counter=ColorCounter,
        color_locator=ColorLocator,
        clock=time.monotonic,
        timeout=args.timeout,
    )
    return tasks


def main(argv: list[str] | None = None) -> None:
    """Run the robot (or a dry run) until the safety timeout.

    Args:
        argv: list[str] | None, command-line arguments (None: sys.argv[1:]).

    Raises:
        SystemExit: with code 130 on Ctrl-C, after the motors are stopped.
    """
    args = parse_args(argv)
    tasks = build_tasks(args)

    # Red-turn sequence state. It's created once, here, and passed into the
    # loop. It only changes through RedAction's return value and the rearm rule.
    state: RedState = {"red_start": None, "red_rearm": True}

    try:
        run_loop(state, **tasks)
    except KeyboardInterrupt:
        # run_loop's finally block has already stopped the motors and
        # released the camera by the time we get here.
        print("Interrupted: motors stopped, camera released.", file=sys.stderr)
        raise SystemExit(130) from None
    print("Timeout reached: motors stopped, camera released.")


if __name__ == "__main__":
    main()
