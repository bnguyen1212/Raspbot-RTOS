"""Tests for tools/capture_samples.py, with scripted input and fake frame sources.

No camera is opened: every test uses a fake source or --dry-run.
"""

from __future__ import annotations

import importlib.util
import signal
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import cv2
import numpy as np
import pytest

from config import IMAGE_HEIGHT, IMAGE_WIDTH

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "capture_samples.py"


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("capture_samples", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


script = load_script()


@pytest.fixture(autouse=True)
def _restore_signal_handlers():
    saved = {sig: signal.getsignal(sig) for sig in script.HANDLED_SIGNALS}
    yield
    for sig, handler in saved.items():
        signal.signal(sig, handler)


class CountingSource:
    """Frame i is filled with the value i, so a test can tell which frame was saved."""

    def __init__(self, shape=(IMAGE_HEIGHT, IMAGE_WIDTH, 3), fail_after=None, on_read=None):
        self.shape = shape
        self.reads = 0
        self.releases = 0
        self.fail_after = fail_after
        self.on_read = on_read

    def read_raw(self):
        if self.on_read is not None:
            self.on_read(self.reads)
        if self.fail_after is not None and self.reads >= self.fail_after:
            raise RuntimeError("camera read failed")
        frame = np.full(self.shape, self.reads % 256, dtype=np.uint8)
        self.reads += 1
        return frame

    def release(self):
        self.releases += 1


def scripted(*answers):
    queue = list(answers)

    def read(prompt):
        if not queue:
            raise EOFError
        return queue.pop(0)

    return read


# --- pure helpers ----------------------------------------------------------

def test_mean_hsv_averages_hue_as_an_angle(monkeypatch):
    # Half the pixels at H=2, half at H=178: both red. A plain mean says 90 (cyan).
    hsv = np.zeros((40, 40, 3), dtype=np.uint8)
    hsv[:, :, 1:] = 255
    hsv[:, :20, 0] = 2
    hsv[:, 20:, 0] = 178
    frame = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    monkeypatch.setattr(script, "CENTRE_FRACTION", 1.0)
    hue, sat, val = script.mean_hsv(frame)
    assert min(hue, 180 - hue) < 1.5
    assert sat == pytest.approx(255, abs=1)
    assert val == pytest.approx(255, abs=1)


def test_mean_hsv_uses_only_the_centre_region():
    frame = script.synthetic_frame(IMAGE_WIDTH, IMAGE_HEIGHT)  # red band in the middle
    hue, sat, val = script.mean_hsv(frame)
    assert (round(hue), round(sat), round(val)) == (0, 255, 200)


@pytest.mark.parametrize("raw, expected", [("red", "red"), (" red.png ", "red"), ("a b", "a b")])
def test_clean_name_accepts_plain_names(raw, expected):
    assert script.clean_name(raw) == expected


@pytest.mark.parametrize("raw", ["a/b", "a\\b", "..", ".png", "../x"])
def test_clean_name_rejects_paths(raw):
    with pytest.raises(ValueError):
        script.clean_name(raw)


def test_frame_size_warning_only_on_mismatch():
    out = []
    script.check_frame_size(np.zeros((IMAGE_HEIGHT, IMAGE_WIDTH, 3), np.uint8), out.append)
    assert len(out) == 1 and f"{IMAGE_WIDTH}x{IMAGE_HEIGHT}" in out[0]
    out.clear()
    script.check_frame_size(np.zeros((720, 1280, 3), np.uint8), out.append)
    assert "1280x720" in out[0]
    assert any("WARNING" in line for line in out)


def test_capture_discards_flush_frames_and_saves_the_next_losslessly(tmp_path):
    source = CountingSource()
    path = tmp_path / "nested" / "x.png"
    frame = script.capture(source, path)
    assert source.reads == script.FLUSH_FRAMES + 1
    assert frame[0, 0, 0] == script.FLUSH_FRAMES  # frame 15, the one after the discards
    np.testing.assert_array_equal(cv2.imread(str(path)), frame)


# --- interactive session ---------------------------------------------------

def test_session_saves_named_image_and_empty_name_quits(tmp_path):
    out = []
    saved = script.run_session(CountingSource(), tmp_path, scripted("cube", "", ""), out.append)
    assert saved == 1
    assert (tmp_path / "cube.png").exists()
    text = "\n".join(out)
    assert "cube.png" in text and "shape (480, 640, 3)" in text and "centre mean HSV" in text


def test_session_refuses_overwrite_unless_confirmed(tmp_path):
    target = tmp_path / "cube.png"
    target.write_bytes(b"original")
    out = []
    script.run_session(CountingSource(), tmp_path, scripted("cube", "n", ""), out.append)
    assert target.read_bytes() == b"original"
    assert any("Kept the existing file" in line for line in out)

    script.run_session(CountingSource(), tmp_path, scripted("cube", "y", "", ""), out.append)
    assert cv2.imread(str(target)) is not None  # replaced with a real PNG


def test_session_typing_at_capture_prompt_cancels(tmp_path):
    source = CountingSource()
    saved = script.run_session(source, tmp_path, scripted("cube", "x", ""), lambda _: None)
    assert saved == 0 and source.reads == 0
    assert not (tmp_path / "cube.png").exists()


def test_session_ends_on_eof(tmp_path):
    assert script.run_session(CountingSource(), tmp_path, scripted("cube"), lambda _: None) == 0


# --- main(): exit paths all release the source -----------------------------

def run_main(monkeypatch, source, argv, read=scripted("")):
    monkeypatch.setattr(script, "open_source", lambda args, write: source)
    out = []
    code = script.main(argv, read=read, write=out.append)
    return code, out


def test_main_test_flag_saves_one_frame(monkeypatch, tmp_path):
    source = CountingSource()
    code, out = run_main(monkeypatch, source, ["--test", str(tmp_path / "t.png")])
    assert code == 0
    assert (tmp_path / "t.png").exists()
    assert any("shape (480, 640, 3)" in line for line in out)
    assert source.releases == 1


def test_test_flag_defaults_to_tmp_test_png():
    assert script.parse_args(["--test"]).test == Path("/tmp/test.png")


def test_main_releases_on_camera_failure(monkeypatch, tmp_path):
    source = CountingSource(fail_after=3)
    code, out = run_main(monkeypatch, source, ["--outdir", str(tmp_path)], scripted("cube", ""))
    assert code == 1
    assert any("camera read failed" in line for line in out)
    assert source.releases == 1


signals = [signal.SIGINT, signal.SIGTERM]
if hasattr(signal, "SIGHUP"):
    signals.append(signal.SIGHUP)


@pytest.mark.parametrize("sig", signals, ids=lambda s: signal.Signals(s).name)
def test_main_releases_on_signal_during_prompt(monkeypatch, tmp_path, sig):
    def read(prompt):
        signal.raise_signal(sig)
        raise AssertionError("signal handler should have raised")

    source = CountingSource()
    code, out = run_main(monkeypatch, source, ["--outdir", str(tmp_path)], read)
    assert code == 128 + sig
    assert source.releases == 1
    assert any(signal.Signals(sig).name in line for line in out)


def test_main_releases_on_signal_during_capture(monkeypatch, tmp_path):
    def on_read(n):
        if n == 5:
            signal.raise_signal(signal.SIGINT)

    source = CountingSource(on_read=on_read)
    code, _ = run_main(monkeypatch, source, ["--outdir", str(tmp_path)], scripted("cube", ""))
    assert code == 130
    assert source.releases == 1
    assert not (tmp_path / "cube.png").exists()


def test_main_restores_previous_signal_handlers(monkeypatch, tmp_path):
    before = {sig: signal.getsignal(sig) for sig in script.HANDLED_SIGNALS}
    run_main(monkeypatch, CountingSource(), ["--outdir", str(tmp_path)])
    assert {sig: signal.getsignal(sig) for sig in script.HANDLED_SIGNALS} == before


# --- argument handling -----------------------------------------------------

def test_image_requires_dry_run():
    with pytest.raises(SystemExit):
        script.parse_args(["--image", "x.png"])


def test_dry_run_defaults_outdir_away_from_tests():
    assert script.parse_args(["--dry-run"]).outdir == script.DRY_RUN_OUTDIR
    assert script.parse_args([]).outdir == script.DEFAULT_OUTDIR


def test_dry_run_end_to_end(tmp_path):
    out = []
    code = script.main(
        ["--dry-run", "--outdir", str(tmp_path)], read=scripted("red", "", ""), write=out.append
    )
    assert code == 0
    assert (tmp_path / "red.png").exists()
    assert "Camera released." in out


def test_script_never_imports_motion(tmp_path):
    # Fresh interpreter, so modules that other tests imported don't count.
    code = "; ".join([
        "import importlib.util, sys",
        f"spec = importlib.util.spec_from_file_location('cs', {str(SCRIPT)!r})",
        "m = importlib.util.module_from_spec(spec)",
        "spec.loader.exec_module(m)",
        f"m.main(['--dry-run', '--test', {str(tmp_path / 't.png')!r}], write=lambda _: None)",
        "print(sorted(n for n in sys.modules if n.split('.')[0] in ('motion', 'Raspbot_Lib')))",
    ])
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == '[]'
