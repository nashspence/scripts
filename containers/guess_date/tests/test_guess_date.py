"""Unit tests for guess_date heuristics."""

from __future__ import annotations

import io
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
