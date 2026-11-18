"""Tests for tools/vision_debug.py.

tools/ isn't a package (the script must run standalone), so it's loaded from
its file path. One test also runs it as a real command from another working
directory, the way it will be used.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import cv2
import numpy as np
import pytest

from config import IMAGE_HEIGHT, IMAGE_WIDTH, TRACKED_COLORS
from tests.vision_images import blank_frame, color_bgr, draw_rect, hsv_to_bgr
from vision.hsv_mask import to_hsv

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "vision_debug.py"


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("vision_debug", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def tool() -> ModuleType:
    return load_script()


@pytest.fixture
def green_card(tmp_path) -> Path:
    """320x240 (not the configured size), green card on the right."""
    image = np.zeros((240, 320, 3), dtype=np.uint8)
    image[60:180, 200:300] = color_bgr("green")
    path = tmp_path / "green_right_card.png"
    cv2.imwrite(str(path), image)
    return path


def test_analyze_matches_the_real_pipeline(tool):
    frame = blank_frame()
    area = draw_rect(frame, 400, 100, 500, 200, color_bgr("blue"))

    analysis = tool.analyze(frame)

    assert analysis.counts == {"green": 0, "blue": area, "red": 0}
    assert analysis.winning_color == "blue"
    assert analysis.position == pytest.approx((449.5, 149.5))
    for color in TRACKED_COLORS:
        assert np.count_nonzero(analysis.masks[color]) == analysis.counts[color]


@pytest.mark.parametrize("winner", [None, "red"])
def test_render_produces_a_two_wide_grid_of_panels(tool, winner):
    frame = blank_frame()
    if winner:
        draw_rect(frame, 0, 0, 100, 100, color_bgr(winner))

    picture = tool.render(frame, tool.analyze(frame))

    panels = 1 + len(TRACKED_COLORS)
    rows = (panels + 1) // 2
    assert picture.shape == (IMAGE_HEIGHT * rows, IMAGE_WIDTH * 2, 3)
    assert picture.dtype == np.uint8


def test_render_does_not_modify_the_frame(tool):
    frame = blank_frame()
    draw_rect(frame, 300, 200, 360, 260, color_bgr("green"))
    before = frame.copy()

    tool.render(frame, tool.analyze(frame))

    np.testing.assert_array_equal(frame, before)


def test_hsv_report_covers_every_color(tool):
    frame = blank_frame()
    draw_rect(frame, 0, 0, 50, 50, color_bgr("red"))

    lines = "\n".join(tool.hsv_report(to_hsv(frame), tool.analyze(frame).masks))

    for color in TRACKED_COLORS:
        assert f"{color}:" in lines
    assert "no counted pixels" in lines  # green and blue


def test_hsv_report_gives_red_statistics_per_range(tool):
    """Pooled statistics across the hue wrap would be meaningless: hues 2
    and 176 would give a median of 89."""
    frame = blank_frame()
    frame[0:50, 0:50] = hsv_to_bgr(2, 255, 255)
    frame[0:50, 100:150] = hsv_to_bgr(176, 255, 255)

    report = tool.hsv_report(to_hsv(frame), tool.analyze(frame).masks)

    red_lines = [line for line in report if "px, H/S/V" in line]
    assert len(red_lines) == 2
    assert "median (2, 255, 255)" in red_lines[0]
    assert "median (176, 255, 255)" in red_lines[1]


def test_hsv_report_counts_pixels_removed_by_the_noise_filter(tool):
    frame = blank_frame()
    frame[10:200:4, 10:200:4] = color_bgr("blue")  # 48x48 isolated specks

    report = tool.hsv_report(to_hsv(frame), tool.analyze(frame).masks)

    assert "blue: 0 px counted  (+2304 in range but removed by the noise filter)" in "\n".join(report)


def test_hsv_report_flags_pixels_just_below_the_saturation_limit(tool, monkeypatch):
    from config import COMMAND_COLORS

    (h_lo, s_lo, v_lo), (h_hi, _, v_hi) = COMMAND_COLORS["green"][0]
    washed_out = cv2.cvtColor(
        np.uint8([[[(h_lo + h_hi) // 2, s_lo - 10, (v_lo + v_hi) // 2]]]), cv2.COLOR_HSV2BGR
    )[0, 0]
    frame = blank_frame()
    frame[0:20, 0:20] = washed_out

    report = tool.hsv_report(to_hsv(frame), tool.analyze(frame).masks)

    green_near_miss = report[report.index(next(l for l in report if "green:" in l)) + 2]
    assert "S 400 px" in green_near_miss


def test_main_writes_the_debug_picture_and_prints_the_result(tool, green_card, tmp_path, capsys):
    out_dir = tmp_path / "out"

    assert tool.main([str(green_card), "--out-dir", str(out_dir)]) == 0

    picture = cv2.imread(str(out_dir / "green_right_card_debug.png"))
    assert picture is not None
    assert picture.shape[1] == IMAGE_WIDTH * 2  # resized to the configured frame size
    out = capsys.readouterr().out
    assert f"({IMAGE_WIDTH}x{IMAGE_HEIGHT})" in out
    assert "result: 'green' at" in out


def test_no_resize_keeps_the_original_size(tool, green_card, tmp_path, capsys):
    assert tool.main([str(green_card), "-o", str(tmp_path), "--no-resize"]) == 0

    picture = cv2.imread(str(tmp_path / "green_right_card_debug.png"))
    assert picture.shape[1] == 320 * 2
    assert "(320x240)" in capsys.readouterr().out


def test_missing_image_is_reported_and_the_rest_still_run(tool, green_card, tmp_path, capsys):
    status = tool.main([str(tmp_path / "nope.png"), str(green_card), "-o", str(tmp_path)])

    assert status == 1
    assert "could not read image" in capsys.readouterr().err
    assert (tmp_path / "green_right_card_debug.png").exists()


def test_inputs_with_the_same_name_do_not_overwrite_each_other(tool, green_card, tmp_path):
    other = tmp_path / "elsewhere"
    other.mkdir()
    blue = blank_frame(240, 320)
    blue[0:100, 0:100] = color_bgr("blue")
    cv2.imwrite(str(other / green_card.name), blue)
    out_dir = tmp_path / "out"

    assert tool.main([str(green_card), str(other / green_card.name), "-o", str(out_dir)]) == 0

    assert sorted(p.name for p in out_dir.iterdir()) == [
        "green_right_card_2_debug.png",
        "green_right_card_debug.png",
    ]


def test_runs_as_a_command_from_another_directory(green_card, tmp_path):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(green_card), "-o", "out"],
        cwd=tmp_path,  # not the repo root: the script must find config/vision itself
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    assert "result: 'green' at" in result.stdout
    assert (tmp_path / "out" / "green_right_card_debug.png").exists()
