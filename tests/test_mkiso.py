"""Tests for mkiso."""

import importlib.util
import sys
from pathlib import Path
from typing import Any

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "mkiso.py"
_SPEC = importlib.util.spec_from_file_location("mkiso", _SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
script = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(script)


def test_stdout_is_output_filename(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "a.txt").write_text("hi")
    out_dir = tmp_path / "out"
    argv = [
        "mkiso.py",
        "--src-dir",
        str(src_dir),
        "--out-dir",
        str(out_dir),
        "--out-file",
        "foo.iso",
    ]
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setattr(script, "run_genisoimage", lambda src, lbl, out: None)
    script.main()
    captured = capsys.readouterr()
    assert captured.out.strip() == "foo.iso"


def test_resolve_out_path_deduplicates(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    first = script.resolve_out_path(str(out_dir), "image")
    Path(first).write_text("stub")
    second = script.resolve_out_path(str(out_dir), "image")
    assert first != second
    assert second.endswith("image_1.iso")


def test_resolve_out_file_handles_absolute(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    target = tmp_path / "custom" / "disk"
    result = script.resolve_out_file(str(out_dir), str(target))
    assert result.endswith("disk.iso")
    assert Path(result).exists() is False
    assert Path(result).parent == target.parent
