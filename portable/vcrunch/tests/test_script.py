"""Tests for vcrunch script."""

# mypy: ignore-errors

import io
import json
import sys
import types
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import portable.vcrunch.script as script  # noqa: E402


def test_parse_size():
    assert script.parse_size("1") == 1
    assert script.parse_size("1k") == 1024
    assert script.parse_size("1.5m") == int(1.5 * 1024**2)
    assert script.parse_size("2g") == 2 * 1024**3
    assert script.parse_size("3t") == 3 * 1024**4
    assert script.parse_size("1KiB") == 1024


def test_kbps_to_bps():
    assert script.kbps_to_bps("1k") == 1000
    assert script.kbps_to_bps("1.5m") == 1_500_000
    assert script.kbps_to_bps("500") == 500


def test_ffprobe_json(monkeypatch):
    def fake_check_output(cmd):
        assert cmd == ["ffprobe", "file"]
        return b'{"a": 1}'

    monkeypatch.setattr(script.subprocess, "check_output", fake_check_output)
    assert script.ffprobe_json(["ffprobe", "file"]) == {"a": 1}


def test_ffprobe_duration(monkeypatch):
    def fake_ffprobe_json(cmd):
        expected = [
            "ffprobe",
            "-hide_banner",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            "-i",
            "path",
        ]
        assert cmd == expected
        return {"format": {"duration": "12.34"}}

    monkeypatch.setattr(script, "ffprobe_json", fake_ffprobe_json)
    assert script.ffprobe_duration("path") == 12.34


def test_is_valid_media(monkeypatch):
    monkeypatch.setattr(script, "ffprobe_duration", lambda p: 1.0)
    assert script.is_valid_media("file")
    monkeypatch.setattr(
        script, "ffprobe_duration", lambda p: (_ for _ in ()).throw(Exception())
    )
    assert script.is_valid_media("file") is False


def test_run_success(monkeypatch, capsys):
    def fake_run(cmd):
        class R:
            returncode = 0

        return R()

    monkeypatch.setattr(script.subprocess, "run", fake_run)
    script.run(["echo", "hi"])
    err = capsys.readouterr().err
    assert "+ echo hi" in err


def test_run_failure(monkeypatch):
    def fake_run(cmd):
        class R:
            returncode = 1

        return R()

    monkeypatch.setattr(script.subprocess, "run", fake_run)
    with pytest.raises(SystemExit) as exc:
        script.run(["bad"])
    assert exc.value.code == 1


def test_collect_all_files(tmp_path):
    (tmp_path / "a.txt").write_text("a")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.txt").write_text("b")
    (sub / "c.log").write_text("c")
    paths = [str(tmp_path), str(tmp_path / "a.txt")]
    result = script.collect_all_files(paths, "*.txt")
    expected = sorted([str(tmp_path / "a.txt"), str(sub / "b.txt")])
    assert result == expected


def test_read_paths_from_file(tmp_path):
    f = tmp_path / "paths.txt"
    f.write_text("a\n\n b \n")
    assert script.read_paths_from(str(f)) == ["a", "b"]


def test_read_paths_from_stdin(monkeypatch):
    monkeypatch.setattr(script.sys, "stdin", io.StringIO("x\ny\n"))
    assert script.read_paths_from("-") == ["x", "y"]


def test_sanitize_base():
    assert script.sanitize_base(".foo") == "foo"
    assert script.sanitize_base("..\\bar") == "_bar"
    assert script.sanitize_base("") == "file"


def test_now_utc_iso_format():
    s = script.now_utc_iso()
    datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")


def test_load_manifest_new(monkeypatch, tmp_path):
    monkeypatch.setattr(script, "now_utc_iso", lambda: "TS")
    path = tmp_path / "m.json"
    assert script.load_manifest(str(path)) == {
        "version": 1,
        "updated": "TS",
        "items": {},
    }


def test_load_manifest_existing(monkeypatch, tmp_path):
    monkeypatch.setattr(script, "now_utc_iso", lambda: "TS")
    path = tmp_path / "m.json"
    path.write_text('{"foo": 1}')
    assert script.load_manifest(str(path)) == {"foo": 1, "items": {}}


def test_load_manifest_invalid(monkeypatch, tmp_path):
    monkeypatch.setattr(script, "now_utc_iso", lambda: "TS")
    path = tmp_path / "m.json"
    path.write_text("not json")
    assert script.load_manifest(str(path)) == {
        "version": 1,
        "updated": "TS",
        "items": {},
    }


def test_save_manifest(monkeypatch, tmp_path):
    monkeypatch.setattr(script, "now_utc_iso", lambda: "TS2")
    path = tmp_path / "m.json"
    manifest = {"version": 1, "updated": "old", "items": {}}
    script.save_manifest(manifest, str(path))
    assert manifest["updated"] == "TS2"
    data = json.loads(path.read_text())
    assert data["updated"] == "TS2"


def test_src_key():
    st = types.SimpleNamespace(st_size=123, st_mtime=456.7)
    assert script.src_key("/abs", st) == "/abs|123|456"


def test_all_videos_done(monkeypatch):
    manifest = {"items": {"1": {"type": "video", "output": "a.mkv", "status": "done"}}}
    monkeypatch.setattr(script.os.path, "exists", lambda p: True)
    monkeypatch.setattr(script, "is_valid_media", lambda p: True)
    assert script.all_videos_done(manifest, "/out") is True
    manifest["items"]["1"]["status"] = "pending"
    assert script.all_videos_done(manifest, "/out") is False
    assert script.all_videos_done({"items": {}}, "/out") is False


def test_copy_if_fits(monkeypatch, tmp_path):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "a.mp4").write_text("a")
    (src_dir / "b.txt").write_text("b")
    out_dir = tmp_path / "out"
    argv = [
        "script.py",
        "--input",
        str(src_dir),
        "--target-size",
        "1M",
        "--output-dir",
        str(out_dir),
    ]
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setattr(
        script,
        "ffprobe_duration",
        lambda p: (_ for _ in ()).throw(Exception("ffprobe")),
    )
    monkeypatch.setattr(
        script, "run", lambda cmd: (_ for _ in ()).throw(Exception("run"))
    )
    script.main()
    assert (out_dir / "a.mp4").exists()
    assert (out_dir / "b.txt").exists()
    assert (src_dir / "a.mp4").exists()
    manifest = json.loads((out_dir / ".job.json").read_text())
    assert len(manifest["items"]) == 1
    rec = next(iter(manifest["items"].values()))
    assert rec["status"] == "done"


def test_move_if_fits(monkeypatch, tmp_path):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    video = src_dir / "a.mp4"
    video.write_text("a")
    out_dir = tmp_path / "out"
    argv = [
        "script.py",
        "--input",
        str(src_dir),
        "--target-size",
        "1M",
        "--output-dir",
        str(out_dir),
        "--move-if-fit",
    ]
    monkeypatch.setattr(sys, "argv", argv)
    script.main()
    assert not video.exists()
    assert (out_dir / "a.mp4").exists()
