"""Color pixel counting from a camera frame.

No hardware/camera calls belong in this module -- it must be testable against
static images loaded from tests/sample_images/ with nothing but numpy/OpenCV.
"""

# Names of the colors this pipeline tracks. Kept here (not as a global mutable
# state) purely as a shared constant that vision/ and motion/ can both import.
TRACKED_COLORS = ("green", "blue", "red")


def ColorCounter(image):
    """Count pixels of each tracked color in a camera frame.

    Args:
        image: numpy.ndarray, a BGR image frame (as returned by cv2.VideoCapture
            or cv2.imread), shape (H, W, 3).

    Returns:
        dict[str, int]: mapping from color name (one of TRACKED_COLORS) to the
        number of pixels in `image` matching that color's threshold range.
    """
    raise NotImplementedError
