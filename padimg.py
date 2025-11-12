"""Pad an image to a target aspect ratio by adding gray bars."""

from __future__ import annotations

import argparse
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from PIL import Image, ImageOps

Color = int | tuple[int, int] | tuple[int, int, int] | tuple[int, int, int, int]
_SUPPORTED_PASTE_MODES: Final = {"RGB", "RGBA", "L", "LA"}


def parse_ratio(value: str) -> float:
    """Parse aspect ratio values like "4:5", "1080x1350", or "0.8"."""

    text = value.strip().lower()
    if ":" in text:
        return _parse_ratio_pair(text, ":")
    if "x" in text:
        return _parse_ratio_pair(text, "x")

    ratio = float(text)
    if ratio <= 0:
        raise ValueError("ratio must be positive")
    return ratio


def _parse_ratio_pair(value: str, separator: str) -> float:
    lhs, rhs = value.split(separator, 1)
    first, second = float(lhs), float(rhs)
    if first <= 0 or second <= 0:
        raise ValueError("ratio components must be positive")
    return first / second


@dataclass(frozen=True)
class CanvasSpec:
    width: int
    height: int
    offset_x: int
    offset_y: int


def compute_canvas(width: int, height: int, target_ratio: float) -> CanvasSpec:
    """Return canvas dimensions and paste offsets for padding."""

    new_height = math.ceil(width / target_ratio)
    if new_height >= height:
        pad_total = new_height - height
        return CanvasSpec(
            width=width, height=new_height, offset_x=0, offset_y=pad_total // 2
        )

    new_width = math.ceil(height * target_ratio)
    pad_total = new_width - width
    return CanvasSpec(
        width=new_width, height=height, offset_x=pad_total // 2, offset_y=0
    )


def make_background(gray: int, mode: str) -> Color:
    level = max(0, min(255, int(gray)))
    if mode == "RGBA":
        return (level, level, level, 255)
    if mode == "LA":
        return (level, 255)
    if mode == "L":
        return level
    return (level, level, level)


def pad_image(image: Image.Image, ratio: float, gray: int) -> Image.Image:
    """Return a padded copy of *image* to match the target *ratio*."""

    if image.mode not in _SUPPORTED_PASTE_MODES:
        image = image.convert("RGB")

    spec = compute_canvas(*image.size, ratio)
    background = make_background(gray, image.mode)
    canvas = Image.new(image.mode, (spec.width, spec.height), background)
    canvas.paste(image, (spec.offset_x, spec.offset_y))
    return canvas


def resolve_output_path(input_path: Path, supplied_output: str | None) -> Path:
    if supplied_output:
        return Path(supplied_output)

    stem, ext = os.path.splitext(input_path.name)
    extension = ext or ".jpg"
    return input_path.with_name(f"{stem}_padded{extension}")


def run_cli(argv: list[str] | None = None) -> Path:
    parser = argparse.ArgumentParser(
        description="Pad an image to a target aspect ratio with gray bars."
    )
    parser.add_argument("input", help="Path to input image")
    parser.add_argument(
        "output", nargs="?", help="Optional output path; defaults to *_padded.<ext>"
    )
    parser.add_argument(
        "--ratio",
        default="4:5",
        help="Target aspect ratio (W:H, float, or WxH). Default: 4:5",
    )
    parser.add_argument(
        "--gray",
        type=int,
        default=128,
        help="Gray level for bars (0–255). Default: 128",
    )

    args = parser.parse_args(argv)

    try:
        target_ratio = parse_ratio(args.ratio)
    except Exception as exc:  # pragma: no cover - argparse error path
        raise SystemExit(
            "error: --ratio must be W:H, WxH, or a positive float (e.g., 4:5, 1080x1350, 0.8)"
        ) from exc

    image_path = Path(args.input)
    image = Image.open(image_path)
    image = ImageOps.exif_transpose(image)
    padded = pad_image(image, target_ratio, args.gray)

    output_path = resolve_output_path(image_path, args.output)
    if output_path.suffix.lower() in {".jpg", ".jpeg"} and padded.mode in {
        "RGBA",
        "LA",
    }:
        padded = padded.convert("RGB")

    padded.save(output_path, quality=95)
    print(output_path)
    return output_path


def main() -> None:
    run_cli()


if __name__ == "__main__":  # pragma: no cover - entrypoint
    main()
