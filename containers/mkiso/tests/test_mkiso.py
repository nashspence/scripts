"""Tests for mkiso script."""

import os
import sys
from pathlib import Path
from types import SimpleNamespace
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
    called: dict[str, Any] = {}

    def fake_run(src: str, lbl: str, out: str, size: int, media: str) -> None:
        called.update(
            {
                "src": src,
                "label": lbl,
                "out": out,
                "size": size,
                "media": media,
            }
        )

    monkeypatch.setattr(script, "run_mkudffs", fake_run)
    script.main()
    captured = capsys.readouterr()
    assert captured.out.strip() == "foo.iso"
    assert called["media"] == "bdr"


def test_media_type_passthrough(tmp_path: Path, monkeypatch: Any, capsys: Any) -> None:
    src_dir = tmp_path / "src2"
    src_dir.mkdir()
    (src_dir / "file.bin").write_text("data")
    out_dir = tmp_path / "out2"
    argv = [
        "script.py",
        "--src-dir",
        str(src_dir),
        "--out-dir",
        str(out_dir),
        "--out-file",
        "bar.iso",
        "--media-type",
        "cdr",
    ]
    monkeypatch.setattr(sys, "argv", argv)
    recorded: dict[str, Any] = {}

    def fake_run(src: str, lbl: str, out: str, size: int, media: str) -> None:
        recorded["media"] = media

    monkeypatch.setattr(script, "run_mkudffs", fake_run)
    script.main()
    captured = capsys.readouterr()
    assert captured.out.strip() == "bar.iso"
    assert recorded["media"] == "cdr"


def test_run_mkudffs_uses_output_dir(tmp_path: Path, monkeypatch: Any) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "data.bin").write_bytes(b"payload")

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    out_path = out_dir / "disk.iso"

    created_mount_dirs: list[str] = []

    def fake_mkdtemp(prefix: str, dir: str) -> str:
        assert dir == str(out_dir)
        mount_path = Path(dir) / "mkiso-test"
        mount_path.mkdir()
        created_mount_dirs.append(str(mount_path))
        return str(mount_path)

    monkeypatch.setattr("containers.mkiso.script.tempfile.mkdtemp", fake_mkdtemp)

    def fake_copytree(src: str, dst: str, **_: Any) -> None:
        assert Path(src) == src_dir
        assert dst == created_mount_dirs[-1]

    monkeypatch.setattr("containers.mkiso.script.shutil.copytree", fake_copytree)

    def fake_sync() -> None:
        pass

    monkeypatch.setattr("containers.mkiso.script.os.sync", fake_sync)

    def fake_run(cmd: list[str], **_: Any) -> SimpleNamespace:
        if cmd and cmd[0] == "truncate":
            Path(cmd[-1]).touch()
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr("containers.mkiso.script.subprocess.run", fake_run)

    real_rmdir = os.rmdir

    def fake_rmdir(path: Any) -> None:
        assert Path(path) == Path(created_mount_dirs[-1])
        real_rmdir(path)

    monkeypatch.setattr("containers.mkiso.script.os.rmdir", fake_rmdir)

    script.run_mkudffs(str(src_dir), "LABEL", str(out_path), 1024, "bdr")

    assert created_mount_dirs
    assert all(Path(p).parent == out_dir for p in created_mount_dirs)
    assert out_path.exists()
