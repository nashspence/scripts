"""Unit tests for guess_date heuristics."""

from __future__ import annotations

import io
import json
import os
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast

import pytest

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


def test_parse_datetime_value_supports_zulu_isoformat() -> None:
    dt, tz_present, frac = script.parse_datetime_value("2024-01-02T03:04:05Z")
    assert dt == datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    assert tz_present
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


def test_choose_and_output_prints_top_choice_when_not_tty(capsys: Any) -> None:
    dt = datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    rep1 = script.CandidateRecord("exif:DateTimeOriginal", dt, dt, True, 10.0)
    rep2 = script.CandidateRecord(
        "ffprobe:format",
        dt + timedelta(seconds=90),
        dt + timedelta(seconds=90),
        True,
        10.0,
    )
    aggregated = [
        script.AggregatedGroup(rep1, [rep1], 10.0),
        script.AggregatedGroup(rep2, [rep2], 10.0),
    ]

    class NonTTY(io.StringIO):
        def isatty(self) -> bool:  # pragma: no cover - simple shim
            return False

    dummy_stdin = NonTTY("")

    rc = script.choose_and_output(aggregated, stdin=dummy_stdin)
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out == dt.isoformat()


@pytest.mark.parametrize(
    ("path", "expected", "tz_present", "has_fraction"),
    [
        (
            "/archive/20240102T030405+0230!~/clip.mp4",
            datetime(
                2024,
                1,
                2,
                3,
                4,
                5,
                tzinfo=timezone(timedelta(hours=2, minutes=30)),
            ),
            True,
            False,
        ),
        (
            "/archive/20240102T030405+0230/clip.mp4",
            datetime(
                2024,
                1,
                2,
                3,
                4,
                5,
                tzinfo=timezone(timedelta(hours=2, minutes=30)),
            ),
            True,
            False,
        ),
        (
            "/archive/2024-07-16_09_10_15Z.mov",
            datetime(2024, 7, 16, 9, 10, 15, tzinfo=timezone.utc),
            True,
            False,
        ),
        (
            "/archive/2024-07-16_09_10_15.123456Z.mov",
            datetime(2024, 7, 16, 9, 10, 15, 123456, tzinfo=timezone.utc),
            True,
            True,
        ),
        (
            "/archive/2024-07-16_09_10_15.123456789.mov",
            datetime(2024, 7, 16, 9, 10, 15, 123456),
            False,
            True,
        ),
        (
            "/snapshots/20240102T030405.5+02:30.mp4",
            datetime(
                2024,
                1,
                2,
                3,
                4,
                5,
                500000,
                tzinfo=timezone(timedelta(hours=2, minutes=30)),
            ),
            True,
            True,
        ),
        (
            "/snapshots/20240102T030405-05:00.mp4",
            datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone(-timedelta(hours=5))),
            True,
            False,
        ),
        (
            "/snapshots/20240716T0910.mp4",
            datetime(2024, 7, 16, 9, 10),
            False,
            False,
        ),
        (
            "/snapshots/202407.mov",
            datetime(2024, 7, 1),
            False,
            False,
        ),
        (
            "/snapshots/2024.mov",
            datetime(2024, 1, 1),
            False,
            False,
        ),
        (
            "/snapshots/20240102T030405+02_30.mov",
            datetime(
                2024,
                1,
                2,
                3,
                4,
                5,
                tzinfo=timezone(timedelta(hours=2, minutes=30)),
            ),
            True,
            False,
        ),
    ],
)
def test_extract_datetime_from_path_rigid_variants(
    path: str, expected: datetime, tz_present: bool, has_fraction: bool
) -> None:
    result = script._extract_rigid_path_datetime(path)
    assert result is not None
    dt, tz, fraction = result
    assert dt == expected
    assert tz is tz_present
    assert fraction is has_fraction


def test_extract_datetime_from_path_rigid_invalid_day() -> None:
    assert script._extract_rigid_path_datetime("/broken/20240230.mov") is None


@pytest.mark.parametrize(
    "path",
    [
        "/broken/2024-00-01.mp4",
        "/broken/2024-13-01/clip.mp4",
    ],
)
def test_extract_datetime_from_path_rigid_invalid_month_defaults_to_year(
    path: str,
) -> None:
    result = script._extract_rigid_path_datetime(path)
    assert result is not None
    dt, tz, fraction = result
    assert dt == datetime(2024, 1, 1)
    assert not tz
    assert not fraction


