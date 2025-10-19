"""Tests for mkiso script."""

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import containers.mkiso.script as script  # noqa: E402


def test_stdout_is_output_filename(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "a.txt").write_text("hi")
    out_dir = tmp_path / "out"
    argv = [
        "script.py",
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
