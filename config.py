"""Shared constants for the whole project.

This is the single place these values live. scheduler/, vision/, motion/ and
main.py import from here and never hardcode them. docs/task_contracts.md
describes how each one is used.

config.py imports nothing from the project, so any module can import it without
creating a circular import.

Anything marked TODO is a placeholder that must be tuned or calibrated on the
real robot.
"""

from __future__ import annotations

from typing import TypedDict

# ---------------------------------------------------------------------------
# Shared types (for annotations; see docs/task_contracts.md)
# ---------------------------------------------------------------------------
HSV = tuple[int, int, int]      # (H, S, V) on OpenCV's scale
HSVRange = tuple[HSV, HSV]      # (lower, upper), both inclusive
Position = tuple[float, float]  # (x, y) in pixels, origin top-left


class RedState(TypedDict):
    """State of the red-turn sequence. It's a plain dict at runtime.

    main.main() creates it once, as {"red_start": None, "red_rearm": True}.
    See "Red-turn sequence" in docs/task_contracts.md.
    """

    red_start: float | None  # time.monotonic() when the current turn began; None = no turn running
    red_rearm: bool          # True = seeing red may start a new turn

# ---------------------------------------------------------------------------
# Vision: color thresholds
# ---------------------------------------------------------------------------
# OpenCV HSV scale: H 0-179, S 0-255, V 0-255.
#
# Each color maps to a tuple of one or more (lower, upper) HSV ranges. Bounds are
# inclusive (cv2.inRange semantics). A pixel counts toward a color if it falls
# inside ANY of that color's ranges. Red needs two ranges because its hue wraps
# around 0/180.
#
# TODO: placeholder values -- tune on the robot under real lighting.
COMMAND_COLORS: dict[str, tuple[HSVRange, ...]] = {
    "green": (
        ((35, 80, 50), (85, 255, 255)),
    ),
    "blue": (
        ((100, 120, 50), (130, 255, 255)),
    ),
    "red": (
        # S >= 160 (was 120): shaded skin reaches H 8-12 with S up to ~180, and
        # at S >= 120 an arm or face in view alone counted up to ~2,700 "red"
        # pixels. At 160, skin stayed under ~300 px in webcam tests while a red
        # screen kept >= 7,000 px. Recheck with the robot camera and real cards.
        ((0, 160, 70), (10, 255, 255)),     # low end of the hue circle
        ((170, 160, 70), (179, 255, 255)),  # high end, wraps back to 0
    ),
}

# The tracked color names, in COMMAND_COLORS order: ("green", "blue", "red").
# The order matters: it's the tie-break order when two colors have the same
# pixel count (see "Dominant color" in docs/task_contracts.md).
TRACKED_COLORS = tuple(COMMAND_COLORS)

# Noise removal: each color's mask gets a morphological opening with a square
# kernel this many pixels wide before pixels are counted or located. It
# removes isolated specks smaller than the kernel (sensor noise, stray
# reflections) and leaves solid regions like a card intact. Must be odd: an even
# kernel shifts the mask by a pixel. 1 (or 0) turns it off.
# TODO: placeholder -- tune on the robot.
MASK_OPEN_KERNEL_PX = 3

# A color whose pixel count is below this is "not detected".
# 1,500 (was 500) is ~0.5% of the frame: about 5x the stray skin/background
# pixels seen in webcam tests, and well under a phone-sized target at arm's
# length (~7,000 px). The real cards are larger, so this leaves room.
# TODO: placeholder -- tune on the robot (640x480 = 307,200 pixels per frame).
MIN_PIXEL_THRESHOLD = 1500

# ---------------------------------------------------------------------------
# Vision: frame geometry
# ---------------------------------------------------------------------------
# capture_frame() must return frames of exactly this size; all pixel
# coordinates below assume it.
IMAGE_WIDTH = 640
IMAGE_HEIGHT = 480
IMAGE_CENTER_X = IMAGE_WIDTH // 2  # 320

