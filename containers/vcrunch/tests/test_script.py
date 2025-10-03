"""Tests for vcrunch script."""

# mypy: ignore-errors

import io
import json
import os
import subprocess
import sys
import types
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import containers.vcrunch.script as script  # noqa: E402


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
    def fake_run(cmd, check, stdout, stderr):
        assert cmd == ["ffprobe", "file"]
        assert check is True
        assert stdout is script.subprocess.PIPE
        assert stderr is script.subprocess.PIPE

        class Result:
            def __init__(self) -> None:
                self.stdout = b'{"a": 1}'
                self.stderr = b""

        return Result()

    monkeypatch.setattr(script.subprocess, "run", fake_run)
    assert script.ffprobe_json(["ffprobe", "file"]) == {"a": 1}


def test_ffprobe_duration(monkeypatch):
    monkeypatch.setattr(script, "probe_media_info", lambda path: {"duration": 12.34})
    assert script.ffprobe_duration("path") == 12.34

    monkeypatch.setattr(script, "probe_media_info", lambda path: {"duration": None})
    with pytest.raises(ValueError):
        script.ffprobe_duration("path")


def test_probe_media_info_uses_stream_duration(monkeypatch):
    expected = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_streams",
        "-show_format",
        "path",
    ]

    def fake_ffprobe_json(cmd):
        assert cmd == expected
        return {
            "format": {"format_name": "matroska"},
            "streams": [
                {
                    "codec_type": "video",
                    "duration": "12.5",
                }
            ],
        }

    monkeypatch.setattr(script, "ffprobe_json", fake_ffprobe_json)
    info = script.probe_media_info("path")
    assert info["is_video"] is True
    assert info["duration"] == pytest.approx(12.5)


def test_probe_media_info_zero_duration_is_still(monkeypatch):
    def fake_ffprobe_json(cmd):
        return {
            "streams": [
                {
                    "codec_type": "video",
                    "duration": "0",
                }
            ]
        }

    monkeypatch.setattr(script, "ffprobe_json", fake_ffprobe_json)
    info = script.probe_media_info("photo.jpg")
    assert info["is_video"] is False
    assert info["duration"] is None


def test_probe_media_info_detects_image_container(monkeypatch):
    expected = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_streams",
        "-show_format",
        "still.png",
    ]

    def fake_ffprobe_json(cmd):
        assert cmd == expected
        return {
            "format": {"format_name": "image2"},
            "streams": [
                {
                    "codec_type": "video",
                    "duration": "1.0",
                }
            ],
        }

    monkeypatch.setattr(script, "ffprobe_json", fake_ffprobe_json)
    info = script.probe_media_info("still.png")
    assert info == {"is_video": False, "duration": None}


def test_probe_media_info_attached_picture(monkeypatch):
    def fake_ffprobe_json(cmd):
        return {
            "streams": [
                {
                    "codec_type": "video",
                    "duration": "5",
                    "disposition": {"attached_pic": 1},
                }
            ]
        }

    monkeypatch.setattr(script, "ffprobe_json", fake_ffprobe_json)
    info = script.probe_media_info("cover.mkv")
    assert info["is_video"] is False
    assert info["duration"] is None


def test_probe_media_info_failure(monkeypatch):
    err = subprocess.CalledProcessError(1, ["ffprobe"], output=b"", stderr=b"bad")

    def fake_ffprobe_json(cmd):
        raise err

    monkeypatch.setattr(script, "ffprobe_json", fake_ffprobe_json)
    info = script.probe_media_info("bad")
    assert info["is_video"] is False
    assert info["duration"] is None
    assert info["error"] == "bad"


def test_is_valid_media(monkeypatch):
    monkeypatch.setattr(script, "ffprobe_duration", lambda p: 1.0)
    assert script.is_valid_media("file")
    monkeypatch.setattr(
        script, "ffprobe_duration", lambda p: (_ for _ in ()).throw(Exception())
    )
    assert script.is_valid_media("file") is False


def test_has_video_stream(monkeypatch):
    monkeypatch.setattr(script, "probe_media_info", lambda path: {"is_video": True})
    assert script.has_video_stream("path") is True

    monkeypatch.setattr(script, "probe_media_info", lambda path: {"is_video": False})
    assert script.has_video_stream("path") is False


def test_is_video_file(monkeypatch):
    calls: list[str] = []

    def fake_has_video_stream(path: str) -> bool:
        calls.append(path)
        return path.endswith(".custom")

    monkeypatch.setattr(script, "has_video_stream", fake_has_video_stream)

    assert script.is_video_file("/tmp/image.JPG") is False
    assert script.is_video_file("/tmp/video.mp4") is False
    assert script.is_video_file("/tmp/video.custom") is True
    assert script.is_video_file("/tmp/asset.bin") is False
    assert calls == [
        "/tmp/image.JPG",
        "/tmp/video.mp4",
        "/tmp/video.custom",
        "/tmp/asset.bin",
    ]


