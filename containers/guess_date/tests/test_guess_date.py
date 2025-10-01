"""Unit tests for guess_date heuristics."""

from __future__ import annotations

import math
import os
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

if "dateutil" not in sys.modules:
    dateutil_module = cast(Any, types.ModuleType("dateutil"))
    parser_module = cast(Any, types.ModuleType("parser"))

    def _parse(value: Any) -> datetime:
        """Minimal parser used in tests when python-dateutil is unavailable."""

        if isinstance(value, datetime):
            return value

        text = str(value).strip()
        if not text:
            raise ValueError("cannot parse empty value")

        if text.endswith("Z"):
            text = text[:-1] + "+00:00"

        try:
            return datetime.fromisoformat(text)
        except ValueError:
            pass

        try:
            return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
        except ValueError as exc:  # pragma: no cover - defensive fallback
            raise exc

    parser_module.parse = _parse
    dateutil_module.parser = parser_module

    sys.modules.setdefault("dateutil", dateutil_module)
    sys.modules.setdefault("dateutil.parser", parser_module)

import containers.guess_date.script as script  # noqa: E402


def test_parse_datetime_value_supports_exif_format() -> None:
    dt, tz_present, frac = script.parse_datetime_value("2024:01:02 03:04:05")
    assert dt == datetime(2024, 1, 2, 3, 4, 5)
    assert not tz_present
    assert not frac


def test_cluster_and_score_groups_close_timestamps() -> None:
    base = datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    candidates = [
        ("exif:DateTimeOriginal", base, 98, True, True),
        ("ffprobe:format:creation_time", base + timedelta(seconds=30), 94, True, False),
        ("fs:mtime", datetime(2024, 1, 2, 3, 5, 0), 60, False, False),
    ]

    agg = script.cluster_and_score(candidates)
    assert agg
    top = agg[0].representative
    assert top.src.startswith("exif")
    assert top.tz


def test_process_directory_copies_with_timestamp(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    photos = input_dir / "photos"
    photos.mkdir(parents=True)
    file_path = photos / "image.jpg"
    file_path.write_bytes(b"data")
    ts = datetime(2024, 1, 2, 3, 4, 5).timestamp()
    os.utime(file_path, (ts, ts))

    script.process_directory(input_dir, output_dir)

    files = sorted(output_dir.iterdir())
    assert len(files) == 1
    renamed = files[0]
    assert renamed.name == "2024-01-02T03-04-05 photos__image.jpg"
    assert renamed.read_bytes() == b"data"
    assert math.isclose(renamed.stat().st_mtime, ts, abs_tol=1)


def test_process_directory_places_unknown_when_no_timestamp(
    tmp_path: Path, monkeypatch: Any
) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    file_path = input_dir / "clip.mov"
    file_path.write_bytes(b"x")

    monkeypatch.setattr(script, "extract_from_exiftool", lambda path: [])
    monkeypatch.setattr(script, "extract_from_ffprobe", lambda path: [])
    monkeypatch.setattr(script, "extract_from_mediainfo", lambda path: [])
    monkeypatch.setattr(script, "extract_sidecars", lambda path: [])
    monkeypatch.setattr(script, "file_system_candidates", lambda path: [])

    script.process_directory(input_dir, output_dir)

    unknown_dir = output_dir / "unknown"
    files = sorted(unknown_dir.iterdir())
    assert [item.name for item in files] == ["clip.mov"]


def test_process_directory_copies_sidecars(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    photos = input_dir / "photos"
    photos.mkdir(parents=True)
    main = photos / "image.jpg"
    sidecar = photos / "image.xmp"
    main.write_bytes(b"main")
    sidecar.write_bytes(b"sidecar")
    ts = datetime(2022, 7, 8, 9, 10, 11).timestamp()
    os.utime(main, (ts, ts))

    script.process_directory(input_dir, output_dir)

    files = sorted(item.name for item in output_dir.iterdir())
    assert files == [
        "2022-07-08T09-10-11 photos__image.jpg",
        "2022-07-08T09-10-11 photos__image.xmp",
    ]
