#!/usr/bin/env python3
"""Capture still sample images from the robot's camera, run over SSH.

    python3 tools/capture_samples.py                     # interactive session
    python3 tools/capture_samples.py --index 1           # another camera device
    python3 tools/capture_samples.py --outdir captures   # save somewhere else
    python3 tools/capture_samples.py --test              # one frame to /tmp/test.png
    python3 tools/capture_samples.py --dry-run           # no camera (synthetic frame)
    python3 tools/capture_samples.py --dry-run --image path/to.png

For each capture it asks for a name, waits for Enter, throws away
FLUSH_FRAMES frames so auto-exposure and white balance settle and the
driver's stale buffered frames are flushed, then saves the next frame as a
lossless PNG (default tests/sample_images/<name>.png). Images are saved at
the size the camera delivers, unresized. An empty name quits.

The camera is opened through scheduler.camera.Camera, the same wrapper
main.py uses. It's released on every exit path: normal quit, error, Ctrl-C
(SIGINT), `kill` (SIGTERM) and a dropped SSH session (SIGHUP).

No motors: this imports nothing from motion/ and never loads Raspbot_Lib.
"""

from __future__ import annotations

import argparse
import signal
import sys
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path
from types import FrameType
from typing import Protocol

import cv2
import numpy as np

# Run as `python3 tools/capture_samples.py`, Python puts tools/ (not the repo
# root) on sys.path. Add the repo root so `config` and `scheduler` import.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config import CAMERA_INDEX, IMAGE_HEIGHT, IMAGE_WIDTH  # noqa: E402
from scheduler.camera import Camera  # noqa: E402

FLUSH_FRAMES = 15          # frames discarded before each saved one
CENTRE_FRACTION = 0.25     # centre region = middle quarter of width and height
DEFAULT_OUTDIR = REPO_ROOT / "tests" / "sample_images"
DRY_RUN_OUTDIR = Path(tempfile.gettempdir()) / "capture_samples_dry_run"
TEST_PATH = Path("/tmp/test.png")
HANDLED_SIGNALS = tuple(
    sig for sig in (getattr(signal, name, None) for name in ("SIGINT", "SIGTERM", "SIGHUP"))
    if sig is not None  # Windows has no SIGHUP
)

Read = Callable[[str], str]
Write = Callable[[str], None]


class FrameSource(Protocol):
    """What this script needs from a frame source (Camera or StaticSource)."""

    def read_raw(self) -> np.ndarray: ...

    def release(self) -> None: ...


class StaticSource:
    """--dry-run stand-in for Camera: every read returns a copy of one image."""

    def __init__(self, frame: np.ndarray) -> None:
        self._frame = frame

    @classmethod
    def from_file(cls, path: Path) -> StaticSource:
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None:
            raise FileNotFoundError(f"could not read image: {path}")
        return cls(image)

    def read_raw(self) -> np.ndarray:
        return self._frame.copy()

    def release(self) -> None:
        """Nothing to free; exists so StaticSource matches Camera."""


class Signalled(BaseException):
    """Raised by the signal handler. A BaseException, so `except Exception` won't swallow it."""

    def __init__(self, signum: int) -> None:
        super().__init__(signum)
        self.signum = signum


def synthetic_frame(width: int, height: int) -> np.ndarray:
    """A BGR frame of vertical green | red | blue bands, red in the centre."""
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    third = width // 3
    frame[:, :third] = (0, 200, 0)
    frame[:, third:2 * third] = (0, 0, 200)
    frame[:, 2 * third:] = (200, 0, 0)
    return frame


def centre_region(frame: np.ndarray) -> np.ndarray:
    """The middle CENTRE_FRACTION of the frame's width and height."""
    height, width = frame.shape[:2]
    region_h = max(1, round(height * CENTRE_FRACTION))
    region_w = max(1, round(width * CENTRE_FRACTION))
    top = (height - region_h) // 2
    left = (width - region_w) // 2
    return frame[top:top + region_h, left:left + region_w]


