"""Tests for qcut script."""

# mypy: ignore-errors

import importlib.util
import time
from datetime import datetime
from pathlib import Path
from typing import Any

_MODULE_PATH = Path(__file__).resolve().parents[1] / "qcut.py"
_SPEC = importlib.util.spec_from_file_location("qcut", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
qcut = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(qcut)


def test_epoch_from_filename_matches_timestamp() -> None:
    ts = qcut.epoch_from_filename("20240102_030405.mp4")
    expected = int(time.mktime(datetime(2024, 1, 2, 3, 4, 5).timetuple()))
    assert ts == expected


def test_build_len_slots_respects_target() -> None:
    slots = qcut.build_len_slots(target_sec=25, min_slot_sec=5, max_slot_sec=10)
    assert sum(slots) == 25
    assert all(5 <= s <= 10 for s in slots)


def test_quotas_like_zsh_respects_minimum_seconds() -> None:
    durations = [1.0, 12.0, 30.0]
    quotas = qcut.quotas_like_zsh(durations, slot_count=5, min_seconds=10)
    assert sum(quotas) == 5
    assert quotas[0] <= 1
    assert quotas[1] >= 1
    assert quotas[2] >= 1


def test_manifest_save_and_load_round_trip(tmp_path: Path) -> None:
    data: dict[str, Any] = {"plan": {"svt_lp": 4}}
    qcut.save_manifest(str(tmp_path), data)
    loaded = qcut.load_manifest(str(tmp_path))
    assert loaded["plan"]["svt_lp"] == 4
    assert "updated" in loaded
    manifest_file = Path(qcut.manifest_path(str(tmp_path)))
    assert manifest_file.exists()


def test_load_manifest_returns_empty_when_missing(tmp_path: Path) -> None:
    manifest = qcut.load_manifest(str(tmp_path))
    assert manifest == {}


def test_build_drawtext_pts_includes_font_and_epoch() -> None:
    draw = qcut.build_drawtext_pts("/fonts/test.ttf", 1_700_000_000)
    assert "fontfile=/fonts/test.ttf" in draw
    assert "basetime=1700000000000000" in draw


def test_walk_video_files_filters_extensions(tmp_path: Path) -> None:
    (tmp_path / "clip1.mp4").write_text("")
    (tmp_path / "clip2.MKV").write_text("")
    (tmp_path / "notes.txt").write_text("")
    videos = qcut.walk_video_files(str(tmp_path))
    assert videos == [str(tmp_path / "clip1.mp4"), str(tmp_path / "clip2.MKV")]
