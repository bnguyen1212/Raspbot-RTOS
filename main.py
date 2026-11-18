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

Ctrl-C (SIGINT), `kill` (SIGTERM) and the SSH session closing (SIGHUP) all
stop the motors from a signal handler (scheduler.signals) and exit with
128 + the signal number. A timeout or an error stops them through
run_loop's finally block.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable
from typing import Any

from config import (
    CAMERA_BUFFER_SIZE,
    CAMERA_FLUSH_FRAMES,
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
from scheduler.signals import install_stop_handlers, restore_handlers
from vision.color_counter import ColorCounter
from vision.color_locator import ColorLocator


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
    from motion.actions import (
        BlueAction,
        GreenAction,
        IdleAction,
        RedAction,
        ShutdownAction,
        StartupAction,
    )

    return {
        "startup_action": StartupAction,
        "idle_action": IdleAction,
        "color_actions": {"green": GreenAction, "blue": BlueAction},
        "red_action": RedAction,
        "stop_motors": ShutdownAction,
    }


def report_camera(camera: Camera, index: int) -> None:
    """Print the frame size the camera delivers once, and warn on a mismatch.

    read() resizes every frame to IMAGE_WIDTH x IMAGE_HEIGHT anyway, but a
    different native size (especially another aspect ratio) changes pixel
    counts and positions, so the vision thresholds may need retuning.
    """
    width, height = camera.delivered_size()
    if (width, height) == (0, 0):
        print(f"Camera {index}: the backend doesn't report its frame size.")
        return
    print(f"Camera {index}: delivering {width}x{height}.")
    if (width, height) != (IMAGE_WIDTH, IMAGE_HEIGHT):
        print(
            f"WARNING: config.py expects {IMAGE_WIDTH}x{IMAGE_HEIGHT}, but camera {index} "
            f"delivers {width}x{height}. Frames are resized, so pixel counts and "
            "positions differ from the tuned values.",
            file=sys.stderr,
        )


def startup_then_flush(
    startup_action: Callable[[], None], flush_camera: Callable[[], None]
) -> Callable[[], None]:
    """Wrap startup_action so the camera is flushed right after it.

    run_loop calls the result as its startup_action, so the flush happens
    after the startup spin and before run_loop takes start_time: the first
    frame the loop processes is fresh, and the flush isn't counted against
    the timeout.
    """

    def startup() -> None:
        startup_action()
        flush_camera()

    return startup


def build_tasks(args: argparse.Namespace) -> dict[str, Any]:
    """Assemble every run_loop keyword argument for this run.

    Motion is picked before the frame source is opened, so a failing motion
    import can't leave a camera open.

    Args:
        args: the parsed command line (see parse_args).

    Returns:
        dict of keyword arguments for run_loop (everything except `state`).
        Its startup_action is the chosen startup action followed by a
        camera flush (see startup_then_flush).
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

    source: Camera | StaticImage
    if args.image:
        source = StaticImage(args.image, IMAGE_WIDTH, IMAGE_HEIGHT)
    else:
        source = Camera(args.camera, IMAGE_WIDTH, IMAGE_HEIGHT, buffer_size=CAMERA_BUFFER_SIZE)
        report_camera(source, args.camera)

    tasks.update(
        startup_action=startup_then_flush(
            tasks["startup_action"], lambda: source.flush(CAMERA_FLUSH_FRAMES)
        ),
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

    Exits the process with 128 + the signal number on SIGINT (130), SIGTERM
    or SIGHUP, after the signal handler has stopped the motors and released
    the camera.

    Raises:
        SystemExit: with code 130 if a KeyboardInterrupt still reaches here
            (see below), after the motors are stopped.
    """
    args = parse_args(argv)
    tasks = build_tasks(args)

    # Red-turn sequence state. It's created once, here, and passed into the
    # loop. It only changes through RedAction's return value and the rearm rule.
    state: RedState = {"red_start": None, "red_rearm": True}

    # Installed before the loop (and so before StartupAction drives the
    # wheels). The handler stops the motors itself and exits with os._exit,
    # so a signal can't be swallowed by Raspbot_Lib's bare `except:`, can't
    # cut run_loop's own stop short, and SIGTERM/SIGHUP no longer end the
    # process with the wheels still running.
    previous_handlers = install_stop_handlers(
        tasks["stop_motors"], release=tasks["release_camera"]
    )
    try:
        run_loop(state, **tasks)
    except KeyboardInterrupt:
        # With the handler installed, Ctrl-C doesn't raise KeyboardInterrupt.
        # This only catches one raised some other way. run_loop's finally
        # block has already stopped the motors and released the camera.
        print("Interrupted: motors stopped, camera released.", file=sys.stderr)
        raise SystemExit(130) from None
    finally:
        # The motors are stopped by now, so the defaults are safe again.
        restore_handlers(previous_handlers)
    print("Timeout reached: motors stopped, camera released.")


if __name__ == "__main__":
    main()