def mean_hsv(frame: np.ndarray) -> tuple[float, float, float]:
    """Mean (H, S, V) of the centre region, on OpenCV's scale (H 0-179).

    Hue is averaged as an angle, because it wraps around: red pixels at H=2
    and H=178 average to about 0, not to 90 (cyan). S and V are plain means.
    """
    hsv = cv2.cvtColor(centre_region(frame), cv2.COLOR_BGR2HSV)
    hsv = hsv.reshape(-1, 3).astype(np.float64)
    angles = np.deg2rad(hsv[:, 0] * 2.0)  # OpenCV stores hue as degrees / 2
    mean_deg = np.rad2deg(np.arctan2(np.sin(angles).mean(), np.cos(angles).mean()))
    hue = (mean_deg / 2.0) % 180.0
    return float(hue), float(hsv[:, 1].mean()), float(hsv[:, 2].mean())


def check_frame_size(frame: np.ndarray, write: Write) -> None:
    """Print the size the camera delivers, and warn if config.py expects another."""
    height, width = frame.shape[:2]
    write(f"Camera delivers {width}x{height} frames (shape {frame.shape}).")
    if (width, height) != (IMAGE_WIDTH, IMAGE_HEIGHT):
        write(
            f"WARNING: config.py expects {IMAGE_WIDTH}x{IMAGE_HEIGHT}, but the camera "
            f"delivers {width}x{height}. Images are saved at {width}x{height}; "
            f"Camera.read() and StaticImage resize to {IMAGE_WIDTH}x{IMAGE_HEIGHT}."
        )


def capture(source: FrameSource, path: Path, flush: int = FLUSH_FRAMES) -> np.ndarray:
    """Discard `flush` frames, then save the next one to `path` as a PNG.

    Returns:
        The saved frame.

    Raises:
        RuntimeError: if the camera stops delivering frames.
        OSError: if the PNG can't be written.
    """
    for _ in range(flush):
        source.read_raw()
    frame = source.read_raw()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(path), frame):
        raise OSError(f"could not write {path}")
    return frame


def describe(path: Path, frame: np.ndarray) -> str:
    """The post-capture summary: path, shape and centre mean HSV."""
    hue, sat, val = mean_hsv(frame)
    return (
        f"  Saved {path}\n"
        f"  shape {frame.shape}\n"
        f"  centre mean HSV: H={hue:.1f} S={sat:.1f} V={val:.1f}"
    )


def clean_name(raw: str) -> str:
    """Turn a typed name into a file stem. A trailing ".png" is dropped.

    Raises:
        ValueError: if the name is empty or isn't a plain file name.
    """
    name = raw.strip()
    if name.lower().endswith(".png"):
        name = name[:-4].strip()
    if not name or name in {".", ".."} or any(c in name for c in "/\\\0"):
        raise ValueError(f"{raw.strip()!r} isn't a plain file name; try again.")
    return name


def run_session(source: FrameSource, outdir: Path, read: Read = input, write: Write = print) -> int:
    """The interactive name -> Enter -> capture loop.

    Returns:
        How many images were saved.
    """
    write(f"Saving to {outdir}. Each capture discards {FLUSH_FRAMES} frames first.")
    saved = 0
    while True:
        try:
            raw = read("\nImage name (empty to quit): ")
            if not raw.strip():
                break
            try:
                name = clean_name(raw)
            except ValueError as exc:
                write(f"  {exc}")
                continue
            path = outdir / f"{name}.png"
            if path.exists():
                answer = read(f"  {path} already exists. Overwrite? [y/N] ")
                if answer.strip().lower() not in {"y", "yes"}:
                    write("  Kept the existing file.")
                    continue
            if read("  Press Enter to capture (anything else cancels): ").strip():
                write("  Cancelled.")
                continue
        except EOFError:  # stdin closed
            break
        frame = capture(source, path)
        write(describe(path, frame))
        saved += 1
    write(f"\nDone: {saved} image(s) saved.")
    return saved