@pytest.mark.parametrize(
    ("path", "expected", "tz_present", "has_fraction"),
    [
        (
            "photos/20230505T111530Z.jpg",
            datetime(2023, 5, 5, 11, 15, 30, tzinfo=timezone.utc),
            True,
            False,
        ),
        (
            "photos/2023-05-05 21:15:30+02:30.jpg",
            datetime(
                2023,
                5,
                5,
                21,
                15,
                30,
                tzinfo=timezone(timedelta(hours=2, minutes=30)),
            ),
            True,
            False,
        ),
        (
            "photos/2023-05-05 21:15:30.654321-05:00.jpg",
            datetime(
                2023,
                5,
                5,
                21,
                15,
                30,
                654321,
                tzinfo=timezone(-timedelta(hours=5)),
            ),
            True,
            True,
        ),
        (
            "photos/05-31-2023 11_15_30 PM-0500.jpg",
            datetime(2023, 5, 31, 23, 15, 30, tzinfo=timezone(-timedelta(hours=5))),
            True,
            False,
        ),
        (
            "photos/May 05, 2023 11-15-30 AM.jpg",
            datetime(2023, 5, 5, 11, 15, 30),
            False,
            False,
        ),
        (
            "photos/05-Jun-2022 23:59:59.png",
            datetime(2022, 6, 5, 23, 59, 59),
            False,
            False,
        ),
        (
            "photos/2024/July/04 04:05:06.mov",
            datetime(2024, 7, 4, 4, 5, 6),
            False,
            False,
        ),
        (
            "photos/31-12-2022.gif",
            datetime(2022, 12, 31),
            False,
            False,
        ),
        (
            "photos/2022-31-12.raw",
            datetime(2022, 12, 31),
            False,
            False,
        ),
        (
            "photos/12-31-2022.heic",
            datetime(2022, 12, 31),
            False,
            False,
        ),
        (
            "photos/2023-15-01 10:00:00.jpg",
            datetime(2023, 1, 15, 10, 0, 0),
            False,
            False,
        ),
        (
            "photos/2024-05/clip.mp4",
            datetime(2024, 5, 1),
            False,
            False,
        ),
        (
            "photos/April 2024/clip.mp4",
            datetime(2024, 4, 1),
            False,
            False,
        ),
        (
            "photos/2023/clip.mp4",
            datetime(2023, 1, 1),
            False,
            False,
        ),
    ],
)
def test_extract_datetime_from_path_relaxed_variants(
    path: str, expected: datetime, tz_present: bool, has_fraction: bool
) -> None:
    # Force relaxed extraction directly to ensure the broad pattern is exercised.
    result = script._extract_relaxed_path_datetime(path)
    assert result is not None
    dt, tz, fraction = result
    assert dt == expected
    assert tz is tz_present
    assert fraction is has_fraction


@pytest.mark.parametrize(
    ("path", "year"),
    [
        ("photos/32-12-2022.jpg", 2022),
        ("photos/Febtober 2023.png", 2023),
    ],
)
def test_extract_datetime_from_path_relaxed_unrecognized_tokens_default(
    path: str, year: int
) -> None:
    result = script._extract_relaxed_path_datetime(path)
    assert result is not None
    dt, tz, fraction = result
    assert dt == datetime(year, 1, 1)
    assert not tz
    assert not fraction


def test_file_system_candidates_use_path_over_mtime(monkeypatch: Any) -> None:
    class DummyStat:
        st_mtime = datetime(2024, 2, 3, 12, 0, 0).timestamp()
        st_ctime = datetime(2024, 2, 4, 12, 0, 0).timestamp()

    monkeypatch.setattr("containers.guess_date.script.os.stat", lambda _: DummyStat())

    path = "/media/2024-02-03!~/example.jpg"
    candidates = script.file_system_candidates(path)
    sources = {candidate[0] for candidate in candidates}
    assert "fs:path" in sources
    assert "fs:mtime" not in sources

    aggregated = script.cluster_and_score(candidates)
    assert aggregated
    assert aggregated[0].representative.src == "fs:path"


