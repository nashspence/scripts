"""Determine the best creation date for a media file.

This module replicates the behaviour of the standalone script used in the
container image.  It aggregates timestamps from EXIF metadata, FFmpeg,
MediaInfo, filesystem data, and common sidecar formats before applying a
heuristic to pick the most trustworthy candidate.
"""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from dateutil import parser as dateparser

Candidate = tuple[str, datetime, int, bool, bool]


@dataclass(slots=True)
class CandidateRecord:
    """Normalized candidate enriched with metadata for scoring."""

    src: str
    dt: datetime
    dt_utc: datetime | None
    tz: bool
    score: float


@dataclass(slots=True)
class AggregatedGroup:
    """Cluster of closely matching timestamps."""

    representative: CandidateRecord
    members: list[CandidateRecord]
    score: float


def read_json_cmd(cmd: list[str]) -> Any:
    """Run *cmd* and decode JSON output.

    Returns ``None`` when the command fails or does not produce valid JSON.
    """

    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    stdout = proc.stdout.strip()
    if not stdout:
        return None
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return None


def parse_datetime_value(value: Any) -> tuple[datetime | None, bool, bool]:
    """Parse *value* into a ``datetime``.

    Returns a tuple of ``(datetime, timezone_present, fractional_seconds)``.
    ``datetime`` is ``None`` when parsing fails.
    """

    if value is None:
        return None, False, False

    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc), True, True
        except (OverflowError, OSError, ValueError):
            return None, False, False

    string = str(value).strip()
    if not string:
        return None, False, False

    if string.lower() in {
        "0000:00:00 00:00:00",
        "0000-00-00 00:00:00",
        "0000:00:00",
        "0000-00-00",
    }:
        return None, False, False

    if string.startswith("UTC "):
        parsed = parse_datetime_value(string[4:])[0]
        if parsed is None:
            return None, False, False
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc), True, False
        return parsed.astimezone(timezone.utc), True, False

    if re.match(r"^\d{4}:\d{2}:\d{2}", string):
        if re.search(r"[+-]\d{2}:\d{2}$", string) and " " in string:
            date_part, rest = string.split(" ", 1)
            string = date_part.replace(":", "-", 2) + " " + rest
        else:
            string = string.replace(":", "-", 2)

    try:
        dt = dateparser.parse(string)
    except (ValueError, OverflowError, TypeError):
        dt = None

    if dt is not None:
        tz_present = dt.tzinfo is not None and dt.tzinfo.utcoffset(dt) is not None
        has_frac = bool(re.search(r"\.\d+", string))
        if tz_present:
            return dt, True, has_frac
        return dt.replace(tzinfo=None), False, has_frac

    if re.fullmatch(r"\d{13}", string) or re.fullmatch(r"\d{12}", string):
        try:
            millis = int(string[:13])
            return datetime.fromtimestamp(millis / 1000.0, tz=timezone.utc), True, True
        except (OverflowError, OSError, ValueError):
            return None, False, False

    if re.fullmatch(r"\d{10}", string):
        try:
            return datetime.fromtimestamp(int(string), tz=timezone.utc), True, False
        except (OverflowError, OSError, ValueError):
            return None, False, False

    return None, False, False


def merge_exif_datetime(base: str, subsec: Any, offset: Any) -> str:
    """Combine EXIF date, subseconds, and offset values."""

    result = base
    if subsec:
        if "." not in result:
            result = f"{result}.{subsec}"
    if offset and not re.search(r"[+-]\d{2}:\d{2}$", result):
        result = f"{result}{offset}"
    return result


def _append_candidate(
    output: list[Candidate],
    source: str,
    value: Any,
    weight: int,
) -> None:
    dt, tz_present, has_fraction = parse_datetime_value(value)
    if dt:
        output.append((source, dt, weight, tz_present, has_fraction))