def open_source(args: argparse.Namespace, write: Write) -> FrameSource:
    """The live camera, or a StaticSource for --dry-run."""
    if not args.dry_run:
        write(f"Opening camera {args.index} (requesting {IMAGE_WIDTH}x{IMAGE_HEIGHT})...")
        return Camera(args.index, IMAGE_WIDTH, IMAGE_HEIGHT)
    if args.image is None:
        write("[dry-run] No camera: every frame is a synthetic green|red|blue pattern.")
        return StaticSource(synthetic_frame(IMAGE_WIDTH, IMAGE_HEIGHT))
    write(f"[dry-run] No camera: every frame is {args.image}.")
    return StaticSource.from_file(args.image)


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture still sample images from the robot's camera (no motors)."
    )
    parser.add_argument(
        "--index", type=int, default=CAMERA_INDEX,
        help=f"cv2.VideoCapture device index (default: config.CAMERA_INDEX = {CAMERA_INDEX})",
    )
    parser.add_argument(
        "--outdir", type=Path, default=None,
        help=f"where to save images (default: {DEFAULT_OUTDIR.relative_to(REPO_ROOT)}; "
             f"with --dry-run, {DRY_RUN_OUTDIR})",
    )
    parser.add_argument(
        "--test", nargs="?", const=TEST_PATH, type=Path, default=None, metavar="PATH",
        help=f"capture one frame to PATH (default {TEST_PATH.as_posix()}), print its shape, and exit",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="read a static image instead of the camera (works on any machine)",
    )
    parser.add_argument(
        "--image", type=Path, default=None,
        help="with --dry-run: the image to use (default: a synthetic test pattern)",
    )
    args = parser.parse_args(argv)
    if args.image is not None and not args.dry_run:
        parser.error("--image needs --dry-run")
    if args.outdir is None:
        # A dry run would otherwise drop fake images into tests/sample_images.
        args.outdir = DRY_RUN_OUTDIR if args.dry_run else DEFAULT_OUTDIR
    return args


def _set_handlers(handler: object) -> dict[int, object]:
    """Install `handler` for HANDLED_SIGNALS. Returns the previous handlers."""
    return {sig: signal.signal(sig, handler) for sig in HANDLED_SIGNALS}  # type: ignore[arg-type]


def _safe_write(write: Write, message: str) -> None:
    """Write, ignoring a dead terminal (after SIGHUP, stdout can raise EIO)."""
    try:
        write(message)
    except OSError:
        pass


def main(argv: Sequence[str] | None = None, read: Read = input, write: Write = print) -> int:
    """Run the script. Returns the exit code (128 + signal number if signalled)."""
    args = parse_args(argv)
    fired = False

    def on_signal(signum: int, _frame: FrameType | None) -> None:
        nonlocal fired
        if not fired:  # a second signal mustn't interrupt the cleanup
            fired = True
            raise Signalled(signum)

    previous = _set_handlers(on_signal)
    source: FrameSource | None = None
    try:
        source = open_source(args, write)
        check_frame_size(source.read_raw(), write)
        if args.test is not None:
            frame = capture(source, args.test)
            write(f"Test frame saved to {args.test}, shape {frame.shape}.")
        else:
            run_session(source, args.outdir, read, write)
        return 0
    except Signalled as exc:
        _safe_write(write, f"\nStopped by {signal.Signals(exc.signum).name}.")
        return 128 + exc.signum
    except (RuntimeError, OSError) as exc:  # camera failure, bad image, unwritable path
        _safe_write(write, f"error: {exc}")
        return 1
    finally:
        _set_handlers(signal.SIG_IGN)  # nothing may interrupt the release
        try:
            if source is not None:
                source.release()
                _safe_write(write, "Camera released.")
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)  # type: ignore[arg-type]


if __name__ == "__main__":
    sys.exit(main())