def test_copy_assets_skips_done(tmp_path):
    src = tmp_path / "asset.bin"
    src.write_text("source-new")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    dest = out_dir / "asset.bin"
    dest.write_text("existing")

    manifest_path = tmp_path / "manifest.json"
    manifest = {
        "items": {},
        "probes": {},
    }

    st = src.stat()
    key = script.src_key(str(src.resolve()), st)
    manifest["items"][key] = {
        "type": "asset",
        "src": str(src),
        "output": "asset.bin",
        "status": "done",
        "finished_at": "2024-01-01T00:00:00Z",
    }

    results = script.copy_assets(
        [str(src)],
        str(out_dir),
        manifest=manifest,
        manifest_path=str(manifest_path),
    )

    assert dest.read_text() == "existing"
    assert results == [(str(src), "asset.bin")]


def test_has_data_stream(monkeypatch):
    expected_cmd = [
        "ffprobe",
        "-hide_banner",
        "-v",
        "error",
        "-show_entries",
        "stream=codec_type",
        "-of",
        "json",
        "sample.mkv",
    ]

    def fake_ffprobe_with_data(cmd):
        assert cmd == expected_cmd
        return {"streams": [{"codec_type": "data"}]}

    monkeypatch.setattr(script, "ffprobe_json", fake_ffprobe_with_data)
    assert script.has_data_stream("sample.mkv") is True

    monkeypatch.setattr(script, "ffprobe_json", lambda cmd: {"streams": []})
    assert script.has_data_stream("sample.mkv") is False

    def raise_called_process_error(cmd):
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(script, "ffprobe_json", raise_called_process_error)
    assert script.has_data_stream("sample.mkv") is False


def test_muxer_for_extension():
    assert script._muxer_for_extension(".mkv") == "matroska"
    assert script._muxer_for_extension(".webm") == "webm"
    assert script._muxer_for_extension(".mp4") == "mp4"
    assert script._muxer_for_extension(".m2ts") == "mpegts"
    assert script._muxer_for_extension(".unknown") == "unknown"


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
    (sub / "._ignored.txt").write_text("meta")
    paths = [str(tmp_path), str(tmp_path / "a.txt")]
    result = script.collect_all_files(paths, "*.txt")
    expected = sorted([str(tmp_path / "a.txt"), str(sub / "b.txt")])
    assert result == expected


def test_collect_all_files_skips_dot_underscore(tmp_path):
    (tmp_path / "._video.mp4").write_text("meta")
    (tmp_path / "video.mp4").write_text("data")
    result = script.collect_all_files([str(tmp_path)], None)
    assert str(tmp_path / "video.mp4") in result
    assert str(tmp_path / "._video.mp4") not in result


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
        "probes": {},
    }


def test_load_manifest_existing(monkeypatch, tmp_path):
    monkeypatch.setattr(script, "now_utc_iso", lambda: "TS")
    path = tmp_path / "m.json"
    path.write_text('{"foo": 1}')
    assert script.load_manifest(str(path)) == {"foo": 1, "items": {}, "probes": {}}


def test_load_manifest_invalid(monkeypatch, tmp_path):
    monkeypatch.setattr(script, "now_utc_iso", lambda: "TS")
    path = tmp_path / "m.json"
    path.write_text("not json")
    assert script.load_manifest(str(path)) == {
        "version": 1,
        "updated": "TS",
        "items": {},
        "probes": {},
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
        "probe_media_info",
        lambda path: {"is_video": path.endswith(".mp4"), "duration": 10.0},
    )
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
    monkeypatch.setattr(
        script,
        "probe_media_info",
        lambda path: {"is_video": path.endswith(".mp4"), "duration": 10.0},
    )
    script.main()
    assert not video.exists()
    assert (out_dir / "a.mp4").exists()


def test_group_outputs_by_target_size(tmp_path):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    files = {
        "a.mkv": 400_000,
        "b.mkv": 400_000,
        "c.txt": 300_000,
    }
    for name, size in files.items():
        path = out_dir / name
        path.write_bytes(b"x" * size)
    manifest = {
        "items": {
            "1": {"type": "video", "output": "a.mkv"},
            "2": {"type": "video", "output": "b.mkv"},
        }
    }
    script.group_outputs_by_target_size(
        str(out_dir),
        manifest,
        ".job.json",
        700_000,
        ["a.mkv", "b.mkv", "c.txt"],
    )
    dir1 = out_dir / "01"
    dir2 = out_dir / "02"
    assert dir1.is_dir()
    assert dir2.is_dir()
    assert sorted(p.name for p in dir1.iterdir()) == ["a.mkv"]
    assert sorted(p.name for p in dir2.iterdir()) == ["b.mkv", "c.txt"]
    assert os.path.normpath(manifest["items"]["1"]["output"]) == os.path.join(
        "01", "a.mkv"
    )
    assert os.path.normpath(manifest["items"]["2"]["output"]) == os.path.join(
        "02", "b.mkv"
    )