def extract_from_exiftool(path: str) -> list[Candidate]:
    """Extract timestamp candidates using ``exiftool``."""

    result: list[Candidate] = []
    data = read_json_cmd(["exiftool", "-j", "-a", "-G", "-s", path])
    if not data or not isinstance(data, list) or not data[0]:
        return result

    tags = data[0]
    base = tags.get("EXIF:DateTimeOriginal")
    subsec = tags.get("EXIF:SubSecTimeOriginal")
    offset = tags.get("EXIF:OffsetTimeOriginal") or tags.get("EXIF:TimeZone")
    composite = tags.get("Composite:SubSecDateTimeOriginal")
    if composite:
        _append_candidate(result, "exif:SubSecDateTimeOriginal", composite, 100)
    elif base:
        merged = merge_exif_datetime(base, subsec, offset)
        _append_candidate(result, "exif:DateTimeOriginal", merged, 98)

    created = tags.get("EXIF:CreateDate")
    if created:
        if tags.get("EXIF:SubSecTimeDigitized"):
            created = merge_exif_datetime(
                created,
                tags.get("EXIF:SubSecTimeDigitized"),
                tags.get("EXIF:OffsetTimeDigitized"),
            )
        _append_candidate(result, "exif:CreateDate", created, 94)

    for key in ("XMP:CreateDate", "XMP:DateCreated"):
        if key in tags:
            _append_candidate(result, f"xmp:{key.split(':', 1)[1]}", tags[key], 95)

    iptc_date = tags.get("IPTC:DateCreated")
    if iptc_date:
        iptc_time = tags.get("IPTC:TimeCreated")
        value = (
            f"{iptc_date.replace(':', '-', 2)} {iptc_time}" if iptc_time else iptc_date
        )
        _append_candidate(result, "iptc:DateCreated", value, 92)

    for key in (
        "QuickTime:MediaCreateDate",
        "QuickTime:CreateDate",
        "QuickTime:CreationDate",
        "QuickTime:TrackCreateDate",
    ):
        if key in tags:
            weight = 98 if key == "QuickTime:MediaCreateDate" else 96
            _append_candidate(result, key.lower(), tags[key], weight)

    if "Composite:GPSDateTime" in tags:
        _append_candidate(result, "gps:DateTime", tags["Composite:GPSDateTime"], 80)

    if "PNG:CreationTime" in tags:
        _append_candidate(result, "png:CreationTime", tags["PNG:CreationTime"], 90)

    for key in ("File:FileCreateDate", "File:FileModifyDate"):
        if key in tags:
            weight = 85 if key.endswith("CreateDate") else 60
            _append_candidate(result, key.lower(), tags[key], weight)

    return result


def extract_from_ffprobe(path: str) -> list[Candidate]:
    """Extract timestamp candidates from ``ffprobe`` JSON output."""

    result: list[Candidate] = []
    data = read_json_cmd(
        [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            path,
        ]
    )
    if not isinstance(data, dict):
        return result

    tags = (data.get("format") or {}).get("tags") or {}
    if "creation_time" in tags:
        _append_candidate(
            result, "ffprobe:format:creation_time", tags["creation_time"], 94
        )

    for stream in data.get("streams", []):
        st_tags = stream.get("tags") or {}
        if "creation_time" in st_tags:
            _append_candidate(
                result,
                "ffprobe:stream:creation_time",
                st_tags["creation_time"],
                93,
            )

    return result


def extract_from_mediainfo(path: str) -> list[Candidate]:
    """Extract timestamp candidates from ``mediainfo``."""

    result: list[Candidate] = []
    data = read_json_cmd(["mediainfo", "--Output=JSON", path])
    if not isinstance(data, dict):
        return result

    tracks = (data.get("media") or {}).get("track") or []
    for track in tracks:
        if track.get("@type") != "General":
            continue
        for key in (
            "Recorded_Date",
            "Tagged_Date",
            "Encoded_Date",
            "File_Created_Date",
            "File_Created_Date_Local",
        ):
            if key not in track:
                continue
            raw_value = track[key]
            if isinstance(raw_value, list):
                raw_value = raw_value[0]
            value = str(raw_value)
            if value.startswith("UTC "):
                parsed, tz_present, frac = parse_datetime_value(value[4:])
                if parsed:
                    dt = (
                        parsed.replace(tzinfo=timezone.utc)
                        if parsed.tzinfo is None
                        else parsed.astimezone(timezone.utc)
                    )
                    result.append((f"mediainfo:{key}", dt, 90, True, frac))
                continue
            weight = (
                88
                if "Recorded" in key
                else (
                    86 if "Encoded" in key else 84 if "File_Created_Date" in key else 70
                )
            )
            _append_candidate(result, f"mediainfo:{key}", value, weight)

    return result