def test_file_system_candidates_falls_back_to_mtime(monkeypatch: Any) -> None:
    class DummyStat:
        st_mtime = datetime(2024, 5, 6, 7, 8, 9).timestamp()
        st_ctime = datetime(2024, 5, 6, 8, 8, 9).timestamp()

    monkeypatch.setattr("containers.guess_date.script.os.stat", lambda _: DummyStat())

    path = "/media/example.jpg"
    candidates = script.file_system_candidates(path)
    sources = {candidate[0] for candidate in candidates}
    assert "fs:mtime" in sources
    assert "fs:path" not in sources


def test_main_fails_when_mtime_is_only_source(monkeypatch: Any, tmp_path: Path) -> None:
    file_path = tmp_path / "example.mov"
    file_path.write_bytes(b"data")

    monkeypatch.setattr(
        "containers.guess_date.script.extract_from_exiftool", lambda _: []
    )
    monkeypatch.setattr(
        "containers.guess_date.script.extract_from_ffprobe", lambda _: []
    )
    monkeypatch.setattr(
        "containers.guess_date.script.extract_from_mediainfo", lambda _: []
    )
    monkeypatch.setattr("containers.guess_date.script.extract_sidecars", lambda _: [])

    dt = datetime(2024, 5, 6, 7, 8, 9)
    monkeypatch.setattr(
        "containers.guess_date.script.file_system_candidates",
        lambda _: [
            ("fs:mtime", dt, 60, False, False),
            ("fs:ctime", dt, 55, False, False),
        ],
    )

    rc = script.main(["--fail-on-mtime-only", os.fspath(file_path)])
    assert rc == 1


def test_main_allows_other_sources_with_mtime(
    monkeypatch: Any, tmp_path: Path, capsys: Any
) -> None:
    file_path = tmp_path / "example.mov"
    file_path.write_bytes(b"data")

    dt = datetime(2024, 5, 6, 7, 8, 9, tzinfo=timezone.utc)
    monkeypatch.setattr(
        "containers.guess_date.script.extract_from_exiftool",
        lambda _: [("exif:DateTimeOriginal", dt, 98, True, False)],
    )
    monkeypatch.setattr(
        "containers.guess_date.script.extract_from_ffprobe", lambda _: []
    )
    monkeypatch.setattr(
        "containers.guess_date.script.extract_from_mediainfo", lambda _: []
    )
    monkeypatch.setattr("containers.guess_date.script.extract_sidecars", lambda _: [])

    monkeypatch.setattr(
        "containers.guess_date.script.file_system_candidates",
        lambda _: [
            ("fs:mtime", dt.replace(tzinfo=None), 60, False, False),
            ("fs:ctime", dt.replace(tzinfo=None), 55, False, False),
        ],
    )

    rc = script.main(["--fail-on-mtime-only", os.fspath(file_path)])
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out == dt.isoformat()


def test_main_outputs_json(monkeypatch: Any, tmp_path: Path, capsys: Any) -> None:
    file_path = tmp_path / "example.mov"
    file_path.write_bytes(b"data")

    dt = datetime(2024, 5, 6, 7, 8, 9, tzinfo=timezone.utc)
    monkeypatch.setattr(
        "containers.guess_date.script.extract_from_exiftool",
        lambda _: [("exif:DateTimeOriginal", dt, 98, True, False)],
    )
    monkeypatch.setattr(
        "containers.guess_date.script.extract_from_ffprobe", lambda _: []
    )
    monkeypatch.setattr(
        "containers.guess_date.script.extract_from_mediainfo", lambda _: []
    )
    monkeypatch.setattr("containers.guess_date.script.extract_sidecars", lambda _: [])
    monkeypatch.setattr(
        "containers.guess_date.script.file_system_candidates",
        lambda _: [
            ("fs:mtime", dt.replace(tzinfo=None), 60, False, False),
            ("fs:ctime", dt.replace(tzinfo=None), 55, False, False),
        ],
    )

    rc = script.main(["--json", os.fspath(file_path)])
    captured = capsys.readouterr()
    assert rc == 0
    payload = json.loads(captured.out)
    assert payload == {
        "creation_date": dt.isoformat(),
        "source": "exif:DateTimeOriginal",
    }
