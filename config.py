"""Shared constants for the whole project.

This is the single place these values live. scheduler/, vision/, motion/ and
main.py import from here and never hardcode them. docs/task_contracts.md
describes how each one is used.

config.py imports nothing from the project, so any module can import it without
creating a circular import.

Anything marked TODO is a placeholder that must be tuned or calibrated on the
real robot.
"""

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
COMMAND_COLORS = {
    "green": (
        ((35, 80, 50), (85, 255, 255)),
    ),
    "blue": (
        ((100, 120, 50), (130, 255, 255)),
    ),
    "red": (
        ((0, 120, 70), (10, 255, 255)),     # low end of the hue circle
        ((170, 120, 70), (179, 255, 255)),  # high end, wraps back to 0
    ),
}

# The tracked color names, in COMMAND_COLORS order: ("green", "blue", "red").
# The order matters: it's the tie-break order when two colors have the same
# pixel count (see "Dominant color" in docs/task_contracts.md).
TRACKED_COLORS = tuple(COMMAND_COLORS)

# A color whose pixel count is below this is "not detected".
# TODO: placeholder -- tune on the robot (640x480 = 307,200 pixels per frame).
MIN_PIXEL_THRESHOLD = 500

# ---------------------------------------------------------------------------
# Vision: frame geometry
# ---------------------------------------------------------------------------
# capture_frame() must return frames of exactly this size; all pixel
# coordinates below assume it.
IMAGE_WIDTH = 640
IMAGE_HEIGHT = 480
IMAGE_CENTER_X = IMAGE_WIDTH // 2  # 320

# Returned by ColorLocator when no tracked color is detected.
# None, not (-1, -1): a (-1, -1) tuple looks like a real position, so code that
# forgets to check for idle would quietly steer toward the left edge. With None,
# a missed check fails loudly (TypeError on p_vector[0]).
# Always compare with `is IDLE_SENTINEL`.
IDLE_SENTINEL = None

# A target counts as "centered" when |x - IMAGE_CENTER_X| <= this many pixels.
# TODO: placeholder -- tune on the robot.
CENTER_DEADBAND_PX = 40

# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------
# Safety cutoff: the main loop stops once this many seconds have elapsed.
TIMEOUT_SECONDS = 20.0

# ---------------------------------------------------------------------------
# Motion
# ---------------------------------------------------------------------------
# Wheel speed magnitudes, in the Yahboom motor library's speed units.
# TODO: placeholder -- confirm the library's range and tune on the robot.
ROTATE_SPEED = 50
STRAFE_SPEED = 50

# Open-loop rotation timing. There is no gyro, so turns are timed: these are the
# seconds a rotation at ROTATE_SPEED takes. SECONDS_PER_180 is calibrated on its
# own rather than derived as SECONDS_PER_360 / 2, because spin-up and spin-down
# make a short turn take more than half the time of a full one.
# TODO: placeholders -- calibrate both on the robot, at ROTATE_SPEED, on the
# actual floor surface. Recalibrate whenever ROTATE_SPEED changes.
SECONDS_PER_360 = 4.0
SECONDS_PER_180 = 2.0
