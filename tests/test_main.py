"""Tests for main.py's command line, --dry-run, and scheduler.camera.

The end-to-end dry runs start main.py in a separate Python process. That way
the "motion/ was never imported" check can't be fooled by another test in
this process having imported it already.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import cv2
import numpy as np
import pytest

import main
from config import CAMERA_INDEX, IMAGE_HEIGHT, IMAGE_WIDTH, SECONDS_PER_180, TIMEOUT_SECONDS
from scheduler import camera as camera_module
from scheduler.camera import Camera, StaticImage
from scheduler.dry_run import DryRunMotion

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def card_image(tmp_path) -> str:
    """A small image file with a green card on black.

    320x240, deliberately not the configured frame size, so resizing gets
    exercised too.
    """
    image = np.zeros((240, 320, 3), dtype=np.uint8)
    image[60:180, 200:300] = (0, 200, 0)  # BGR green
    path = tmp_path / "card.png"
    cv2.imwrite(str(path), image)
    return str(path)


def run_python(code: str) -> subprocess.CompletedProcess:
    """Run `code` in a fresh Python process from the repo root."""
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )


# ---------------------------------------------------------------------------
# --dry-run end to end
# ---------------------------------------------------------------------------

def test_dry_run_on_a_static_image_never_imports_motion(card_image):
    """Vision is still a stub on dev, so it's faked here; everything else
    (command line, frame source, dry-run motion, loop, timeout) is real."""
    result = run_python(f"""
        import sys
        import vision.color_counter, vision.color_locator
        vision.color_counter.ColorCounter = lambda image: {{"green": 0, "blue": 0, "red": 900}}
        vision.color_locator.ColorLocator = lambda counts, image: ("red", (320.0, 240.0))

        import main
        main.main(["--dry-run", "--image", {card_image!r}, "--timeout", "0.3"])

        loaded = [m for m in sys.modules if m == "motion" or m.startswith("motion.")]
        assert not loaded, f"dry run imported {{loaded}}"
    """)
    assert result.returncode == 0, result.stderr
    assert "RedAction: start 180 turn" in result.stdout
    assert "stop_motors: motors stopped" in result.stdout
    assert "Timeout reached" in result.stdout


def vision_is_stubbed() -> bool:
    from vision.color_counter import ColorCounter

    try:
        ColorCounter(np.zeros((IMAGE_HEIGHT, IMAGE_WIDTH, 3), dtype=np.uint8))
    except NotImplementedError:
        return True
    return False


@pytest.mark.skipif(vision_is_stubbed(), reason="vision/ isn't implemented on this branch yet")
def test_dry_run_command_with_real_vision(card_image):
    """Turns itself on once the vision code is merged."""
    result = subprocess.run(
        [sys.executable, "main.py", "--dry-run", "--image", card_image, "--timeout", "0.5"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "GreenAction" in result.stdout
    assert "stop_motors: motors stopped" in result.stdout


# ---------------------------------------------------------------------------
# Command line and wiring
# ---------------------------------------------------------------------------

def test_defaults_come_from_config():
    args = main.parse_args([])
    assert args.dry_run is False
    assert args.image is None
    assert args.camera == CAMERA_INDEX
    assert args.timeout == TIMEOUT_SECONDS


@pytest.mark.parametrize("bad", ["0", "-5", "abc"])
def test_timeout_must_be_a_positive_number(bad):
    with pytest.raises(SystemExit):
        main.parse_args(["--timeout", bad])


def test_dry_run_wiring(card_image):
    args = main.parse_args(["--dry-run", "--image", card_image, "--timeout", "2"])
    tasks = main.build_tasks(args)

    assert tasks["timeout"] == 2.0
    assert tasks["capture_frame"]().shape == (IMAGE_HEIGHT, IMAGE_WIDTH, 3)
    # Every motion task is a DryRunMotion method, not a motion/ function.
    for name in ("startup_action", "idle_action", "red_action", "stop_motors"):
        assert isinstance(tasks[name].__self__, DryRunMotion)


def test_real_mode_wiring_uses_motion_actions(card_image):
    from motion import actions

    tasks = main.build_tasks(main.parse_args(["--image", card_image]))
    assert tasks["startup_action"] is actions.StartupAction
    assert tasks["idle_action"] is actions.IdleAction
    assert tasks["red_action"] is actions.RedAction
    assert tasks["stop_motors"] is actions.ShutdownAction
    assert tasks["color_actions"] == {"green": actions.GreenAction, "blue": actions.BlueAction}


def test_ctrl_c_exits_with_code_130(monkeypatch, card_image):
    def interrupted(state, **tasks):
        raise KeyboardInterrupt

    monkeypatch.setattr(main, "run_loop", interrupted)
    with pytest.raises(SystemExit) as exit_info:
        main.main(["--dry-run", "--image", card_image])
    assert exit_info.value.code == 130


# ---------------------------------------------------------------------------
# DryRunMotion
# ---------------------------------------------------------------------------

def test_dry_run_prints_only_when_the_action_changes():
    lines = []
    fake = DryRunMotion(log=lines.append)
    fake.idle_action()
    fake.idle_action()
    fake.green_action((400.0, 240.0))
    fake.green_action((410.0, 240.0))
    fake.idle_action()
    assert lines == [
        "[dry-run] IdleAction",
        "[dry-run] GreenAction p_vector=(400, 240)",
        "[dry-run] IdleAction",
    ]


def test_dry_run_red_action_follows_the_contract_timing():
    fake = DryRunMotion(log=lambda line: None)
    state = {"red_start": None, "red_rearm": True}

    started = fake.red_action(state, 5.0)
    assert started == {"red_start": 5.0, "red_rearm": True}
    assert state == {"red_start": None, "red_rearm": True}  # input not modified

    assert fake.red_action(started, 5.0 + SECONDS_PER_180 / 2) == started
    assert fake.red_action(started, 5.0 + SECONDS_PER_180) == {"red_start": None, "red_rearm": False}


# ---------------------------------------------------------------------------
# Frame sources
# ---------------------------------------------------------------------------

def test_static_image_is_resized_and_read_returns_copies(card_image):
    source = StaticImage(card_image, IMAGE_WIDTH, IMAGE_HEIGHT)
    frame = source.read()
    assert frame.shape == (IMAGE_HEIGHT, IMAGE_WIDTH, 3)
    assert frame.dtype == np.uint8

    frame[:] = 0                    # a task scribbling on its frame...
    assert source.read().any()      # ...doesn't change the next one
    source.release()
    source.release()                # safe to call twice


def test_static_image_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        StaticImage(str(tmp_path / "missing.png"), IMAGE_WIDTH, IMAGE_HEIGHT)


class FakeVideoCapture:
    """Stands in for cv2.VideoCapture, so no webcam is needed."""

    def __init__(self, index, opened=True, frames=()):
        self.index = index
        self.opened = opened
        self.frames = list(frames)
        self.settings = {}
        self.release_count = 0

    def isOpened(self):
        return self.opened

    def set(self, prop, value):
        self.settings[prop] = value

    def read(self):
        if not self.frames:
            return False, None
        return True, self.frames.pop(0)

    def release(self):
        self.release_count += 1


def test_camera_opens_device_resizes_frames_and_releases(monkeypatch):
    opened = []

    def fake_video_capture(index):
        capture = FakeVideoCapture(index, frames=[np.zeros((720, 1280, 3), dtype=np.uint8)])
        opened.append(capture)
        return capture

    monkeypatch.setattr(camera_module.cv2, "VideoCapture", fake_video_capture)

    cam = Camera(2, IMAGE_WIDTH, IMAGE_HEIGHT)
    capture = opened[0]
    assert capture.index == 2
    assert capture.settings[cv2.CAP_PROP_FRAME_WIDTH] == IMAGE_WIDTH
    assert capture.settings[cv2.CAP_PROP_FRAME_HEIGHT] == IMAGE_HEIGHT

    assert cam.read().shape == (IMAGE_HEIGHT, IMAGE_WIDTH, 3)  # 1280x720 resized

    with pytest.raises(RuntimeError, match="read failed"):      # no more frames
        cam.read()

    cam.release()
    assert capture.release_count == 1


def test_camera_that_cannot_open_raises(monkeypatch):
    monkeypatch.setattr(
        camera_module.cv2, "VideoCapture", lambda index: FakeVideoCapture(index, opened=False)
    )
    with pytest.raises(RuntimeError, match="could not open camera"):
        Camera(0, IMAGE_WIDTH, IMAGE_HEIGHT)