def find_sidecars(path: Path) -> list[Path]:
    """Return matching sidecar file paths for *path*."""

    stem = path.stem
    ext = path.suffix
    directory = path.parent
    candidates: set[Path] = set()

    def add(names: Iterable[str]) -> None:
        for name in names:
            candidate = directory / name
            if candidate.exists():
                candidates.add(candidate)

    add(
        [
            f"{stem}.xmp",
            f"{stem}{ext}.xmp",
            f"{path.name}.xmp",
            f"{stem}.XMP",
            f"{stem}{ext}.XMP",
            f"{path.name}.XMP",
        ]
    )
    add(
        [
            f"{stem}.json",
            f"{stem}{ext}.json",
            f"{path.name}.json",
            f"{stem}.JSON",
            f"{stem}{ext}.JSON",
            f"{path.name}.JSON",
        ]
    )
    add([f"{stem}.aae", f"{stem}.AAE"])
    add(
        [
            f"{stem}.xml",
            f"{stem}{ext}.xml",
            f"{path.name}.xml",
            f"{stem}.XML",
            f"{stem}{ext}.XML",
            f"{path.name}.XML",
        ]
    )

    return sorted(candidates)


def extract_from_xmp(file_path: str) -> list[Candidate]:
    result: list[Candidate] = []
    try:
        tree = ET.parse(file_path)
    except (ET.ParseError, OSError):
        return result

    root = tree.getroot()
    weights = {
        "DateTimeOriginal": 96,
        "CreateDate": 96,
        "DateCreated": 96,
        "MetadataDate": 70,
        "ModifyDate": 68,
        "OriginalDate": 96,
    }
    for element in root.iter():
        tag = element.tag
        if "}" in tag:
            tag = tag.split("}", 1)[1]
        if tag in weights:
            _append_candidate(
                result,
                f"sidecar:xmp:{tag}",
                element.text,
                weights[tag],
            )

    return result


def extract_from_json_sidecar(file_path: str) -> list[Candidate]:
    result: list[Candidate] = []
    try:
        with open(file_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return result

    def visit(key: str | None, value: Any) -> None:
        lower = (key or "").lower()
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                visit(child_key, child_value)
            return
        if isinstance(value, list):
            for item in value:
                if isinstance(item, (dict, list)):
                    visit(key, item)
                else:
                    try_add(lower, item)
            return
        try_add(lower, value)

    def try_add(name: str, raw_value: Any) -> None:
        str_value = str(raw_value)
        if name in {
            "timestamp",
            "unixtime",
            "epoch",
            "takenms",
            "taken_at_ms",
        } or re.search(r"(timestamp|epoch)", name):
            _append_candidate(result, f"sidecar:json:{name}", str_value, 96)
            return

        if any(
            token in name
            for token in [
                "phototakentime",
                "takentime",
                "taken_time",
                "capturetime",
                "captured_at",
                "shootingtime",
            ]
        ):
            candidate = (
                raw_value.get("timestamp") if isinstance(raw_value, dict) else str_value
            )
            _append_candidate(result, "sidecar:json:taken", candidate, 97)
            return

        if any(
            token in name
            for token in [
                "creationtime",
                "createdtime",
                "created_at",
                "creation_date",
                "datecreated",
            ]
        ):
            candidate = (
                raw_value.get("timestamp") if isinstance(raw_value, dict) else str_value
            )
            _append_candidate(result, "sidecar:json:created", candidate, 96)
            return

        if any(token in name for token in ["datetimeoriginal", "originaldatetime"]):
            _append_candidate(result, "sidecar:json:DateTimeOriginal", str_value, 98)
            return

        if any(token in name for token in ["modifydate", "lastmodified"]):
            _append_candidate(result, "sidecar:json:ModifyDate", str_value, 60)

    if isinstance(data, dict):
        for key, value in data.items():
            visit(key, value)
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                for key, value in item.items():
                    visit(key, value)

    return result


def extract_from_aae(file_path: str) -> list[Candidate]:
    result: list[Candidate] = []
    try:
        with open(file_path, "rb") as handle:
            plist = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException):
        return result

    for key in (
        "adjustmentTimestamp",
        "modificationDate",
        "createDate",
        "creationDate",
    ):
        if key in plist:
            _append_candidate(result, f"sidecar:aae:{key}", plist[key], 60)

    return result


