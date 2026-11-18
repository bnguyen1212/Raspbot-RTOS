"""Tests for main.py's command line, --dry-run, and scheduler.camera.

The end-to-end dry runs start main.py in a separate Python process. That way
the "motion/ was never imported" check can't be fooled by another test in
this process having imported it already.
"""

from __future__ import annotations

import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import cv2
import numpy as np
import pytest

import main
from config import (
    CAMERA_BUFFER_SIZE,
    CAMERA_FLUSH_FRAMES,
    CAMERA_INDEX,
    IMAGE_HEIGHT,
    IMAGE_WIDTH,
    SECONDS_PER_180,
    TIMEOUT_SECONDS,
)
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
    # (startup_action is wrapped with the camera flush; see below.)
    for name in ("idle_action", "red_action", "stop_motors"):
        assert isinstance(tasks[name].__self__, DryRunMotion)


def test_real_mode_wiring_uses_motion_actions(card_image, monkeypatch):
    from motion import actions

    started = []
    monkeypatch.setattr(actions, "StartupAction", lambda: started.append("StartupAction"))
    tasks = main.build_tasks(main.parse_args(["--image", card_image]))
    tasks["startup_action"]()
    assert started == ["StartupAction"]  # wrapped with the flush, still the real action
    assert tasks["idle_action"] is actions.IdleAction
    assert tasks["red_action"] is actions.RedAction
    assert tasks["stop_motors"] is actions.ShutdownAction
    assert tasks["color_actions"] == {"green": actions.GreenAction, "blue": actions.BlueAction}


def test_startup_then_flush_runs_the_startup_first():
    order = []
    startup = main.startup_then_flush(lambda: order.append("startup"), lambda: order.append("flush"))
    assert order == []  # nothing runs until run_loop calls it
    startup()
    assert order == ["startup", "flush"]


def test_startup_failure_skips_the_flush():
    flushed = []

    def broken_startup():
        raise RuntimeError("motor init failed")

    with pytest.raises(RuntimeError):
        main.startup_then_flush(broken_startup, lambda: flushed.append(True))()
    assert flushed == []


def test_live_camera_wiring_flushes_after_startup(monkeypatch):
    """With a live camera, build_tasks opens it with the configured buffer size,
    and its startup_action runs the startup and then the flush."""
    events = []

    class RecordingCamera:
        def __init__(self, index, width, height, *, buffer_size=None):
            events.append(("open", index, width, height, buffer_size))

        def delivered_size(self):
            return IMAGE_WIDTH, IMAGE_HEIGHT

        def flush(self, frames):
            events.append(("flush", frames))

        def read(self):
            return np.zeros((IMAGE_HEIGHT, IMAGE_WIDTH, 3), dtype=np.uint8)

        def release(self):
            events.append(("release",))

    monkeypatch.setattr(main, "Camera", RecordingCamera)
    tasks = main.build_tasks(main.parse_args(["--dry-run", "--camera", "3"]))
    assert events == [("open", 3, IMAGE_WIDTH, IMAGE_HEIGHT, CAMERA_BUFFER_SIZE)]

    tasks["startup_action"]()
    assert events[-1] == ("flush", CAMERA_FLUSH_FRAMES)


@pytest.mark.parametrize(
    "size, warns",
    [((IMAGE_WIDTH, IMAGE_HEIGHT), False), ((1280, 720), True)],
)
def test_report_camera_warns_only_on_a_size_mismatch(capsys, size, warns):
    class SizedCamera:
        def delivered_size(self):
            return size

    main.report_camera(SizedCamera(), 0)  # type: ignore[arg-type]
    out = capsys.readouterr()
    assert f"delivering {size[0]}x{size[1]}" in out.out
    assert ("WARNING" in out.err) is warns


def test_report_camera_when_the_backend_reports_no_size(capsys):
    class UnsizedCamera:
        def delivered_size(self):
            return 0, 0

    main.report_camera(UnsizedCamera(), 0)  # type: ignore[arg-type]
    out = capsys.readouterr()
    assert "doesn't report" in out.out
    assert out.err == ""


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------

def recording_signal_helpers(monkeypatch):
    """Replace main's signal helpers with recorders; nothing is really installed."""
    calls = []

    def install(stop, *, release=None, write=print):
        calls.append(("install", stop, release))
        return {"previous": True}

    monkeypatch.setattr(main, "install_stop_handlers", install)
    monkeypatch.setattr(main, "restore_handlers", lambda previous: calls.append(("restore", previous)))
    return calls