# cv2.VideoCapture device index for the USB camera (scheduler.camera.Camera).
# 0 is usually the built-in webcam on a laptop. main.py --camera overrides it.
# TODO: confirm the robot's index during integration (`v4l2-ctl --list-devices`).
CAMERA_INDEX = 0

# How many frames the camera driver may queue (cv2.CAP_PROP_BUFFERSIZE). With
# 1, each read returns the newest frame instead of one that waited in the
# queue while the loop was busy. That keeps the robot from acting on old
# images, but it can lower the loop rate, because each read may wait for the
# next frame. Not every backend honors it (V4L2 does). main.py passes it to
# scheduler.camera.Camera.
# TODO: confirm on the robot. If the loop rate drops noticeably, try 2.
CAMERA_BUFFER_SIZE = 1

# Frames Camera.flush() throws away after StartupAction's spin and before the
# loop's start_time, so the first frames the loop sees are fresh and taken
# with auto-exposure and white balance already settled. Matches the flush in
# tools/capture_samples.py. Costs about half a second at 30 fps, which isn't
# counted against TIMEOUT_SECONDS.
# TODO: confirm on the robot.
CAMERA_FLUSH_FRAMES = 15

# What ColorLocator returns when no tracked color is detected. It has the same
# (winning_color, position) shape as a detection, so callers can always unpack
# `winning_color, p_vector = ColorLocator(...)`.
# Check for idle with `winning_color is None` (or `== IDLE_SENTINEL`). Never use
# `is IDLE_SENTINEL`, because two equal tuples aren't guaranteed to be the same
# object.
# The position is None rather than a fake value such as (-1, -1). A fake
# position would quietly steer the robot toward the left edge if someone forgot
# the idle check; None makes that mistake fail with a TypeError on p_vector[0].
IDLE_SENTINEL: tuple[None, None] = (None, None)

# A target counts as "centered" when |x - IMAGE_CENTER_X| <= this many pixels.
# TODO: placeholder -- tune on the robot.
CENTER_DEADBAND_PX = 210

# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------
# Safety cutoff: TimerCheck returns True once more than this many seconds have
# passed, measured with time.monotonic(), and the main loop then stops.
TIMEOUT_SECONDS = 30.0

# ---------------------------------------------------------------------------
# Motion
# ---------------------------------------------------------------------------
# Wheel speeds are normalized: -1.0 is full speed backward, 1.0 full speed
# forward. motion.mecanum converts them to the library's -255..255.
#
# MAX_SPEED is the safety cap: motion.mecanum clamps every wheel speed to
# +/-MAX_SPEED before sending it, whatever the caller asked for.
# TODO: placeholder -- raise it only after the robot has been tested at this cap.
MAX_SPEED = 0.4

# Wheel speed magnitudes for rotating and strafing, in the same normalized units.
# TODO: placeholder -- tune on the robot.
ROTATE_SPEED = 0.2
STRAFE_SPEED = 0.2

assert 0 < MAX_SPEED <= 1.0, "MAX_SPEED must be in (0, 1.0]"
assert 0 < ROTATE_SPEED <= MAX_SPEED, "ROTATE_SPEED must be in (0, MAX_SPEED]"
assert 0 < STRAFE_SPEED <= MAX_SPEED, "STRAFE_SPEED must be in (0, MAX_SPEED]"

# Open-loop rotation timing. There is no gyro, so turns are timed: these are the
# seconds a rotation at ROTATE_SPEED takes. SECONDS_PER_180 is calibrated on its
# own rather than derived as SECONDS_PER_360 / 2, because spin-up and spin-down
# make a short turn take more than half the time of a full one.
#
# SECONDS_PER_360 times StartupAction's blocking spin.
# SECONDS_PER_180 times RedAction's non-blocking turn. That turn is checked once
# per loop pass, so it can overshoot by up to one pass. Calibrate it by running
# the real loop, not by timing an isolated spin.
#
# TODO: placeholders -- calibrate both on the robot, at ROTATE_SPEED, on the
# actual floor surface. Recalibrate whenever ROTATE_SPEED changes.
SECONDS_PER_360 = 1.85
SECONDS_PER_180 = 0.8