def test_constant_quality_groups_and_command(monkeypatch, tmp_path):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    video = src_dir / "a.mp4"
    video.write_bytes(b"v" * (2 * 1024 * 1024))
    asset = src_dir / "notes.txt"
    asset.write_text("notes")
    out_dir = tmp_path / "out"
    stage_dir = tmp_path / "stage"
    stage_dir.mkdir()

    argv = [
        "script.py",
        "--input",
        str(src_dir),
        "--target-size",
        "1M",
        "--output-dir",
        str(out_dir),
        "--stage-dir",
        str(stage_dir),
        "--constant-quality",
        "32",
    ]
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setattr(
        script,
        "probe_media_info",
        lambda path: {
            "is_video": path.endswith(".mp4"),
            "duration": 60.0 if path.endswith(".mp4") else None,
        },
    )

    monkeypatch.setattr(script, "ffprobe_duration", lambda path: 60.0)
    monkeypatch.setattr(script, "has_data_stream", lambda path: False)

    captured_cmds = []

    def fake_run(cmd, env=None):
        captured_cmds.append(cmd)
        stage_part = Path(cmd[-1])
        stage_part.write_bytes(b"encoded")

        class R:
            returncode = 0

        return R()

    monkeypatch.setattr(script.subprocess, "run", fake_run)
    monkeypatch.setattr(script, "is_valid_media", lambda path: True)

    script.main()

    dirs = sorted(p.name for p in out_dir.iterdir() if p.is_dir())
    assert dirs == ["01"]
    bundle = out_dir / "01"
    video_out = bundle / "a.mkv"
    asset_out = bundle / "notes.txt"
    assert video_out.exists()
    assert asset_out.exists()

    manifest_data = json.loads((out_dir / ".job.json").read_text())
    rec = next(iter(manifest_data["items"].values()))
    assert rec["output"].startswith("01" + os.sep)
    cmd = captured_cmds[0]
    assert "-crf" in cmd
    idx = cmd.index("-crf")
    assert cmd[idx + 1] == "32"
    assert cmd[idx + 2] == "-b:v"
    assert cmd[idx + 3] == "0"


def test_sidecar_files_are_renamed(monkeypatch, tmp_path):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    video = src_dir / "a.mp4"
    video.write_bytes(b"v" * (2 * 1024 * 1024))
    sidecar1 = src_dir / "a.mp4.srt"
    sidecar1.write_text("subs")
    sidecar2 = src_dir / "a.mp4.nfo"
    sidecar2.write_text("info")
    other_asset = src_dir / "other.txt"
    other_asset.write_text("other")

    out_dir = tmp_path / "out"
    stage_dir = tmp_path / "stage"
    stage_dir.mkdir()

    argv = [
        "script.py",
        "--input",
        str(src_dir),
        "--target-size",
        "1M",
        "--output-dir",
        str(out_dir),
        "--stage-dir",
        str(stage_dir),
        "--constant-quality",
        "30",
    ]
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setattr(
        script,
        "probe_media_info",
        lambda path: {
            "is_video": path.endswith(".mp4"),
            "duration": 60.0 if path.endswith(".mp4") else None,
        },
    )
    monkeypatch.setattr(script, "ffprobe_duration", lambda path: 60.0)
    monkeypatch.setattr(script, "has_data_stream", lambda path: False)

    def fake_run(cmd, env=None):
        stage_part = Path(cmd[-1])
        stage_part.write_bytes(b"encoded")

        class R:
            returncode = 0

        return R()

    monkeypatch.setattr(script.subprocess, "run", fake_run)
    monkeypatch.setattr(script, "is_valid_media", lambda path: True)

    script.main()

    bundles = sorted(p for p in out_dir.iterdir() if p.is_dir())
    assert len(bundles) == 1
    bundle = bundles[0]

    assert (bundle / "a.mkv").exists()
    assert (bundle / "a.mkv.srt").exists()
    assert (bundle / "a.mkv.nfo").exists()
    assert (bundle / "other.txt").exists()
    assert not (bundle / "a.mp4.srt").exists()
    assert not (bundle / "a.mp4.nfo").exists()
