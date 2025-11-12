"""Tests for padimg script."""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from typing import Any

from PIL import Image

pytest = importlib.import_module("pytest")

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "padimg.py"
_SPEC = importlib.util.spec_from_file_location("padimg", _SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
padimg: Any = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = padimg
_SPEC.loader.exec_module(padimg)


def test_parse_ratio_formats() -> None:
    assert padimg.parse_ratio("4:5") == pytest.approx(0.8)
    assert padimg.parse_ratio("1080x1350") == pytest.approx(0.8)
    assert padimg.parse_ratio("0.5") == pytest.approx(0.5)


def test_parse_ratio_invalid() -> None:
    for value in ["0:5", "4:0", "0", "-1", "foo"]:
        with pytest.raises(Exception):
            padimg.parse_ratio(value)


def test_compute_canvas_vertical_padding() -> None:
    spec = padimg.compute_canvas(100, 90, 0.8)
    assert spec.width == 100
    assert spec.height == 125
    assert spec.offset_x == 0
    assert spec.offset_y == 17


def test_compute_canvas_horizontal_padding() -> None:
    spec = padimg.compute_canvas(80, 100, 1.5)
    assert spec.width == 150
    assert spec.height == 100
    assert spec.offset_x == 35
    assert spec.offset_y == 0


def test_make_background() -> None:
    cases = [
        (0, "RGB", (0, 0, 0)),
        (255, "RGBA", (255, 255, 255, 255)),
        (200, "LA", (200, 255)),
        (128, "L", 128),
    ]
    for gray, mode, expected in cases:
        assert padimg.make_background(gray, mode) == expected


def test_pad_image_adds_bars() -> None:
    image = Image.new("RGB", (100, 100), (10, 20, 30))
    padded = padimg.pad_image(image, ratio=0.8, gray=200)
    assert padded.size == (100, 125)
    assert padded.getpixel((0, 0)) == (200, 200, 200)
    assert padded.getpixel((50, 62)) == (10, 20, 30)


def test_run_cli_writes_expected_output(tmp_path: Path) -> None:
    input_path = tmp_path / "sample.png"
    Image.new("RGBA", (60, 40), (10, 10, 10, 255)).save(input_path)

    output = padimg.run_cli([str(input_path), "--ratio", "2:1", "--gray", "32"])

    assert output.name == "sample_padded.png"
    assert output.exists()
    with Image.open(output) as result:
        assert result.size == (80, 40)
        assert result.mode == "RGBA"
        assert result.getpixel((0, 20)) == (32, 32, 32, 255)
        assert result.getpixel((40, 20)) == (10, 10, 10, 255)