def extract_sidecars(path: str) -> list[Candidate]:
    result: list[Candidate] = []
    for sidecar in find_sidecars(Path(path)):
        suffix = sidecar.suffix.lower()
        if suffix == ".xmp":
            result.extend(extract_from_xmp(str(sidecar)))
        elif suffix == ".json":
            result.extend(extract_from_json_sidecar(str(sidecar)))
        elif suffix == ".aae":
            result.extend(extract_from_aae(str(sidecar)))
        elif suffix == ".xml":
            result.extend(extract_from_xmp(str(sidecar)))
    return result


def file_system_candidates(path: str) -> list[Candidate]:
    result: list[Candidate] = []
    try:
        stat = os.stat(path)
    except OSError:
        return result

    birthtime = getattr(stat, "st_birthtime", None)
    if isinstance(birthtime, (int, float)):
        birth = datetime.fromtimestamp(birthtime)
        result.append(("fs:birthtime", birth, 85, False, False))

    mtime = datetime.fromtimestamp(stat.st_mtime)
    result.append(("fs:mtime", mtime, 60, False, False))

    ctime = datetime.fromtimestamp(stat.st_ctime)
    result.append(("fs:ctime", ctime, 55, False, False))

    return result


def normalize_dt(dt: datetime) -> tuple[datetime, timezone | None]:
    if dt.tzinfo is None:
        return dt, None
    return dt.astimezone(timezone.utc), timezone.utc


def cluster_and_score(candidates: Iterable[Candidate]) -> list[AggregatedGroup]:
    valid: list[CandidateRecord] = []
    now = datetime.now(timezone.utc)
    for source, dt, weight, tz_present, has_fraction in candidates:
        if tz_present:
            dt_utc, _ = normalize_dt(dt)
            if dt_utc > now + timedelta(days=2):
                continue
            if dt_utc.year < 1990:
                continue
            score = float(weight) + 5 + (2 if has_fraction else 0)
            valid.append(CandidateRecord(source, dt, dt_utc, True, score))
            continue

        if dt.year < 1990 or dt.year > now.year + 1:
            continue
        score = float(weight) + (2 if has_fraction else 0)
        valid.append(CandidateRecord(source, dt, None, False, score))

    groups: list[list[CandidateRecord]] = []
    for candidate in valid:
        placed = False
        for group in groups:
            representative = group[0]
            if candidate.tz and representative.tz:
                if candidate.dt_utc is None or representative.dt_utc is None:
                    continue
                if (
                    abs((candidate.dt_utc - representative.dt_utc).total_seconds())
                    <= 120
                ):
                    group.append(candidate)
                    placed = True
                    break
            elif (not candidate.tz) and (not representative.tz):
                if abs((candidate.dt - representative.dt).total_seconds()) <= 120:
                    group.append(candidate)
                    placed = True
                    break
        if not placed:
            groups.append([candidate])

    aggregated: list[AggregatedGroup] = []
    for group in groups:
        representative = max(group, key=lambda item: item.score)
        score = len(group) * 5 + representative.score
        aggregated.append(AggregatedGroup(representative, group, score))

    aggregated.sort(
        key=lambda entry: (-entry.score, entry.representative.dt.isoformat())
    )
    return aggregated


def format_output(representative: CandidateRecord) -> str:
    dt = representative.dt
    if dt.tzinfo is not None and representative.tz:
        return dt.isoformat()
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


SAFE_FILENAME_RE = re.compile(r"[^0-9A-Za-z._()+@-]+")


def sanitize_component(value: str) -> str:
    """Return *value* normalized for safe filename usage."""

    sanitized = value.replace(os.sep, "_").replace("\\", "_")
    sanitized = sanitized.replace(":", "-")
    sanitized = SAFE_FILENAME_RE.sub("_", sanitized)
    sanitized = sanitized.strip(" ._-")
    return sanitized or "_"


def sanitize_relative_path(relative: Path) -> str:
    """Normalize a relative path so it can be embedded in a filename."""

    parts = [sanitize_component(part) for part in relative.parts]
    return "__".join(parts)


