"""Frame sources: the one place the loop gets camera frames from.

Two interchangeable sources with the same small interface:

- `Camera`: a live cv2.VideoCapture device (the robot's USB camera, or a
  laptop webcam during --dry-run).
- `StaticImage`: one image file, returned as every frame (--image PATH).

Both have:
- `read()` -> a BGR frame, shape (height, width, 3), dtype uint8
- `flush(frames)` -> throws away stale frames (a no-op for StaticImage)
- `release()` -> frees the source; safe to call more than once

main.py passes a source's bound `read` method to run_loop as capture_frame,
and its `release` method as release_camera. The open device lives on the
object, which is how capture_frame can take no arguments without a global.
"""

from __future__ import annotations

import sys

import cv2
import numpy as np


def _backend() -> tuple[int, str]:
    """The cv2.VideoCapture backend to open cameras with, and its name.

    V4L2 on Linux (the robot), so the backend doesn't depend on how OpenCV was
    built (an OpenCV with GStreamer may otherwise pick it). Anywhere else
    (a laptop dry run), OpenCV's default.
    """
    if sys.platform.startswith("linux"):
        return cv2.CAP_V4L2, "V4L2"
    return cv2.CAP_ANY, "default backend"


def _fit(frame: np.ndarray, width: int, height: int) -> np.ndarray:
    """Return `frame` resized to (height, width), or unchanged if it already is."""
    if frame.shape[:2] != (height, width):
        frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
    return frame


class Camera:
    """A live camera opened with cv2.VideoCapture.

    Opened with V4L2 on Linux, OpenCV's default backend elsewhere.

    Args:
        index: int, the VideoCapture device index (config.CAMERA_INDEX).
        width: int, width of every frame read() returns (config.IMAGE_WIDTH).
        height: int, height of every frame read() returns (config.IMAGE_HEIGHT).
        buffer_size: int | None, keyword-only. How many frames the driver may
            queue (cv2.CAP_PROP_BUFFERSIZE; main.py passes
            config.CAMERA_BUFFER_SIZE). None leaves the driver's default.
            Only a request: not every backend honors it.

    Raises:
        RuntimeError: if the device can't be opened.
    """

    def __init__(
        self, index: int, width: int, height: int, *, buffer_size: int | None = None
    ) -> None:
        self._width = width
        self._height = height
        api, api_name = _backend()
        self._capture = cv2.VideoCapture(index, api)
        if not self._capture.isOpened():
            self._capture.release()
            raise RuntimeError(f"could not open camera at index {index} ({api_name})")
        # Only a request: some cameras ignore it, so read() resizes anyway.
        self._capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self._capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        if buffer_size is not None:
            self._capture.set(cv2.CAP_PROP_BUFFERSIZE, buffer_size)

    def delivered_size(self) -> tuple[int, int]:
        """The (width, height) the device reports it delivers, before read() resizes.

        (0, 0) if the backend doesn't report it.
        """
        return (
            int(self._capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
            int(self._capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        )

    def flush(self, frames: int) -> None:
        """Grab and throw away `frames` frames, without decoding them.

        main.py calls it after StartupAction and before the loop takes
        start_time. It drops any frames the driver queued earlier and gives
        auto-exposure and white balance time to settle.

        Raises:
            RuntimeError: if the camera stops delivering frames.
        """
        for _ in range(frames):
            if not self._capture.grab():
                raise RuntimeError("camera read failed while flushing")

    def read(self) -> np.ndarray:
        """Grab one frame.

        Returns:
            numpy.ndarray: BGR frame, shape (height, width, 3), dtype uint8.

        Raises:
            RuntimeError: if the camera returns no frame (e.g. unplugged).
                run_loop's finally block then stops the motors.
        """
        return _fit(self.read_raw(), self._width, self._height)

    def read_raw(self) -> np.ndarray:
        """Grab one frame exactly as the camera delivers it, without resizing.

        tools/capture_samples.py uses this to report the camera's real
        resolution, which read() hides.

        Returns:
            numpy.ndarray: BGR frame, at whatever size the device delivers.

        Raises:
            RuntimeError: if the camera returns no frame (e.g. unplugged).
        """
        ok, frame = self._capture.read()
        if not ok or frame is None:
            raise RuntimeError("camera read failed")
        return frame

    def release(self) -> None:
        """Release the device. Safe to call more than once."""
        self._capture.release()


class StaticImage:
    """An image file served as every frame (for --image and tests).

    Args:
        path: str, the image file to load.
        width: int, width of every frame read() returns.
        height: int, height of every frame read() returns.

    Raises:
        FileNotFoundError: if the file is missing or isn't a readable image.
    """

    def __init__(self, path: str, width: int, height: int) -> None:
        image = cv2.imread(path, cv2.IMREAD_COLOR)
        if image is None:
            raise FileNotFoundError(f"could not read image: {path}")
        self._frame = _fit(image, width, height)

    def read(self) -> np.ndarray:
        """Return a copy of the image.

        A copy, so a task that draws on or edits its frame can't change what
        later passes see.

        Returns:
            numpy.ndarray: BGR frame, shape (height, width, 3), dtype uint8.
        """
        return self._frame.copy()

    def flush(self, frames: int) -> None:
        """Nothing is ever stale; exists so StaticImage matches Camera."""

    def release(self) -> None:
        """Nothing to free; exists so StaticImage matches Camera."""
