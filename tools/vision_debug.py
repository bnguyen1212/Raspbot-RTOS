#!/usr/bin/env python3
"""Run the vision pipeline on image files and save an annotated picture of it.

    python tools/vision_debug.py tests/sample_images/green_center_near.png
    python tools/vision_debug.py tests/sample_images/*.png --out-dir debug_out

For each image this:

1. loads it the way `main.py --image` does (scheduler.camera.StaticImage,
   resized to config.IMAGE_WIDTH x IMAGE_HEIGHT, since MIN_PIXEL_THRESHOLD
   assumes that size; --no-resize keeps the original size),
2. runs the real ColorCounter and ColorLocator on it,
3. prints the counts, the result, and per-color HSV statistics for tuning
   config.COMMAND_COLORS,
4. saves <out-dir>/<name>_debug.png: the frame with the result, the centroid
   marker and the centering deadband, plus one panel per color showing which
   pixels matched.

The HSV statistics show, for each color:
- how many in-range pixels the noise filter (MASK_OPEN_KERNEL_PX) removed,
- for each of the color's ranges separately, the min / median / max H, S
  and V of the counted pixels, and
- near misses: pixels with the right hue that were rejected only because S
  or V was a little below the range's lower bound. A large count there,
  together with the color panel showing holes in the card, usually means
  the S or V limit is too strict (glare on glossy cards washes the color
  toward white, which lowers S; shadows lower V).

This is a development tool: it touches no hardware.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import NamedTuple

import cv2
import numpy as np

# Run as `python tools/vision_debug.py`, Python puts tools/ (not the repo
# root) on sys.path. Add the repo root so `config`, `scheduler` and `vision`
# can be imported.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config import (  # noqa: E402
    CENTER_DEADBAND_PX,
    COMMAND_COLORS,
    IMAGE_CENTER_X,
    IMAGE_HEIGHT,
    IMAGE_WIDTH,
    MIN_PIXEL_THRESHOLD,
    TRACKED_COLORS,
    Position,
)
from scheduler.camera import StaticImage  # noqa: E402
from vision.color_counter import ColorCounter  # noqa: E402
from vision.color_locator import ColorLocator  # noqa: E402
from vision.hsv_mask import color_mask, to_hsv  # noqa: E402

# Drawing colors (BGR) for the annotations.
MARKER_BGR = {"green": (0, 255, 0), "blue": (255, 128, 0), "red": (0, 0, 255)}
DEFAULT_MARKER_BGR = (255, 0, 255)
TEXT_BGR = (255, 255, 255)
GUIDE_BGR = (0, 255, 255)

# How far below a range's lower S or V bound a pixel may be to count as a
# near miss in hsv_report().
NEAR_MISS_MARGIN = 40


class Analysis(NamedTuple):
    """Everything the tool computes for one frame."""

    counts: dict[str, int]
    winning_color: str | None
    position: Position | None
    masks: dict[str, np.ndarray]  # the exact masks ColorCounter counted


def analyze(frame: np.ndarray) -> Analysis:
    """Run ColorCounter and ColorLocator on `frame`, and keep every color's mask.

    Args:
        frame: numpy.ndarray, a BGR frame, shape (H, W, 3), dtype uint8.

    Returns:
        Analysis with the pipeline's real output and the per-color masks.
    """
    counts = ColorCounter(frame)
    winning_color, position = ColorLocator(counts, frame)
    hsv = to_hsv(frame)
    masks = {color: color_mask(hsv, COMMAND_COLORS[color]) for color in TRACKED_COLORS}
    return Analysis(counts, winning_color, position, masks)


def hsv_report(hsv: np.ndarray, masks: dict[str, np.ndarray]) -> list[str]:
    """Per-color HSV statistics to help tune config.COMMAND_COLORS.

    Statistics are given separately for each of a color's ranges. Pooling
    them would be meaningless for red, whose two ranges sit at opposite ends
    of the hue circle (hues 2 and 176 would give a "median" of 89, which is
    green).

    Args:
        hsv: numpy.ndarray, the HSV frame (vision.hsv_mask.to_hsv).
        masks: dict[str, numpy.ndarray], each color's counted (opened) mask,
            from analyze().

    Returns:
        list[str], printable lines.
    """
    h, s, v = (hsv[..., i].astype(np.int16) for i in range(3))
    lines = []
    for color in TRACKED_COLORS:
        counted = masks[color] > 0
        raw = color_mask(hsv, COMMAND_COLORS[color], open_kernel_px=1) > 0
        lines.append(
            f"  {color:>5}: {int(counted.sum())} px counted"
            f"  (+{int((raw & ~counted).sum())} in range but removed by the noise filter)"
        )
        for (h_lo, s_lo, v_lo), (h_hi, s_hi, v_hi) in COMMAND_COLORS[color]:
            hue_ok = (h >= h_lo) & (h <= h_hi)
            s_ok = (s >= s_lo) & (s <= s_hi)
            v_ok = (v >= v_lo) & (v <= v_hi)
            label = f"    H {h_lo}-{h_hi} S {s_lo}-{s_hi} V {v_lo}-{v_hi}:"
            matched = hsv[counted & hue_ok & s_ok & v_ok]
            if len(matched):
                low, mid, high = (
                    tuple(np.percentile(matched, q, axis=0).astype(int).tolist()) for q in (0, 50, 100)
                )
                stats = f"{len(matched)} px, H/S/V min {low} median {mid} max {high}"
            else:
                stats = "no counted pixels"
            # Near misses: hue in range and one of S/V in range, but the other
            # just below its lower bound (by at most NEAR_MISS_MARGIN).
            s_short = hue_ok & v_ok & (s < s_lo) & (s >= s_lo - NEAR_MISS_MARGIN)
            v_short = hue_ok & s_ok & (v < v_lo) & (v >= v_lo - NEAR_MISS_MARGIN)
            lines.append(f"{label} {stats}")
            lines.append(
                f"      near misses (within {NEAR_MISS_MARGIN} below the lower bound): "
                f"S {int(s_short.sum())} px, V {int(v_short.sum())} px"
            )
    return lines


def _label(image: np.ndarray, lines: list[str]) -> None:
    """Write `lines` at the top-left of `image`, on a dark band for contrast."""
    scale = max(image.shape[1] / 640, 0.5) * 0.55
    line_height = int(22 * scale / 0.55)
    band = image[: line_height * len(lines) + 8]
    band[:] = (band * 0.35).astype(np.uint8)
    for i, text in enumerate(lines):
        org = (6, line_height * (i + 1))
        cv2.putText(image, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, TEXT_BGR, 1, cv2.LINE_AA)


def render(frame: np.ndarray, analysis: Analysis) -> np.ndarray:
    """Build the debug picture: the annotated frame plus one panel per color.

    Panels are laid out in a grid two wide. The first panel is the frame with
    the centering guides (config.IMAGE_CENTER_X and the deadband, scaled if
    the frame isn't the configured width) and a marker at the centroid. Each
    color panel shows the frame dimmed, with that color's matching pixels at
    full brightness.

    Args:
        frame: numpy.ndarray, the BGR frame that was analyzed.
        analysis: the result of analyze(frame).

    Returns:
        numpy.ndarray, a BGR image.
    """
    height, width = frame.shape[:2]

    overview = frame.copy()
    scale_x = width / IMAGE_WIDTH  # guides are defined for the configured width
    center_x = round(IMAGE_CENTER_X * scale_x)
    deadband = round(CENTER_DEADBAND_PX * scale_x)
    cv2.line(overview, (center_x, 0), (center_x, height - 1), GUIDE_BGR, 1)
    for edge in (center_x - deadband, center_x + deadband):
        for y in range(0, height, 12):  # dashed
            cv2.line(overview, (edge, y), (edge, min(y + 5, height - 1)), GUIDE_BGR, 1)

    if analysis.winning_color is None:
        result = f"IDLE (no color >= {MIN_PIXEL_THRESHOLD} px)"
    else:
        x, y = analysis.position
        marker = MARKER_BGR.get(analysis.winning_color, DEFAULT_MARKER_BGR)
        point = (round(x), round(y))
        # White cross on a black outline, so it shows on any card color; the
        # ring around it is in the winning color.
        cv2.drawMarker(overview, point, (0, 0, 0), cv2.MARKER_CROSS, 34, 5)
        cv2.drawMarker(overview, point, TEXT_BGR, cv2.MARKER_CROSS, 30, 2)
        cv2.circle(overview, point, 20, (0, 0, 0), 4)
        cv2.circle(overview, point, 20, marker, 2)
        error = x - center_x
        side = "centered" if abs(error) <= deadband else ("right" if error > 0 else "left")
        result = f"{analysis.winning_color.upper()} at ({x:.1f}, {y:.1f})  x-error {error:+.1f} ({side})"
    _label(overview, ["result: " + result])

    panels = [overview]
    dimmed = (frame * 0.25).astype(np.uint8)
    for color in TRACKED_COLORS:
        mask = analysis.masks[color]
        panel = dimmed.copy()
        panel[mask > 0] = frame[mask > 0]
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(panel, contours, -1, MARKER_BGR.get(color, DEFAULT_MARKER_BGR), 1)
        tag = "  WINNER" if color == analysis.winning_color else ""
        _label(panel, [f"{color}: {analysis.counts[color]} px{tag}"])
        panels.append(panel)

    if len(panels) % 2:
        panels.append(np.zeros_like(frame))
    rows = [np.hstack(panels[i : i + 2]) for i in range(0, len(panels), 2)]
    return np.vstack(rows)


def load_frame(path: str, resize: bool) -> np.ndarray:
    """Load an image as the loop would see it.

    Raises:
        FileNotFoundError: if the file is missing or isn't a readable image.
    """
    if resize:
        return StaticImage(path, IMAGE_WIDTH, IMAGE_HEIGHT).read()
    frame = cv2.imread(path, cv2.IMREAD_COLOR)
    if frame is None:
        raise FileNotFoundError(f"could not read image: {path}")
    return frame


def unique_out_path(out_dir: Path, stem: str, taken: set[Path]) -> Path:
    """<out_dir>/<stem>_debug.png, or <stem>_2_debug.png, ... if this run
    already wrote that name (two inputs with the same stem)."""
    path = out_dir / f"{stem}_debug.png"
    n = 2
    while path in taken:
        path = out_dir / f"{stem}_{n}_debug.png"
        n += 1
    return path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run ColorCounter/ColorLocator on images and save annotated debug pictures."
    )
    parser.add_argument("images", nargs="+", metavar="IMAGE", help="image file(s) to analyze")
    parser.add_argument(
        "-o",
        "--out-dir",
        default=".",
        metavar="DIR",
        help="where to save <name>_debug.png (default: current directory; created if missing)",
    )
    parser.add_argument(
        "--no-resize",
        action="store_true",
        help=f"keep the original size instead of resizing to {IMAGE_WIDTH}x{IMAGE_HEIGHT} like main.py",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Analyze each image; return 0 if all succeeded, 1 if any failed."""
    args = parse_args(argv)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    failures = 0
    written: set[Path] = set()
    for path in args.images:
        try:
            frame = load_frame(path, resize=not args.no_resize)
        except FileNotFoundError as error:
            print(f"error: {error}", file=sys.stderr)
            failures += 1
            continue

        analysis = analyze(frame)
        out_path = unique_out_path(out_dir, Path(path).stem, written)
        written.add(out_path)
        if not cv2.imwrite(str(out_path), render(frame, analysis)):
            print(f"error: could not write {out_path}", file=sys.stderr)
            failures += 1
            continue

        height, width = frame.shape[:2]
        print(f"{path}  ({width}x{height})")
        print(f"  counts: {analysis.counts}  (threshold {MIN_PIXEL_THRESHOLD})")
        if analysis.winning_color is None:
            print("  result: idle (None, None)")
        else:
            x, y = analysis.position
            print(f"  result: {analysis.winning_color!r} at ({x:.1f}, {y:.1f})")
        for line in hsv_report(to_hsv(frame), analysis.masks):
            print(line)
        print(f"  saved: {out_path}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