@pytest.mark.parametrize("outcome", ["timeout", "error"])
def test_main_installs_stop_handlers_around_the_loop(monkeypatch, card_image, outcome):
    calls = recording_signal_helpers(monkeypatch)

    def fake_run_loop(state, **tasks):
        # The handlers are in place before the loop (and StartupAction) runs,
        # with the run's own stop_motors and release_camera.
        assert calls == [("install", tasks["stop_motors"], tasks["release_camera"])]
        if outcome == "error":
            raise RuntimeError("camera read failed")

    monkeypatch.setattr(main, "run_loop", fake_run_loop)
    if outcome == "error":
        with pytest.raises(RuntimeError):
            main.main(["--dry-run", "--image", card_image])
    else:
        main.main(["--dry-run", "--image", card_image])
    assert calls[-1] == ("restore", {"previous": True})


def test_main_leaves_the_signal_handlers_as_it_found_them(monkeypatch, card_image):
    from scheduler.signals import STOP_SIGNALS

    before = {sig: signal.getsignal(sig) for sig in STOP_SIGNALS}
    seen_during = {}

    def fake_run_loop(state, **tasks):
        seen_during.update({sig: signal.getsignal(sig) for sig in STOP_SIGNALS})

    monkeypatch.setattr(main, "run_loop", fake_run_loop)
    main.main(["--dry-run", "--image", card_image])
    assert all(seen_during[sig] is not before[sig] for sig in STOP_SIGNALS)
    assert {sig: signal.getsignal(sig) for sig in STOP_SIGNALS} == before


@pytest.mark.skipif(not hasattr(signal, "SIGHUP"), reason="needs POSIX signals (runs on the Pi)")
@pytest.mark.parametrize("sig", ["SIGTERM", "SIGHUP", "SIGINT"])
def test_real_signal_stops_a_dry_run_loop_and_exits(card_image, sig):
    """Send a real signal to main.py --dry-run while its loop is running."""
    proc = subprocess.Popen(
        [sys.executable, "-u", "main.py", "--dry-run", "--image", card_image, "--timeout", "30"],
        cwd=REPO_ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True,
    )
    try:
        assert proc.stdout is not None
        while "StartupAction" not in proc.stdout.readline():  # wait until it's running
            pass
        time.sleep(0.5)  # let it get into the loop
        proc.send_signal(getattr(signal, sig))
        out, _ = proc.communicate(timeout=10)
    finally:
        proc.kill()
    assert proc.returncode == 128 + getattr(signal, sig)
    assert "stop_motors: motors stopped" in out
    assert f"{sig}: stop sent" in out
    assert "Timeout reached" not in out


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

    # Start at 0.0 so that "now - red_start" is exactly SECONDS_PER_180 at the
    # limit, whatever its calibrated value. (From 5.0, 5.0 + 1.1 - 5.0 rounds
    # to just under 1.1.) It also checks that a turn started at time 0.0
    # counts as running: red_start is compared with None, not for truthiness.
    started = fake.red_action(state, 0.0)
    assert started == {"red_start": 0.0, "red_rearm": True}
    assert state == {"red_start": None, "red_rearm": True}  # input not modified

    assert fake.red_action(started, SECONDS_PER_180 / 2) == started
    assert fake.red_action(started, SECONDS_PER_180) == {"red_start": None, "red_rearm": False}


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

    def __init__(self, index, api=None, opened=True, frames=(), grabs=None, size=(640, 480)):
        self.index = index
        self.api = api
        self.opened = opened
        self.frames = list(frames)
        self.grabs_left = grabs  # None: grab() always succeeds
        self.grab_count = 0
        self.size = size
        self.settings = {}
        self.release_count = 0

    def isOpened(self):
        return self.opened

    def set(self, prop, value):
        self.settings[prop] = value

    def get(self, prop):
        sizes = {cv2.CAP_PROP_FRAME_WIDTH: self.size[0], cv2.CAP_PROP_FRAME_HEIGHT: self.size[1]}
        return float(sizes.get(prop, 0))

    def grab(self):
        if self.grabs_left is not None:
            if self.grabs_left == 0:
                return False
            self.grabs_left -= 1
        self.grab_count += 1
        return True

    def read(self):
        if not self.frames:
            return False, None
        return True, self.frames.pop(0)

    def release(self):
        self.release_count += 1