def sanitize_timestamp(value: str) -> str:
    """Return a sanitized representation of a timestamp string."""

    return sanitize_component(value)


def ensure_unique_name(
    directory: Path, file_name: str, used: dict[Path, set[str]]
) -> Path:
    """Ensure the resulting filename in *directory* is unique."""

    candidates = used.setdefault(directory, set())
    candidate = file_name
    stem, suffix = os.path.splitext(file_name)
    counter = 1
    while candidate in candidates or (directory / candidate).exists():
        candidate = f"{stem}__{counter}{suffix}"
        counter += 1
    candidates.add(candidate)
    return directory / candidate


def copy_preserving_metadata(source: Path, destination: Path) -> None:
    """Copy *source* to *destination* preserving metadata where possible."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def gather_candidates_for(path: Path) -> list[Candidate]:
    """Collect timestamp candidates for *path* using all extractors."""

    target = str(path)
    candidates: list[Candidate] = []
    candidates.extend(extract_from_exiftool(target))
    candidates.extend(extract_from_ffprobe(target))
    candidates.extend(extract_from_mediainfo(target))
    candidates.extend(extract_sidecars(target))
    candidates.extend(file_system_candidates(target))
    return candidates


def choose_best_candidate(path: Path) -> CandidateRecord | None:
    """Return the highest ranked timestamp candidate for *path*."""

    aggregated = cluster_and_score(gather_candidates_for(path))
    if not aggregated:
        return None
    return aggregated[0].representative


def rename_group(
    main_file: Path,
    sidecars: Sequence[Path],
    input_dir: Path,
    output_dir: Path,
    used_names: dict[Path, set[str]],
) -> None:
    """Copy *main_file* and *sidecars* into *output_dir* with new names."""

    best = choose_best_candidate(main_file)
    if best is None:
        unknown_dir = output_dir / "unknown"
        relative_main = main_file.relative_to(input_dir)
        target_main = sanitize_relative_path(relative_main)
        copy_preserving_metadata(
            main_file,
            ensure_unique_name(unknown_dir, target_main, used_names),
        )
        for sidecar in sidecars:
            relative_sidecar = sidecar.relative_to(input_dir)
            target_sidecar = sanitize_relative_path(relative_sidecar)
            copy_preserving_metadata(
                sidecar,
                ensure_unique_name(unknown_dir, target_sidecar, used_names),
            )
        return

    iso_component = sanitize_timestamp(format_output(best))
    relative_main = main_file.relative_to(input_dir)
    target_main = f"{iso_component} {sanitize_relative_path(relative_main)}"
    copy_preserving_metadata(
        main_file,
        ensure_unique_name(output_dir, target_main, used_names),
    )

    for sidecar in sidecars:
        relative_sidecar = sidecar.relative_to(input_dir)
        target_sidecar = f"{iso_component} {sanitize_relative_path(relative_sidecar)}"
        copy_preserving_metadata(
            sidecar,
            ensure_unique_name(output_dir, target_sidecar, used_names),
        )


def process_directory(input_dir: Path, output_dir: Path) -> None:
    """Walk *input_dir* and copy renamed files into *output_dir*."""

    if not input_dir.is_dir():
        raise ValueError("input directory must exist and be a directory")

    output_dir.mkdir(parents=True, exist_ok=True)
    used_names: dict[Path, set[str]] = {}
    processed: set[Path] = set()
    for path in sorted(p for p in input_dir.rglob("*") if p.is_file()):
        if path in processed:
            continue
        sidecars = [
            candidate for candidate in find_sidecars(path) if candidate.exists()
        ]
        processed.add(path)
        processed.update(sidecars)
        rename_group(path, sidecars, input_dir, output_dir, used_names)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Rename media files into a flat directory using guessed timestamps."
        )
    )
    parser.add_argument("input_dir", help="directory containing files to rename")
    parser.add_argument(
        "output_dir",
        help="directory where renamed files will be written",
    )

    parsed = parser.parse_args(argv)
    input_dir = Path(parsed.input_dir)
    output_dir = Path(parsed.output_dir)

    if not input_dir.is_dir():
        print(
            "input directory must exist and be a directory",
            file=sys.stderr,
        )
        return 2

    try:
        process_directory(input_dir, output_dir)
    except OSError as exc:
        print(f"error copying files: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