def test_camera_opens_device_resizes_frames_and_releases(monkeypatch):
    opened = []

    def fake_video_capture(index, api):
        capture = FakeVideoCapture(index, api, frames=[np.zeros((720, 1280, 3), dtype=np.uint8)])
        opened.append(capture)
        return capture

    monkeypatch.setattr(camera_module.cv2, "VideoCapture", fake_video_capture)

    cam = Camera(2, IMAGE_WIDTH, IMAGE_HEIGHT)
    capture = opened[0]
    assert capture.index == 2
    assert capture.settings[cv2.CAP_PROP_FRAME_WIDTH] == IMAGE_WIDTH
    assert capture.settings[cv2.CAP_PROP_FRAME_HEIGHT] == IMAGE_HEIGHT
    assert cv2.CAP_PROP_BUFFERSIZE not in capture.settings  # left alone unless asked

    assert cam.read().shape == (IMAGE_HEIGHT, IMAGE_WIDTH, 3)  # 1280x720 resized

    with pytest.raises(RuntimeError, match="read failed"):      # no more frames
        cam.read()

    cam.release()
    assert capture.release_count == 1


def test_camera_read_raw_returns_frame_unresized(monkeypatch):
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    monkeypatch.setattr(
        camera_module.cv2, "VideoCapture",
        lambda index, api: FakeVideoCapture(index, api, frames=[frame]),
    )
    cam = Camera(0, IMAGE_WIDTH, IMAGE_HEIGHT)
    assert cam.read_raw().shape == (720, 1280, 3)
    with pytest.raises(RuntimeError, match="read failed"):
        cam.read_raw()


def test_camera_that_cannot_open_raises(monkeypatch):
    monkeypatch.setattr(
        camera_module.cv2, "VideoCapture",
        lambda index, api: FakeVideoCapture(index, api, opened=False),
    )
    with pytest.raises(RuntimeError, match="could not open camera"):
        Camera(0, IMAGE_WIDTH, IMAGE_HEIGHT)


def install_fake_capture(monkeypatch, **kwargs) -> list[FakeVideoCapture]:
    opened: list[FakeVideoCapture] = []

    def fake_video_capture(index, api):
        capture = FakeVideoCapture(index, api, **kwargs)
        opened.append(capture)
        return capture

    monkeypatch.setattr(camera_module.cv2, "VideoCapture", fake_video_capture)
    return opened


@pytest.mark.parametrize(
    "platform, api",
    [("linux", cv2.CAP_V4L2), ("win32", cv2.CAP_ANY), ("darwin", cv2.CAP_ANY)],
)
def test_camera_uses_v4l2_on_linux_only(monkeypatch, platform, api):
    monkeypatch.setattr(camera_module.sys, "platform", platform)
    opened = install_fake_capture(monkeypatch)
    Camera(0, IMAGE_WIDTH, IMAGE_HEIGHT)
    assert opened[0].api == api


def test_camera_requests_the_buffer_size(monkeypatch):
    opened = install_fake_capture(monkeypatch)
    Camera(0, IMAGE_WIDTH, IMAGE_HEIGHT, buffer_size=1)
    assert opened[0].settings[cv2.CAP_PROP_BUFFERSIZE] == 1


def test_camera_reports_the_delivered_size(monkeypatch):
    install_fake_capture(monkeypatch, size=(1280, 720))
    assert Camera(0, IMAGE_WIDTH, IMAGE_HEIGHT).delivered_size() == (1280, 720)


def test_camera_flush_grabs_without_decoding(monkeypatch):
    opened = install_fake_capture(monkeypatch, frames=[np.zeros((480, 640, 3), dtype=np.uint8)])
    cam = Camera(0, IMAGE_WIDTH, IMAGE_HEIGHT)
    cam.flush(15)
    assert opened[0].grab_count == 15
    assert len(opened[0].frames) == 1  # read() was never called
    cam.flush(0)
    assert opened[0].grab_count == 15


def test_camera_flush_raises_when_frames_stop(monkeypatch):
    install_fake_capture(monkeypatch, grabs=3)
    cam = Camera(0, IMAGE_WIDTH, IMAGE_HEIGHT)
    with pytest.raises(RuntimeError, match="flushing"):
        cam.flush(15)


def test_static_image_flush_does_nothing(card_image):
    source = StaticImage(card_image, IMAGE_WIDTH, IMAGE_HEIGHT)
    before = source.read()
    source.flush(15)
    assert np.array_equal(source.read(), before)
