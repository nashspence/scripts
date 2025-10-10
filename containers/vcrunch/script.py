#!/usr/bin/env python3

import argparse
import hashlib
import json
import logging
import mimetypes
import os
import pathlib
import platform
import re
import shlex
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from fractions import Fraction
from typing import Any, Dict, List, Optional, Sequence, Tuple, TypedDict, TypeVar, cast
from xml.sax.saxutils import escape as xml_escape

OUT_EXT = ".mkv"
DEFAULT_SUFFIX = ""
MANIFEST_NAME = ".job.json"
MAX_SVT_KBPS = 100_000
DEFAULT_TARGET_SIZE = "23.30G"
DEFAULT_SAFETY_OVERHEAD = 0.012

FFMPEG_INPUT_FLAGS = ["-fflags", "+genpts"]
FFMPEG_OUTPUT_FLAGS = [
    "-avoid_negative_ts",
    "make_zero",
    "-max_interleave_delta",
    "0",
]

VERBOSE_LEVEL = 0


class _StreamExportRequired(TypedDict):
    path: str
    stream: Dict[str, Any]
    stype: str
    mkv_ok: bool


class StreamExport(_StreamExportRequired, total=False):
    packet_timestamps_path: str
    spec: str
    muxer: str


class StreamInfo(TypedDict):
    index: int
    stream: Dict[str, Any]
    stype: str
    mkv_ok: bool
    spec: str


class DumpedStreams(TypedDict):
    exports: List[StreamExport]
    attachments: List[pathlib.Path]
    metadata_path: Optional[pathlib.Path]
    container_tags: Dict[str, str]
    stream_infos: List[StreamInfo]


_METADATA_COPY_BASE = ["-map_metadata", "0"]
_METADATA_COPY_STREAM_MAP: List[Tuple[str, List[str]]] = [
    ("v", ["-map_metadata:s:v", "0:s:v"]),
    ("a", ["-map_metadata:s:a", "0:s:a"]),
    ("s", ["-map_metadata:s:s", "0:s:s"]),
    ("d", ["-map_metadata:s:d", "0:s:d"]),
    ("t", ["-map_metadata:s:t", "0:s:t"]),
]


def _metadata_copy_args(stream_types: Sequence[str]) -> List[str]:
    args = list(_METADATA_COPY_BASE)
    present = {stype for stype in stream_types}
    for stype, option in _METADATA_COPY_STREAM_MAP:
        if stype in present:
            args.extend(option)
    return args


VIDEO_STREAM_MAP: Dict[str, Tuple[str, str, bool]] = {
    "h264": ("h264", "h264", True),
    "hevc": ("hevc", "h265", True),
    "mpeg4": ("m4v", "m4v", True),
    "mpeg2video": ("mpeg2video", "m2v", True),
    "vp9": ("ivf", "ivf", True),
    "av1": ("ivf", "ivf", True),
    "mjpeg": ("mjpeg", "mjpeg", False),
    "png": ("image2", "png", False),
    "bmp": ("image2", "bmp", False),
    "webp": ("image2", "webp", False),
}


AUDIO_STREAM_MAP: Dict[str, Tuple[str, str, bool]] = {
    "aac": ("adts", "aac", True),
    "ac3": ("ac3", "ac3", True),
    "eac3": ("eac3", "eac3", True),
    "mp3": ("mp3", "mp3", True),
    "flac": ("flac", "flac", True),
    "opus": ("opus", "opus", True),
    "vorbis": ("ogg", "ogg", True),
    "pcm_s16le": ("wav", "wav", True),
    "pcm_s24le": ("wav", "wav", True),
    "pcm_s32le": ("wav", "wav", True),
}


SUBTITLE_STREAM_MAP: Dict[str, Tuple[str, str, bool]] = {
    "subrip": ("srt", "srt", True),
    "srt": ("srt", "srt", True),
    "ass": ("ass", "ass", True),
    "ssa": ("ass", "ass", True),
    "webvtt": ("webvtt", "vtt", True),
    "hdmv_pgs_subtitle": ("sup", "sup", True),
}


RAW_STREAM_DUMP = ("data", "bin", False)


def _data_sidecar_suffix(token: str) -> str:
    clean = token or "data"
    if clean.endswith("data"):
        return clean
    return f"{clean}data"


def _sanitize_token(value: Optional[str]) -> str:
    if not value:
        return ""
    cleaned = re.sub(r"[^\w\-\+.]+", "_", value.strip())
    return cleaned[:48]


def _stream_language(stream: Dict[str, Any]) -> str:
    tags = cast(Dict[str, Any], stream.get("tags") or {})
    lang = cast(str, tags.get("language") or "")
    if lang.lower() in {"und", "undetermined", "xx"}:
        return ""
    return lang.lower()


def _stream_title(stream: Dict[str, Any]) -> str:
    tags = cast(Dict[str, Any], stream.get("tags") or {})
    title = cast(str, tags.get("title") or "")
    return title


def _stream_disposition_flags(stream: Dict[str, Any]) -> List[str]:
    disp = cast(Dict[str, Any], stream.get("disposition") or {})
    flags = []
    for key in (
        "default",
        "forced",
        "hearing_impaired",
        "visual_impaired",
        "attached_pic",
        "dub",
        "original",
    ):
        try:
            if int(disp.get(key, 0)) == 1:
                flags.append(key)
        except (TypeError, ValueError):
            continue
    return flags


def _classify_stream(stream: Dict[str, Any]) -> Tuple[str, Tuple[str, str, bool]]:
    codec_type = cast(str, stream.get("codec_type") or "")
    codec_name = cast(str, (stream.get("codec_name") or "").lower())
    if codec_type == "video":
        return "v", VIDEO_STREAM_MAP.get(codec_name, RAW_STREAM_DUMP)
    if codec_type == "audio":
        return "a", AUDIO_STREAM_MAP.get(codec_name, RAW_STREAM_DUMP)
    if codec_type == "subtitle":
        return "s", SUBTITLE_STREAM_MAP.get(codec_name, RAW_STREAM_DUMP)
    if codec_type == "attachment":
        return "t", RAW_STREAM_DUMP
    return "d", RAW_STREAM_DUMP


def _sidecar_name(
    base: pathlib.Path,
    stype: str,
    index: int,
    codec_hint: str,
    lang: str,
    flags: List[str],
    ext: str,
    dest_dir: pathlib.Path,
    *,
    naming_stem: Optional[str] = None,
) -> pathlib.Path:
    stem = naming_stem or base.stem
    if naming_stem is None:
        match = re.match(r"^(?P<root>.+?)\.[0-9a-f]{8}$", stem)
        if match:
            stem = match.group("root")
    parts = [f"{stype}{index}-{_sanitize_token(codec_hint) or 'unknown'}"]
    if lang:
        parts.append(lang)
    if flags:
        parts.extend(flags[:2])
    filename = ".".join([stem] + parts) + f".{ext}"
    return dest_dir / filename


_PurePathT = TypeVar("_PurePathT", bound=pathlib.PurePath)


def _lowercase_suffix(path: _PurePathT) -> _PurePathT:
    suffix = path.suffix
    if not suffix:
        return path
    lowered = suffix.lower()
    if lowered == suffix:
        return path
    return path.with_suffix(lowered)


def _lowercase_suffix_str(path_str: str) -> str:
    return str(_lowercase_suffix(pathlib.PurePath(path_str)))


def _export_stream(
    src: str,
    output: pathlib.Path,
    stream_index: int,
    muxer: str,
    verbose: bool,
    *,
    stream_types: Sequence[str],
) -> None:
    cmd = [
        "ffmpeg",
        "-y",
    ]
    if verbose:
        cmd += ["-stats", "-loglevel", "info"]
    else:
        cmd += ["-hide_banner", "-loglevel", "warning"]
    cmd += FFMPEG_INPUT_FLAGS
    cmd += [
        "-i",
        src,
        "-map",
        f"0:{stream_index}",
    ]
    cmd += _metadata_copy_args(stream_types)
    cmd += FFMPEG_OUTPUT_FLAGS
    cmd += [
        "-c",
        "copy",
        "-f",
        muxer,
        str(output),
    ]
    _print_command(cmd)
    proc = subprocess.run(cmd)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed exporting stream {stream_index}")


def _export_attachments(
    src: str, dest_dir: pathlib.Path, verbose: bool
) -> List[pathlib.Path]:
    attach_dir = dest_dir / "attachments"
    attach_dir.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y"]
    if verbose:
        cmd += ["-stats", "-loglevel", "info"]
    else:
        cmd += ["-hide_banner", "-loglevel", "warning"]
    cmd += [
        "-dump_attachment:t",
        "",
    ]
    cmd += FFMPEG_INPUT_FLAGS
    cmd += [
        "-i",
        src,
    ]
    cmd += FFMPEG_OUTPUT_FLAGS
    cmd += [
        "-f",
        "null",
        os.devnull,
    ]
    _print_command(cmd)
    proc = subprocess.run(cmd, cwd=str(attach_dir))
    if proc.returncode != 0:
        return []
    return [p for p in attach_dir.iterdir() if p.is_file()]


def _pick_real_video_stream_index(src: str) -> Optional[Tuple[int, str]]:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "stream=index,codec_type,disposition,width,height",
        "-of",
        "json",
        src,
    ]
    try:
        data = ffprobe_json(cmd)
    except subprocess.CalledProcessError:
        return None
    streams = cast(List[Dict[str, Any]], data.get("streams") or [])
    best_index: Optional[int] = None
    best_spec: Optional[str] = None
    best_score = -1
    video_ordinal = 0
    for stream in streams:
        if cast(str, stream.get("codec_type")) != "video":
            continue
        spec = f"v:{video_ordinal}"
        video_ordinal += 1
        disp = cast(Dict[str, Any], stream.get("disposition") or {})
        try:
            if int(disp.get("attached_pic", 0)) == 1:
                continue
        except (TypeError, ValueError):
            continue
        raw_width = stream.get("width")
        raw_height = stream.get("height")
        width = 0
        height = 0
        if isinstance(raw_width, (int, float)):
            width = int(raw_width)
        elif isinstance(raw_width, str):
            try:
                width = int(float(raw_width))
            except ValueError:
                width = 0
        if isinstance(raw_height, (int, float)):
            height = int(raw_height)
        elif isinstance(raw_height, str):
            try:
                height = int(float(raw_height))
            except ValueError:
                height = 0
        score = width * height
        try:
            idx = int(cast(Any, stream.get("index")))
        except (TypeError, ValueError):
            continue
        if score > best_score:
            best_score = score
            best_index = idx
            best_spec = spec
    if best_index is None or best_spec is None:
        logging.debug("no non-attached video stream found in %s", src)
        return None
    logging.debug(
        "selected video stream %s (specifier %s) with score %s for %s",
        best_index,
        best_spec,
        best_score,
        src,
    )
    return best_index, best_spec


def _collect_frame_timestamps_seconds(
    src: str, stream_index: int, stream_spec: str
) -> Optional[List[float]]:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        stream_spec,
        "-show_frames",
        "-show_entries",
        "frame=media_type,best_effort_timestamp_time,pkt_pts_time,pts_time,pkt_dts_time",
        "-of",
        "json",
        src,
    ]
    try:
        data = ffprobe_json(cmd)
    except subprocess.CalledProcessError as exc:
        logging.debug(
            "ffprobe -show_frames failed for %s stream %s (%s): %s",
            src,
            stream_index,
            stream_spec,
            exc,
        )
        return _collect_packet_timestamps_seconds(src, stream_index, stream_spec)
    frames = cast(List[Dict[str, Any]], data.get("frames") or [])
    timestamps: List[float] = []
    for frame in frames:
        if cast(str, frame.get("media_type")) != "video":
            continue
        value = _parse_time_value(frame.get("best_effort_timestamp_time"))
        if value is None:
            value = _parse_time_value(frame.get("pkt_pts_time"))
        if value is None:
            continue
        timestamps.append(value)
    if not timestamps:
        logging.debug(
            "no frame timestamps found for %s stream %s (%s); falling back to packets",
            src,
            stream_index,
            stream_spec,
        )
        return _collect_packet_timestamps_seconds(src, stream_index, stream_spec)
    fixed: List[float] = []
    last = float("-inf")
    for ts in timestamps:
        if ts < last:
            ts = last
        fixed.append(ts)
        last = ts
    logging.debug(
        "collected %d frame timestamps for %s stream %s (%s)",
        len(fixed),
        src,
        stream_index,
        stream_spec,
    )
    return fixed


def _parse_time_value(raw: Any) -> Optional[float]:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        value = raw.strip()
        if not value:
            return None
        try:
            return float(value)
        except ValueError:
            if "/" in value:
                try:
                    return float(Fraction(value))
                except (ValueError, ZeroDivisionError):
                    return None
    return None


def _collect_packet_timestamps_seconds(
    src: str, stream_index: int, stream_spec: str
) -> Optional[List[float]]:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        stream_spec,
        "-show_packets",
        "-show_entries",
        "packet=stream_index,pts_time,dts_time,pos,flags",
        "-of",
        "json",
        src,
    ]
    try:
        data = ffprobe_json(cmd)
    except subprocess.CalledProcessError as exc:
        logging.debug(
            "ffprobe -show_packets failed for %s stream %s (%s): %s",
            src,
            stream_index,
            stream_spec,
            exc,
        )
        return None
    packets = cast(List[Dict[str, Any]], data.get("packets") or [])
    timestamps: List[float] = []
    for packet in packets:
        value = _parse_time_value(packet.get("pts_time"))
        if value is None:
            value = _parse_time_value(packet.get("dts_time"))
        if value is None:
            continue
        timestamps.append(value)
    if not timestamps:
        logging.debug(
            "no packet timestamps found for %s stream %s (%s)",
            src,
            stream_index,
            stream_spec,
        )
        return []
    fixed: List[float] = []
    last = float("-inf")
    for ts in timestamps:
        if ts < last:
            ts = last
        fixed.append(ts)
        last = ts
    logging.debug(
        "collected %d packet timestamps for %s stream %s (%s)",
        len(fixed),
        src,
        stream_index,
        stream_spec,
    )
    return fixed


def _dump_streams_and_metadata(
    src: str,
    dest_dir: pathlib.Path,
    verbose: bool,
    *,
    naming_stem: Optional[str] = None,
) -> DumpedStreams:
    dest_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        "-show_programs",
        "-show_chapters",
        src,
    ]
    metadata = ffprobe_json(cmd)
    source_path = pathlib.Path(src)
    source_suffix = source_path.suffix
    data_ext_hint = source_suffix[1:] if source_suffix.startswith(".") else ""
    container_format_name: Optional[str] = None
    meta_path: Optional[pathlib.Path] = None
    metadata_stem = naming_stem or source_path.stem
    container_tags: Dict[str, str] = {}
    if metadata:
        meta_path = dest_dir / f"{metadata_stem}.metadata.json"
        with open(meta_path, "w", encoding="utf-8") as fh:
            json.dump(metadata, fh, indent=2)
            fh.write("\n")
        fmt_obj = metadata.get("format")
        if isinstance(fmt_obj, dict):
            raw_format_name = fmt_obj.get("format_name")
            if isinstance(raw_format_name, str):
                first_format = raw_format_name.split(",")[0].strip()
                if first_format:
                    container_format_name = first_format
            raw_tags = fmt_obj.get("tags")
            if isinstance(raw_tags, dict):
                for key, value in raw_tags.items():
                    if isinstance(key, str) and isinstance(value, str):
                        container_tags[key] = value

    exports: List[StreamExport] = []
    stream_infos: List[StreamInfo] = []
    streams = cast(List[Dict[str, Any]], metadata.get("streams") or [])
    type_map = {
        "video": "v",
        "audio": "a",
        "subtitle": "s",
        "data": "d",
        "attachment": "t",
    }
    type_counters: Dict[str, int] = {}
    stream_specifiers: Dict[int, str] = {}
    for raw_stream in streams:
        try:
            raw_index = int(raw_stream.get("index", -1))
        except (TypeError, ValueError):
            continue
        letter = type_map.get(cast(str, raw_stream.get("codec_type") or ""))
        if not letter:
            continue
        ordinal = type_counters.get(letter, 0)
        type_counters[letter] = ordinal + 1
        stream_specifiers[raw_index] = f"{letter}:{ordinal}"

    total_data_streams = type_counters.get("d", 0)

    for stream in streams:
        try:
            index = int(stream.get("index", -1))
        except (TypeError, ValueError):
            continue
        stype, (muxer, ext, mkv_ok) = _classify_stream(stream)
        spec = stream_specifiers.get(index, "")
        stream_infos.append(
            {
                "index": index,
                "stream": stream,
                "stype": stype,
                "mkv_ok": mkv_ok,
                "spec": spec,
            }
        )
        if stype == "t":
            continue
        if stype in {"v", "a"}:
            continue
        if stype == "s" and mkv_ok:
            continue
        codec_hint = cast(
            str,
            (
                stream.get("codec_name") or stream.get("codec_tag_string") or "unknown"
            ).lower(),
        )
        lang = _stream_language(stream)
        flags = _stream_disposition_flags(stream)
        target_muxer = muxer
        target_ext = ext
        if stype == "d":
            target_muxer = container_format_name or "matroska"
            data_base = data_ext_hint or container_format_name or "mkv"
            data_token = _sanitize_token(data_base) or "mkv"
            target_ext = _data_sidecar_suffix(data_token)
        elif stype == "s" and not mkv_ok:
            if container_format_name:
                target_muxer = container_format_name
            container_token = (
                _sanitize_token(container_format_name or data_ext_hint or target_ext)
                or target_ext
            )
            target_ext = _data_sidecar_suffix(container_token)
        sidecar = _sidecar_name(
            source_path,
            stype,
            index,
            codec_hint,
            lang,
            flags,
            target_ext,
            dest_dir,
            naming_stem=naming_stem,
        )
        try:
            _export_stream(
                src,
                sidecar,
                index,
                target_muxer,
                verbose,
                stream_types=[stype],
            )
            export_entry: StreamExport = {
                "path": str(sidecar),
                "stream": stream,
                "stype": stype,
                "mkv_ok": mkv_ok,
                "spec": spec,
                "muxer": target_muxer,
            }
            exports.append(export_entry)
            try:
                sidecar.unlink()
            except FileNotFoundError:
                pass
        except RuntimeError as exc:
            if (
                stype == "d"
                and container_format_name
                and target_muxer == container_format_name
                and total_data_streams == 1
            ):
                logging.info(
                    "failed to export data stream %s using %s; falling back to raw data: %s",
                    index,
                    container_format_name,
                    exc,
                )
                try:
                    sidecar.unlink()
                except FileNotFoundError:
                    pass
                fallback_path = sidecar.with_suffix(".data")
                try:
                    _export_stream(
                        src,
                        fallback_path,
                        index,
                        "data",
                        verbose,
                        stream_types=[stype],
                    )
                except RuntimeError as fallback_exc:
                    logging.warning(
                        "failed to export data stream %s as raw data: %s",
                        index,
                        fallback_exc,
                    )
                    continue

                packets_path: Optional[pathlib.Path] = None
                stream_spec = stream_specifiers.get(index)
                timestamps: Optional[List[float]] = None
                if stream_spec:
                    timestamps = _collect_packet_timestamps_seconds(
                        src, index, stream_spec
                    )
                if timestamps is not None:
                    packets_path = fallback_path.with_suffix(".packets.json")
                    try:
                        with open(packets_path, "w", encoding="utf-8") as fh:
                            json.dump({"packets": timestamps}, fh, indent=2)
                            fh.write("\n")
                    except OSError as write_exc:
                        logging.warning(
                            "failed to write packet timestamps for stream %s: %s",
                            index,
                            write_exc,
                        )
                        packets_path = None

                fallback_entry: StreamExport = {
                    "path": str(fallback_path),
                    "stream": stream,
                    "stype": stype,
                    "mkv_ok": False,
                    "spec": spec,
                    "muxer": "data",
                }
                if packets_path is not None:
                    fallback_entry["packet_timestamps_path"] = str(packets_path)
                exports.append(fallback_entry)
                try:
                    fallback_path.unlink()
                except FileNotFoundError:
                    pass
                continue

            logging.warning("failed to export stream %s: %s", index, exc)

    attachments = _export_attachments(src, dest_dir, verbose)
    return {
        "exports": exports,
        "attachments": attachments,
        "metadata_path": meta_path,
        "container_tags": container_tags,
        "stream_infos": stream_infos,
    }


def _mkvmerge_args(
    streams: List[Tuple[pathlib.Path, Dict[str, Any], str]],
) -> Tuple[List[str], List[pathlib.Path]]:
    order = {"v": 0, "a": 1, "s": 2, "d": 3, "t": 4}
    args: List[str] = []
    used: List[pathlib.Path] = []
    for path, stream, stype in sorted(streams, key=lambda item: order.get(item[2], 9)):
        if stype not in {"v", "a", "s"}:
            continue
        lang = _stream_language(stream)
        title = _stream_title(stream)
        flags = _stream_disposition_flags(stream)
        if lang:
            args += ["--language", f"0:{lang}"]
        if title:
            args += ["--track-name", f"0:{title}"]
        if "default" in flags:
            args += ["--default-track-flag", "0:yes"]
        if "forced" in flags:
            args += ["--forced-track-flag", "0:yes"]
        args.append(str(path))
        used.append(path)
    return args, used


def _print_command(cmd: Sequence[str]) -> None:
    if not VERBOSE_LEVEL:
        return
    cmdline = " ".join(shlex.quote(str(part)) for part in cmd)
    print(cmdline, file=sys.stderr)


def _packet_sidecar_path(
    export: StreamExport, export_path: pathlib.Path
) -> Optional[pathlib.Path]:
    packet_path_str = export.get("packet_timestamps_path")
    if packet_path_str:
        return pathlib.Path(packet_path_str)
    if export.get("stype") == "d" and not export.get("mkv_ok"):
        inferred = export_path.with_suffix(".packets.json")
        if inferred.exists():
            return inferred
    return None


def _guess_mime_type(path: pathlib.Path) -> str:
    mime, _ = mimetypes.guess_type(path.name)
    if mime:
        return mime
    return "application/octet-stream"


def _clean_attachment_description(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text.strip())
    cleaned = cleaned.replace(":", ";")
    if not cleaned:
        return "attachment"
    return cleaned[:120]


def _attach_sidecar_files(
    mkv_path: str, attachments: Sequence[Tuple[pathlib.Path, str, str]]
) -> None:
    if not attachments:
        return
    for path, description, mime_type in attachments:
        if not path.exists():
            continue
        desc = _clean_attachment_description(description) or path.name
        name = path.name

        cmd = ["mkvpropedit", mkv_path]
        if name:
            cmd.extend(["--attachment-name", name])
        if mime_type:
            cmd.extend(["--attachment-mime-type", mime_type])
        if desc:
            cmd.extend(["--attachment-description", desc])
        cmd.extend(["--add-attachment", str(path)])
        _print_command(cmd)
        proc = subprocess.run(cmd)
        if proc.returncode != 0:
            raise RuntimeError(
                f"mkvpropedit failed to attach {path} with code {proc.returncode}"
            )


def _apply_birthtime(path: str, birthtime: float) -> None:
    if platform.system() != "Darwin":
        return
    setfile = shutil.which("SetFile")
    if not setfile:
        logging.debug("SetFile unavailable; skipping birthtime update for %s", path)
        return
    try:
        dt = datetime.fromtimestamp(birthtime, tz=timezone.utc).astimezone()
    except (OSError, OverflowError, ValueError) as exc:
        logging.debug("cannot convert birthtime for %s: %s", path, exc)
        return
    formatted = dt.strftime("%m/%d/%Y %H:%M:%S")
    cmd = [setfile, "-d", formatted, path]
    try:
        _print_command(cmd)
        proc = subprocess.run(cmd)
    except OSError as exc:
        logging.debug("failed to execute SetFile for %s: %s", path, exc)
        return
    if proc.returncode != 0:
        logging.debug("SetFile exited with %s for %s", proc.returncode, path)


def _apply_source_timestamps(
    src: str, dest: str, st: Optional[os.stat_result] = None
) -> None:
    try:
        stat_result = st if st is not None else os.stat(src)
    except OSError as exc:
        logging.debug("failed to stat %s for timestamp copy: %s", src, exc)
        return

    atime_ns = getattr(
        stat_result, "st_atime_ns", int(stat_result.st_atime * 1_000_000_000)
    )
    mtime_ns = getattr(
        stat_result, "st_mtime_ns", int(stat_result.st_mtime * 1_000_000_000)
    )

    try:
        os.utime(dest, ns=(atime_ns, mtime_ns))
    except OSError as exc:
        logging.debug("failed to update timestamps for %s: %s", dest, exc)
        return

    birthtime = getattr(stat_result, "st_birthtime", None)
    if birthtime is not None:
        _apply_birthtime(dest, birthtime)


def _build_container_tags_xml(entries: List[Tuple[str, str]]) -> str:
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<Tags>"]
    for key, value in entries:
        lines.append("  <Tag>")
        lines.append("    <Targets>")
        lines.append("      <TargetTypeValue>50</TargetTypeValue>")
        lines.append("    </Targets>")
        lines.append("    <Simple>")
        lines.append(f"      <Name>{xml_escape(key)}</Name>")
        lines.append(f"      <String>{xml_escape(value)}</String>")
        lines.append("    </Simple>")
        lines.append("  </Tag>")
    lines.append("</Tags>")
    return "\n".join(lines) + "\n"


def _apply_container_metadata(
    mkv_path: str,
    creation_date: Optional[str],
    tags: Dict[str, str],
    cleanup: List[str],
) -> None:
    info_updates: List[Tuple[str, str]] = []
    remaining_tags: List[Tuple[str, str]] = []

    title_value = None
    for key, value in tags.items():
        if not isinstance(value, str):
            continue
        stripped = value.strip()
        if not stripped:
            continue
        lowered = key.lower()
        if lowered == "title":
            title_value = stripped
            continue
        if lowered in {"creation_time", "com.apple.quicktime.creationdate"}:
            continue
        remaining_tags.append((key, stripped))

    if creation_date:
        info_updates.append(("date", creation_date))
    if title_value:
        info_updates.append(("title", title_value))

    tags_file: Optional[pathlib.Path] = None
    if remaining_tags:
        xml_text = _build_container_tags_xml(remaining_tags)
        tags_file = pathlib.Path(mkv_path + ".container.tags.xml")
        try:
            tags_file.write_text(xml_text, encoding="utf-8")
        except OSError as exc:
            raise RuntimeError(f"failed to write container tags XML: {exc}") from exc
        cleanup.append(str(tags_file))

    if not info_updates and tags_file is None:
        return

    cmd: List[str] = ["mkvpropedit", mkv_path]
    if info_updates:
        cmd += ["--edit", "info"]
        for key, value in info_updates:
            cmd += ["--set", f"{key}={value}"]
    if tags_file is not None:
        cmd += ["--tags", f"global:{tags_file}"]
    _print_command(cmd)
    proc = subprocess.run(cmd)
    if proc.returncode != 0:
        raise RuntimeError(f"mkvpropedit exited with code {proc.returncode}")


class MediaPreset(TypedDict):
    target_size: str
    safety_overhead: float


class MediaProbeResult(TypedDict, total=False):
    is_video: bool
    duration: Optional[float]
    error: str


class ProbeCacheEntry(TypedDict, total=False):
    path: str
    is_video: bool
    duration: float
    error: str


MEDIA_PRESETS: dict[str, MediaPreset] = {
    "cdr700": {"target_size": "650M", "safety_overhead": 0.020},
    "dvd5": {"target_size": "4.36G", "safety_overhead": 0.020},
    "dvd9": {"target_size": "7.95G", "safety_overhead": 0.020},
    "dvd10": {"target_size": "8.73G", "safety_overhead": 0.020},
    "dvd18": {"target_size": "15.85G", "safety_overhead": 0.020},
    "bdr25": {"target_size": "23.30G", "safety_overhead": 0.012},
    "bdr50": {"target_size": "46.60G", "safety_overhead": 0.012},
    "bdr100": {"target_size": "93.10G", "safety_overhead": 0.012},
    "bdr128": {"target_size": "119.10G", "safety_overhead": 0.012},
}

_MEDIA_ALIASES: dict[str, str] = {
    "cd700": "cdr700",
    "cdr": "cdr700",
    "cd-r": "cdr700",
    "cd-r700": "cdr700",
    "dvd-5": "dvd5",
    "dvd+5": "dvd5",
    "dvd5": "dvd5",
    "dvd-9": "dvd9",
    "dvd+9": "dvd9",
    "dvd9": "dvd9",
    "dvd-10": "dvd10",
    "dvd10": "dvd10",
    "dvd-18": "dvd18",
    "dvd18": "dvd18",
    "bd25": "bdr25",
    "bdr25": "bdr25",
    "bd-r25": "bdr25",
    "bd-r": "bdr25",
    "bd50": "bdr50",
    "bdr50": "bdr50",
    "bd-r50": "bdr50",
    "bd100": "bdr100",
    "bdr100": "bdr100",
    "bdxl100": "bdr100",
    "bd128": "bdr128",
    "bdr128": "bdr128",
    "bdxl128": "bdr128",
}


def run(cmd: list[str]) -> None:
    print("+ " + " ".join(map(str, cmd)), file=sys.stderr)
    p = subprocess.run(cmd)
    if p.returncode != 0:
        raise SystemExit(p.returncode)


def _normalize_media(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    key = s.strip().lower().replace("_", "").replace(" ", "")
    key = key.replace("gb", "").replace("gib", "").replace("-", "")
    if key in MEDIA_PRESETS:
        return key
    return _MEDIA_ALIASES.get(key)


def parse_size(s: str) -> int:
    s = s.strip().lower().replace("ib", "")
    mult = 1
    if s.endswith("k"):
        mult = 1024
        s = s[:-1]
    elif s.endswith("m"):
        mult = 1024**2
        s = s[:-1]
    elif s.endswith("g"):
        mult = 1024**3
        s = s[:-1]
    elif s.endswith("t"):
        mult = 1024**4
        s = s[:-1]
    return int(float(s) * mult)


def kbps_to_bps(s: str) -> int:
    s = s.strip().lower()
    if s.endswith("k"):
        return int(float(s[:-1]) * 1000)
    if s.endswith("m"):
        return int(float(s[:-1]) * 1_000_000)
    return int(float(s))


def ffprobe_json(cmd: Sequence[str]) -> dict[str, Any]:
    _print_command(cmd)
    proc = subprocess.run(
        cmd,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout = proc.stdout.decode("utf-8", "replace")
    if not stdout.strip():
        return {}
    return cast(dict[str, Any], json.loads(stdout))


def find_start_timecode(path: str) -> str:
    probes = [
        [
            "ffprobe",
            "-v",
            "error",
            "-of",
            "json",
            "-select_streams",
            "d",
            "-show_streams",
            "-show_entries",
            "stream=tags",
            path,
        ],
        [
            "ffprobe",
            "-v",
            "error",
            "-of",
            "json",
            "-show_format",
            "-show_entries",
            "format=tags",
            path,
        ],
        [
            "ffprobe",
            "-v",
            "error",
            "-of",
            "json",
            "-select_streams",
            "v:0",
            "-show_streams",
            "-show_entries",
            "stream=tags",
            path,
        ],
    ]
    for cmd in probes:
        try:
            data = ffprobe_json(cmd)
        except Exception:
            continue
        streams = data.get("streams")
        if isinstance(streams, list):
            for stream in streams:
                if not isinstance(stream, dict):
                    continue
                tags = stream.get("tags")
                if isinstance(tags, dict) and tags.get("timecode"):
                    return str(tags["timecode"])
        fmt = data.get("format")
        if isinstance(fmt, dict):
            tags = fmt.get("tags")
            if isinstance(tags, dict) and tags.get("timecode"):
                return str(tags["timecode"])
    return "00:00:00:00"


def _parse_creation_date(value: str) -> Optional[str]:
    s = value.strip()
    if not s:
        return None

    candidates = [s]
    if "T" not in s and " " in s:
        candidates.append(s.replace(" ", "T", 1))

    for candidate in candidates:
        fixed = candidate
        if fixed.endswith("Z"):
            fixed = fixed[:-1] + "+00:00"
        elif fixed.endswith("+0000"):
            fixed = fixed[:-5] + "+00:00"

        try:
            dt = datetime.fromisoformat(fixed)
        except ValueError:
            continue

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)

        return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")

    return None


def get_container_creation_date(path: str) -> Optional[str]:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_entries",
        "format_tags=creation_time,com.apple.quicktime.creationdate",
        path,
    ]

    try:
        data = ffprobe_json(cmd)
    except Exception:
        return None

    fmt = data.get("format")
    if not isinstance(fmt, dict):
        return None

    tags = fmt.get("tags")
    if not isinstance(tags, dict):
        return None

    for key in ("creation_time", "com.apple.quicktime.creationdate"):
        value = tags.get(key)
        if isinstance(value, str):
            parsed = _parse_creation_date(value)
            if parsed:
                return parsed

    return None


def _parse_fraction(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        s = value.strip()
        if not s or s.lower() == "n/a":
            return None
        if "/" in s:
            num, den = s.split("/", 1)
            try:
                return float(num) / float(den)
            except (ValueError, ZeroDivisionError):
                return None
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _parse_duration_value(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if value >= 0 else None
    if isinstance(value, str):
        s = value.strip()
        if not s or s.lower() in {"n/a", "nan"}:
            return None
        try:
            return float(s)
        except ValueError:
            if ":" in s:
                parts = s.split(":")
                try:
                    total = 0.0
                    for part in parts:
                        total = total * 60 + float(part)
                    return total
                except ValueError:
                    return None
    return None


def probe_media_info(path: str) -> MediaProbeResult:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_streams",
        "-show_format",
        path,
    ]
    try:
        data = ffprobe_json(cmd)
    except subprocess.CalledProcessError as exc:
        err = (
            exc.stderr.decode("utf-8", "replace").strip()
            if getattr(exc, "stderr", None)
            else ""
        )
        failure: MediaProbeResult = {"is_video": False, "duration": None}
        if err:
            failure["error"] = err
        return failure

    fmt = data.get("format") or {}
    fmt_names = {n.strip() for n in (fmt.get("format_name") or "").split(",")}
    is_image_container = any(
        n.endswith("_pipe") or n.startswith("image2") for n in fmt_names
    )
    if is_image_container:
        return {"is_video": False, "duration": None}

    has_video_stream = False
    positive_stream_durations: list[float] = []
    for stream in data.get("streams") or []:
        if not isinstance(stream, dict):
            continue
        if stream.get("codec_type") != "video":
            continue
        if (
            isinstance(stream.get("disposition"), dict)
            and stream["disposition"].get("attached_pic") == 1
        ):
            continue
        has_video_stream = True
        d = _parse_duration_value(stream.get("duration"))
        if d is not None and d > 0:
            positive_stream_durations.append(d)

    has_video = has_video_stream and bool(positive_stream_durations)
    duration = positive_stream_durations[0] if positive_stream_durations else None
    return {"is_video": has_video, "duration": duration}


def ffprobe_duration(path: str) -> float:
    info = probe_media_info(path)
    duration = info.get("duration")
    if duration is None:
        raise ValueError(f"ffprobe did not report duration for {path}")
    return float(duration)


def is_valid_media(path: str) -> bool:
    try:
        return ffprobe_duration(path) > 0.0
    except Exception:
        return False


def has_video_stream(path: str) -> bool:
    info = probe_media_info(path)
    return bool(info.get("is_video"))


def is_video_file(path: str) -> bool:
    return has_video_stream(path)


def _should_ignore_name(name: str) -> bool:
    return name.startswith("._")


def collect_all_files(paths: List[str], pattern: Optional[str]) -> List[str]:
    files = []
    for p in paths:
        p = os.path.abspath(p)
        if os.path.isfile(p):
            if _should_ignore_name(os.path.basename(p)):
                continue
            files.append(p)
        elif os.path.isdir(p):
            for root, dirs, fn in os.walk(p):
                dirs[:] = [d for d in dirs if not _should_ignore_name(d)]
                for f in fn:
                    if _should_ignore_name(f):
                        continue
                    fp = os.path.abspath(os.path.join(root, f))
                    if os.path.isfile(fp):
                        files.append(fp)
    if pattern:
        files = [p for p in files if pathlib.PurePath(p).match(pattern)]
    return sorted(set(files))


def read_paths_from(fpath: str) -> List[str]:
    fh = sys.stdin if fpath == "-" else open(fpath, "r", encoding="utf-8")
    with fh:
        return [ln.strip() for ln in fh if ln.strip()]


def sanitize_base(stem: str) -> str:
    base = os.path.basename(stem).replace("\\", "_")
    while base.startswith("."):
        base = base[1:]
    return base or "file"


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_manifest(path: str) -> dict[str, Any]:
    if not os.path.exists(path):
        return {"version": 1, "updated": now_utc_iso(), "items": {}, "probes": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            m = cast(dict[str, Any], json.load(f))
            if not isinstance(m.get("items"), dict):
                m["items"] = {}
            if not isinstance(m.get("probes"), dict):
                m["probes"] = {}
            return m
    except Exception:
        return {"version": 1, "updated": now_utc_iso(), "items": {}, "probes": {}}


def save_manifest(manifest: dict[str, Any], path: str) -> None:
    manifest["updated"] = now_utc_iso()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def src_key(src_abs: str, st: os.stat_result) -> str:
    return f"{src_abs}|{st.st_size}|{int(st.st_mtime)}"


def all_videos_done(manifest: dict[str, Any], out_dir: str) -> bool:
    saw_video = False
    for rec in manifest.get("items", {}).values():
        if rec.get("type") != "video":
            continue
        saw_video = True
        out_name = rec.get("output")
        if not out_name:
            return False
        fp = os.path.join(out_dir, out_name)
        if not (
            rec.get("status") == "done" and os.path.exists(fp) and is_valid_media(fp)
        ):
            return False
    return saw_video


def _short_hash(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:8]


def copy_assets(
    assets: List[str],
    out_dir: str,
    rename_map: Optional[dict[str, str]] = None,
    manifest: Optional[dict[str, Any]] = None,
    manifest_path: Optional[str] = None,
) -> list[tuple[str, str]]:
    copied: list[tuple[str, str]] = []
    rename_map = rename_map or {}
    manifest_dict = manifest if isinstance(manifest, dict) else None
    manifest_items = manifest_dict.get("items") if manifest_dict else None

    for src in assets:
        dest_name = rename_map.get(src, os.path.basename(src))
        dest_name = os.path.normpath(dest_name)
        dest_name = _lowercase_suffix_str(dest_name)
        dest = os.path.join(out_dir, dest_name)
        if os.path.abspath(src) == os.path.abspath(dest):
            continue

        key: Optional[str] = None
        record: Optional[dict[str, Any]] = None
        src_stat: Optional[os.stat_result] = None
        if manifest_items is not None:
            try:
                st = os.stat(src)
                src_stat = st
            except FileNotFoundError:
                logging.warning("asset missing, skipping: %s", src)
                continue
            key = src_key(os.path.abspath(src), st)
            rec_val = manifest_items.get(key)
            if isinstance(rec_val, dict):
                record = rec_val

            if record and record.get("status") == "done":
                recorded_output = os.path.normpath(record.get("output") or dest_name)
                output_path = os.path.join(out_dir, recorded_output)
                if os.path.exists(output_path):
                    if recorded_output != dest_name:
                        new_output_path = os.path.join(out_dir, dest_name)
                        new_output_dir = os.path.dirname(new_output_path)
                        if new_output_dir and not os.path.exists(new_output_dir):
                            os.makedirs(new_output_dir, exist_ok=True)
                        try:
                            os.replace(output_path, new_output_path)
                        except OSError as exc:
                            logging.error(
                                "failed to rename asset %s -> %s: %s",
                                output_path,
                                new_output_path,
                                exc,
                            )
                            if (
                                manifest_items is not None
                                and key is not None
                                and manifest_dict is not None
                            ):
                                new_record = dict(record)
                                new_record["status"] = "pending"
                                new_record["error"] = f"rename failed: {exc}"
                                new_record.pop("finished_at", None)
                                manifest_items[key] = new_record
                                if manifest_path:
                                    save_manifest(manifest_dict, manifest_path)
                        else:
                            logging.info(
                                "renamed asset output: %s -> %s",
                                output_path,
                                new_output_path,
                            )
                            _apply_source_timestamps(src, new_output_path, src_stat)
                            copied.append((src, dest_name))
                            if (
                                manifest_items is not None
                                and key is not None
                                and manifest_dict is not None
                            ):
                                new_record = dict(record)
                                new_record["output"] = dest_name
                                manifest_items[key] = new_record
                                if manifest_path:
                                    save_manifest(manifest_dict, manifest_path)
                            continue
                    logging.info("skip asset done: %s -> %s", src, output_path)
                    copied.append((src, recorded_output))
                    if manifest_dict is not None and recorded_output != record.get(
                        "output"
                    ):
                        record["output"] = recorded_output
                        manifest_items[key] = record
                        if manifest_path:
                            save_manifest(manifest_dict, manifest_path)
                    continue
                logging.warning(
                    "manifest marks asset done but output missing: %s", output_path
                )
                if manifest_dict is not None and manifest_items is not None:
                    new_record = dict(record)
                    new_record["status"] = "pending"
                    new_record["error"] = "output missing"
                    new_record.pop("finished_at", None)
                    manifest_items[key] = new_record
                    if manifest_path:
                        save_manifest(manifest_dict, manifest_path)
                record = None

        dest_dir = os.path.dirname(dest)
        if dest_dir and not os.path.exists(dest_dir):
            os.makedirs(dest_dir, exist_ok=True)

        try:
            shutil.copy2(src, dest)
            _apply_source_timestamps(src, dest, src_stat)
            logging.info("copied asset: %s -> %s", src, dest)
            copied.append((src, dest_name))
            if (
                manifest_items is not None
                and key is not None
                and manifest_dict is not None
            ):
                manifest_items[key] = {
                    "type": "asset",
                    "src": src,
                    "output": dest_name,
                    "status": "done",
                    "finished_at": now_utc_iso(),
                }
                manifest_items[key].pop("error", None)
                if manifest_path:
                    save_manifest(manifest_dict, manifest_path)
        except Exception as e:
            logging.error("failed to copy asset %s -> %s: %s", src, dest, e)
            if (
                manifest_items is not None
                and key is not None
                and manifest_dict is not None
            ):
                manifest_items[key] = {
                    "type": "asset",
                    "src": src,
                    "output": dest_name,
                    "status": "pending",
                    "error": str(e),
                }
                manifest_items[key].pop("finished_at", None)
                if manifest_path:
                    save_manifest(manifest_dict, manifest_path)
    return copied


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Encode videos (SVT-AV1) with resume manifest. Non-video files are copied to the output directory."
    )
    ap.add_argument(
        "--input",
        action="append",
        default=["/in"],
        help="File or directory (repeatable).",
    )
    ap.add_argument("--paths-from", help="Newline-delimited paths, or '-' for stdin.")
    ap.add_argument(
        "--pattern", default=None, help="Optional glob to filter inputs (e.g., '*')."
    )
    ap.add_argument(
        "--media",
        help="Optical media preset. Choices: cdr700, dvd5, dvd9, dvd10, dvd18, bdr25, bdr50, bdr100, bdr128.",
    )
    ap.add_argument(
        "--target-size",
        default=None,
        help="Total target size (e.g., 23.30G, 7.95G, 650M).",
    )
    ap.add_argument(
        "--constant-quality",
        type=int,
        default=None,
        help="Use SVT-AV1 constant quality (CRF) instead of computing a target bitrate.",
    )
    ap.add_argument(
        "--audio-bitrate", default="128k", help="Per-title audio bitrate (e.g., 128k)."
    )
    ap.add_argument(
        "--safety-overhead",
        type=float,
        default=None,
        help="Reserve fraction for mux/fs overhead.",
    )
    ap.add_argument("--output-dir", default="/out", help="Output directory.")
    ap.add_argument(
        "--manifest-name",
        default=MANIFEST_NAME,
        help="Manifest filename under output dir.",
    )
    ap.add_argument(
        "--name-suffix",
        default=DEFAULT_SUFFIX,
        help="Suffix before extension for encoded files.",
    )
    ap.add_argument(
        "--move-if-fit",
        action="store_true",
        help="Move files instead of copying when inputs fit within target size without re-encoding.",
    )
    ap.add_argument(
        "--stage-dir",
        default="/work",
        help="Local work dir inside the container; inputs are staged here before encoding.",
    )
    ap.add_argument(
        "--svt-lp",
        type=int,
        default=int(os.getenv("SVT_LP", "5")),
        help="Number of SVT-AV1 lookahead processes (lp parameter).",
    )
    ap.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase verbosity (-v, -vv).",
    )
    args = ap.parse_args()

    level = (
        logging.WARNING
        if args.verbose == 0
        else (logging.INFO if args.verbose == 1 else logging.DEBUG)
    )
    global VERBOSE_LEVEL
    VERBOSE_LEVEL = args.verbose
    logging.basicConfig(
        level=level, stream=sys.stderr, format="%(levelname)s: %(message)s"
    )

    if args.constant_quality is not None and args.constant_quality < 0:
        logging.error("--constant-quality must be non-negative")
        sys.exit(2)

    canon_media = _normalize_media(args.media)
    if args.media and not canon_media:
        logging.error(
            "unknown --media value: %s; valid: %s",
            args.media,
            ", ".join(sorted(MEDIA_PRESETS.keys())),
        )
        sys.exit(2)
    preset = MEDIA_PRESETS.get(canon_media) if canon_media else None
    target_size_str = (
        args.target_size
        if args.target_size is not None
        else (preset["target_size"] if preset else DEFAULT_TARGET_SIZE)
    )
    safety_overhead = (
        args.safety_overhead
        if args.safety_overhead is not None
        else (preset["safety_overhead"] if preset else DEFAULT_SAFETY_OVERHEAD)
    )

    os.makedirs(args.output_dir, exist_ok=True)
    os.makedirs(args.stage_dir, exist_ok=True)
    manifest_path = os.path.join(args.output_dir, args.manifest_name)
    manifest = load_manifest(manifest_path)

    inputs: List[str] = []
    if args.paths_from:
        inputs += read_paths_from(args.paths_from)
    inputs += args.input
    all_files = collect_all_files([p for p in inputs if p], args.pattern)
    if not all_files:
        logging.error("no input files found")
        sys.exit(1)

    def manifest_covers_inputs() -> bool:
        items = manifest.get("items")
        if not isinstance(items, dict):
            return False
        for src in all_files:
            try:
                st = os.stat(src)
            except FileNotFoundError:
                continue
            key = src_key(os.path.abspath(src), st)
            rec = items.get(key)
            if not isinstance(rec, dict):
                return False
            if rec.get("status") != "done":
                return False
            output_rel = rec.get("output")
            if not output_rel:
                return False
            output_path = os.path.join(args.output_dir, os.path.normpath(output_rel))
            if rec.get("type") == "video":
                if not (os.path.exists(output_path) and is_valid_media(output_path)):
                    return False
            else:
                if not os.path.exists(output_path):
                    return False
        return True

    if all_videos_done(manifest, args.output_dir) and manifest_covers_inputs():
        logging.warning(
            "already complete; manifest indicates all videos are done and outputs are valid"
        )
        logging.info("manifest: %s", manifest_path)
        return

    probes_val = manifest.get("probes")
    if not isinstance(probes_val, dict):
        probes_val = {}
        manifest["probes"] = probes_val
    probe_cache = cast(dict[str, ProbeCacheEntry], probes_val)

    video_flags: dict[str, bool] = {}
    video_durations: dict[str, float] = {}
    probe_keys: dict[str, str] = {}
    filtered_files: list[str] = []

    for path in all_files:
        try:
            st = os.stat(path)
        except FileNotFoundError:
            logging.warning("input missing, skipping: %s", path)
            continue

        key = src_key(os.path.abspath(path), st)
        probe_keys[path] = key
        entry = probe_cache.get(key)
        if not isinstance(entry, dict):
            entry = None
        if entry is None:
            probe_result = probe_media_info(path)
            entry = {
                "path": os.path.abspath(path),
                "is_video": bool(probe_result.get("is_video")),
            }
            duration_value = probe_result.get("duration")
            if duration_value is not None:
                entry["duration"] = float(duration_value)
            probe_cache[key] = entry
            save_manifest(manifest, manifest_path)

        is_video = bool(entry.get("is_video"))
        duration_val = entry.get("duration")
        if isinstance(duration_val, (int, float)):
            video_durations[path] = float(duration_val)

        video_flags[path] = is_video
        filtered_files.append(path)
        if args.verbose:
            if is_video:
                logging.info("video: %s", path)
            else:
                logging.info("not a video: %s", path)

    all_files = filtered_files
    videos = [p for p in all_files if video_flags.get(p)]
    assets = [p for p in all_files if not video_flags.get(p)]
    video_set = {p for p, is_video in video_flags.items() if is_video}

    logging.info("media preset: %s", canon_media or "none")
    logging.info("outputs: %s", args.output_dir)
    logging.info("staging: %s", args.stage_dir)
    logging.info(
        "inputs: %d (videos=%d assets=%d)", len(all_files), len(videos), len(assets)
    )

    use_constant_quality = args.constant_quality is not None

    target_bytes = parse_size(target_size_str)
    total_input_bytes = 0
    for src in all_files:
        try:
            total_input_bytes += os.path.getsize(src)
        except FileNotFoundError:
            pass

    if not use_constant_quality and total_input_bytes <= target_bytes:
        action = "move" if args.move_if_fit else "copy"
        logging.warning(
            "inputs fit within target size; %sing without re-encoding", action
        )
        manifest["items"] = {}
        for src in all_files:
            st = os.stat(src)
            dest = os.path.join(args.output_dir, os.path.basename(src))
            try:
                if args.move_if_fit:
                    shutil.move(src, dest)
                else:
                    shutil.copy2(src, dest)
            except Exception as e:
                logging.error("%s failed %s -> %s: %s", action, src, dest, e)
                sys.exit(1)
            if src in video_set:
                key = src_key(os.path.abspath(src), st)
                manifest["items"][key] = {
                    "type": "video",
                    "src": src,
                    "output": os.path.basename(src),
                    "status": "done",
                    "finished_at": now_utc_iso(),
                }
        save_manifest(manifest, manifest_path)
        logging.warning("done; no re-encoding needed")
        return

    asset_bytes = 0
    for src in assets:
        try:
            asset_bytes += os.path.getsize(src)
        except FileNotFoundError:
            pass

    audio_bps = kbps_to_bps(args.audio_bitrate)
    total_duration = 0.0
    total_audio_bytes = 0
    durations: List[float] = []
    for src in videos:
        duration = video_durations.get(src)
        if duration is None:
            try:
                duration = ffprobe_duration(src)
            except Exception as exc:
                logging.error("failed to determine duration for %s: %s", src, exc)
                sys.exit(1)
            probe_key = probe_keys.get(src)
            if probe_key:
                entry = probe_cache.get(probe_key)
                if entry is not None:
                    entry["duration"] = float(duration)
                    save_manifest(manifest, manifest_path)
            video_durations[src] = float(duration)
        durations.append(float(duration))
        total_duration += float(duration)
        total_audio_bytes += int((audio_bps / 8.0) * float(duration))

    global_video_kbps = 0
    if use_constant_quality:
        logging.info("using constant quality: CRF=%s", args.constant_quality)
        if videos and total_duration <= 0:
            logging.error("total video duration is zero; cannot proceed")
            sys.exit(1)
    else:
        reserved = int(target_bytes * safety_overhead) + 20_000_000
        video_budget_bytes = target_bytes - asset_bytes - total_audio_bytes - reserved
        if video_budget_bytes <= 0 and videos:
            logging.error(
                "assets + audio + overhead exceed target size; no room for video"
            )
            sys.exit(1)

        avg_video_bps = 0
        if videos:
            if total_duration <= 0:
                logging.error("total video duration is zero; cannot compute bitrate")
                sys.exit(1)
            avg_video_bps = int((video_budget_bytes * 8) / total_duration)
            if avg_video_bps < 50_000:
                logging.error("computed video bitrate unrealistically low")
                sys.exit(1)

        computed_kbps = max(1, int(avg_video_bps / 1000)) if avg_video_bps else 1
        if computed_kbps > MAX_SVT_KBPS:
            logging.warning(
                "computed average video bitrate %s kbps exceeds SVT-AV1 max %s kbps; clamping; final size will undershoot",
                computed_kbps,
                MAX_SVT_KBPS,
            )
            global_video_kbps = MAX_SVT_KBPS
        else:
            global_video_kbps = computed_kbps

    logging.info("target bytes: %s", f"{target_bytes:,}")
    logging.info("asset bytes: %s", f"{asset_bytes:,}")
    logging.info(
        "video duration hours: %.2f; audio bytes: %s",
        total_duration / 3600 if videos else 0.0,
        f"{total_audio_bytes:,}",
    )
    if videos:
        if not use_constant_quality:
            logging.info(
                "video budget bytes: %s; avg video bitrate: %s kbps (using %s kbps)",
                f"{max(0, video_budget_bytes):,}",
                f"{computed_kbps:,}",
                f"{global_video_kbps:,}",
            )
    else:
        logging.info("no videos to encode")

    output_by_input: dict[str, str] = {}
    video_metadata: list[dict[str, Any]] = []
    encoded_count = 0
    for src, _dur in zip(videos, durations):
        st = os.stat(src)
        stem = sanitize_base(pathlib.Path(src).stem)
        ext = pathlib.Path(src).suffix
        output_ext = OUT_EXT
        out_name = _lowercase_suffix_str(f"{stem}{args.name_suffix}{output_ext}")
        metadata = {
            "dir": os.path.abspath(os.path.dirname(src)),
            "original": os.path.basename(src),
            "desired": out_name,
            "ext_changed": ext.lower() != output_ext.lower(),
            "used_original": False,
        }
        video_metadata.append(metadata)
        h = _short_hash(os.path.abspath(src))
        stage_src = os.path.join(args.stage_dir, f"{stem}.{h}{ext}")
        stage_part = os.path.join(args.stage_dir, out_name + ".part")
        remux_output = stage_part + ".mkvmerge"
        key = src_key(os.path.abspath(src), st)
        rec = manifest["items"].get(
            key, {"type": "video", "src": src, "output": out_name, "status": "pending"}
        )

        output_rel = _lowercase_suffix_str(rec.get("output") or out_name)
        desired_ext_lower = output_ext.lower()
        current_ext = os.path.splitext(output_rel)[1].lower()
        if current_ext != desired_ext_lower:
            output_rel = out_name
        else:
            output_rel = _lowercase_suffix_str(output_rel)
        rec["output"] = output_rel
        output_by_input[os.path.abspath(src)] = os.path.normpath(output_rel)
        final_path = os.path.join(args.output_dir, output_rel)
        final_dir = os.path.dirname(final_path)
        if final_dir and not os.path.exists(final_dir):
            os.makedirs(final_dir, exist_ok=True)
        part_path = final_path + ".part"

        def mark_pending(error: Optional[str] = None) -> None:
            rec["status"] = "pending"
            rec.pop("started_at", None)
            rec.pop("finished_at", None)
            if error:
                rec["error"] = error
            else:
                rec.pop("error", None)
            manifest["items"][key] = rec
            save_manifest(manifest, manifest_path)

        if rec.get("status") == "encoding_started":
            logging.info("retrying previously started encode for %s", src)
            mark_pending()

        for stale in (
            part_path,
            stage_part,
            remux_output,
        ):
            if os.path.exists(stale):
                try:
                    os.remove(stale)
                except FileNotFoundError:
                    pass

        if rec.get("status") == "done":
            if os.path.exists(final_path):
                try:
                    if not is_valid_media(final_path):
                        logging.debug(
                            "manifest marks video done but validation failed: %s",
                            final_path,
                        )
                except Exception:
                    logging.debug(
                        "manifest marks video done but validation errored: %s",
                        final_path,
                    )
                logging.info("skip done: %s", final_path)
                continue
            logging.warning(
                "manifest marks video done but output missing: %s", final_path
            )
            mark_pending("output missing")

        if os.path.exists(final_path) and not is_valid_media(final_path):
            try:
                os.remove(final_path)
            except FileNotFoundError:
                pass

        original_creation_date: Optional[str] = None
        try:
            if os.path.exists(stage_src):
                try:
                    os.remove(stage_src)
                except FileNotFoundError:
                    pass
            if args.verbose:
                logging.info("staging -> %s", stage_src)
            shutil.copy2(src, stage_src)
            original_creation_date = get_container_creation_date(stage_src)
        except Exception as e:
            logging.error("failed to stage source %s -> %s: %s", src, stage_src, e)
            mark_pending(f"failed to stage source: {e}")
            continue

        audio_kbps = max(1, int(audio_bps / 1000))
        streams_root = pathlib.Path(os.path.join(args.stage_dir, f"{stem}.{h}.streams"))
        if streams_root.exists():
            shutil.rmtree(streams_root, ignore_errors=True)

        finally_cleanup_files: List[str] = [stage_part, remux_output, stage_src]

        try:
            try:
                dumped = _dump_streams_and_metadata(
                    stage_src, streams_root, args.verbose, naming_stem=stem
                )
            except Exception as exc:
                logging.error("failed to dump streams for %s: %s", src, exc)
                mark_pending("failed to dump streams")
                continue
            exports = dumped["exports"]
            attachments = dumped["attachments"]
            metadata_sidecar = dumped["metadata_path"]
            container_tags = dumped.get("container_tags", {})

            stream_infos = dumped.get("stream_infos", [])
            info_by_index = {info["index"]: info for info in stream_infos}

            video_selection = _pick_real_video_stream_index(stage_src)
            if video_selection is None:
                logging.error("no video stream found for %s", src)
                mark_pending("no video stream found")
                continue

            video_stream_index, video_stream_spec = video_selection
            video_stream_info = info_by_index.get(video_stream_index)
            if video_stream_info is None:
                logging.error("missing video stream metadata for %s", src)
                mark_pending("missing video stream metadata")
                continue

            primary_video_spec = video_stream_info.get("spec") or video_stream_spec
            if not primary_video_spec:
                logging.error("missing video stream specifier for %s", src)
                mark_pending("missing video stream specifier")
                continue

            video_infos = sorted(
                [info for info in stream_infos if info["stype"] == "v"],
                key=lambda item: item["index"],
            )
            audio_infos = sorted(
                [info for info in stream_infos if info["stype"] == "a"],
                key=lambda item: item["index"],
            )
            subtitle_infos = sorted(
                [
                    info
                    for info in stream_infos
                    if info["stype"] == "s" and info["mkv_ok"]
                ],
                key=lambda item: item["index"],
            )
            attachment_infos = sorted(
                [info for info in stream_infos if info["stype"] == "t"],
                key=lambda item: item["index"],
            )

            rec.pop("error", None)
            rec.update(
                {
                    "status": "encoding_started",
                    "started_at": now_utc_iso(),
                    "output": output_rel,
                }
            )
            manifest["items"][key] = rec
            save_manifest(manifest, manifest_path)

            env = os.environ.copy()
            env["SVT_LOG"] = "4" if args.verbose else "2"

            base_name = pathlib.Path(src).stem
            encode_output_path = streams_root / f"{base_name}.encoded.mkv"
            finally_cleanup_files.append(str(encode_output_path))

            encode_cmd = ["ffmpeg"]
            if args.verbose:
                encode_cmd += ["-stats", "-loglevel", "info"]
            else:
                encode_cmd += ["-hide_banner", "-loglevel", "warning"]
            encode_cmd += [
                "-y",
                "-ignore_unknown",
            ]
            encode_cmd += FFMPEG_INPUT_FLAGS
            encode_cmd += [
                "-i",
                stage_src,
            ]

            encode_outputs: List[List[str]] = []

            main_stream_types: List[str] = []

            def _register_main_stream(stype: str) -> None:
                if stype not in main_stream_types:
                    main_stream_types.append(stype)

            main_output_opts: List[str] = []
            for info in sorted(stream_infos, key=lambda item: item["index"]):
                spec = info.get("spec")
                if not spec:
                    continue
                stype = info.get("stype")
                if stype == "v":
                    main_output_opts += ["-map", f"0:{spec}"]
                    _register_main_stream("v")
                elif stype == "a":
                    main_output_opts += ["-map", f"0:{spec}"]
                    _register_main_stream("a")
                elif stype == "s" and info.get("mkv_ok"):
                    main_output_opts += ["-map", f"0:{spec}"]
                    _register_main_stream("s")
                elif stype == "t":
                    main_output_opts += ["-map", f"0:{spec}"]
                    _register_main_stream("t")

            if "v" not in main_stream_types:
                logging.error("no video streams mapped for %s", src)
                mark_pending("no video streams mapped")
                continue

            main_output_opts += _metadata_copy_args(main_stream_types)
            main_output_opts += FFMPEG_OUTPUT_FLAGS
            main_output_opts += ["-c:v", "libsvtav1"]
            if use_constant_quality:
                main_output_opts += ["-crf", str(args.constant_quality), "-b:v", "0"]
            else:
                main_output_opts += ["-b:v", f"{global_video_kbps}k"]
            main_output_opts += [
                "-preset",
                "5",
                "-svtav1-params",
                f"lp={args.svt_lp}",
                "-fps_mode",
                "passthrough",
            ]
            if "a" in main_stream_types:
                main_output_opts += [
                    "-c:a",
                    "libopus",
                    "-ar",
                    "48000",
                    "-b:a",
                    f"{audio_kbps}k",
                ]
            if "s" in main_stream_types:
                main_output_opts += ["-c:s", "copy"]
            if "t" in main_stream_types:
                main_output_opts += ["-c:t", "copy"]
            main_output_opts += [
                "-f",
                "matroska",
                str(encode_output_path),
            ]
            encode_outputs.append(main_output_opts)

            for export in exports:
                spec = export.get("spec")
                if not spec:
                    continue
                export_path = pathlib.Path(export["path"])
                export_path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    export_path.unlink()
                except FileNotFoundError:
                    pass
                finally_cleanup_files.append(str(export_path))
                export_stream_types = [export["stype"]]
                extra_opts: List[str] = ["-map", f"0:{spec}"]
                extra_opts += _metadata_copy_args(export_stream_types)
                extra_opts += FFMPEG_OUTPUT_FLAGS
                muxer = export.get("muxer") or "matroska"
                if muxer == "data":
                    extra_opts += ["-c", "copy", "-f", "data", str(export_path)]
                else:
                    extra_opts += ["-c", "copy", "-f", muxer, str(export_path)]
                encode_outputs.append(extra_opts)

            for output_opts in encode_outputs:
                encode_cmd.extend(output_opts)

            _print_command(encode_cmd)
            encode_proc = subprocess.run(encode_cmd, env=env)
            if encode_proc.returncode != 0:
                logging.error("encode failed for %s", src)
                mark_pending(f"encode exited with code {encode_proc.returncode}")
                continue

            if not encode_output_path.exists():
                logging.error("expected encoded output missing for %s", src)
                mark_pending("encoded output missing")
                continue

            missing_exports = False
            for export in exports:
                export_path = pathlib.Path(export["path"])
                if not export_path.exists():
                    logging.error(
                        "expected auxiliary export missing for %s stream %s",
                        src,
                        export.get("spec"),
                    )
                    missing_exports = True
            if missing_exports:
                mark_pending("auxiliary export missing")
                continue

            all_video_mkv_ok = bool(video_infos) and all(
                info.get("mkv_ok") for info in video_infos
            )
            all_audio_mkv_ok = all(info.get("mkv_ok") for info in audio_infos)
            perform_size_check = (
                bool(video_infos) and all_video_mkv_ok and all_audio_mkv_ok
            )

            selected_output_path = encode_output_path
            if perform_size_check:
                try:
                    encoded_size = encode_output_path.stat().st_size
                    original_size = os.path.getsize(stage_src)
                except OSError as exc:
                    logging.warning("failed to compare sizes for %s: %s", src, exc)
                else:
                    if encoded_size >= original_size:
                        logging.info(
                            "encoded output larger than source; considering original remux for %s",
                            src,
                        )
                        remux_source_path = streams_root / f"{base_name}.original.mkv"
                        finally_cleanup_files.append(str(remux_source_path))
                        remux_cmd = ["ffmpeg"]
                        if args.verbose:
                            remux_cmd += ["-stats", "-loglevel", "info"]
                        else:
                            remux_cmd += ["-hide_banner", "-loglevel", "warning"]
                        remux_cmd += [
                            "-y",
                            "-ignore_unknown",
                        ]
                        remux_cmd += FFMPEG_INPUT_FLAGS
                        remux_cmd += [
                            "-i",
                            stage_src,
                        ]
                        remux_stream_types: List[str] = []
                        mapped_video = False
                        if all_video_mkv_ok:
                            for info in video_infos:
                                spec = info.get("spec")
                                if not spec:
                                    continue
                                remux_cmd += ["-map", f"0:{spec}"]
                                mapped_video = True
                        if mapped_video:
                            remux_stream_types.append("v")
                        mapped_audio = False
                        if all_audio_mkv_ok:
                            for info in audio_infos:
                                spec = info.get("spec")
                                if not spec:
                                    continue
                                remux_cmd += ["-map", f"0:{spec}"]
                                mapped_audio = True
                        if mapped_audio:
                            remux_stream_types.append("a")
                        for info in subtitle_infos:
                            spec = info.get("spec")
                            if not spec:
                                continue
                            remux_cmd += ["-map", f"0:{spec}"]
                        if subtitle_infos:
                            remux_stream_types.append("s")
                        for info in attachment_infos:
                            spec = info.get("spec")
                            if not spec:
                                continue
                            remux_cmd += ["-map", f"0:{spec}"]
                        if attachment_infos:
                            remux_stream_types.append("t")
                        remux_cmd += _metadata_copy_args(remux_stream_types)
                        remux_cmd += FFMPEG_OUTPUT_FLAGS
                        if mapped_video:
                            remux_cmd += ["-c:v", "copy"]
                        if mapped_audio:
                            remux_cmd += ["-c:a", "copy"]
                        if subtitle_infos:
                            remux_cmd += ["-c:s", "copy"]
                        if attachment_infos:
                            remux_cmd += ["-c:t", "copy"]
                        remux_cmd += [
                            "-f",
                            "matroska",
                            str(remux_source_path),
                        ]
                        _print_command(remux_cmd)
                        remux_proc = subprocess.run(remux_cmd)
                        if remux_proc.returncode != 0:
                            logging.warning(
                                "original remux failed for %s; keeping encoded output",
                                src,
                            )
                        elif not remux_source_path.exists():
                            logging.warning(
                                "expected original remux output missing for %s; keeping encoded output",
                                src,
                            )
                        else:
                            selected_output_path = remux_source_path
                            metadata["used_original"] = True

            attachment_entries: List[Tuple[pathlib.Path, str, str]] = []
            for export in exports:
                export_path = pathlib.Path(export["path"])
                stream = export.get("stream", {})
                codec_hint = cast(
                    str,
                    (
                        stream.get("codec_name")
                        or stream.get("codec_tag_string")
                        or "unknown"
                    ),
                )
                description = f"{export['stype'].upper()} stream export ({codec_hint})"
                attachment_entries.append(
                    (export_path, description, _guess_mime_type(export_path))
                )
                packet_sidecar = _packet_sidecar_path(export, export_path)
                if packet_sidecar is not None and packet_sidecar.exists():
                    attachment_entries.append(
                        (
                            packet_sidecar,
                            f"{export['stype'].upper()} stream packet timestamps",
                            "application/json",
                        )
                    )

            for attachment in attachments:
                attachment_entries.append(
                    (
                        attachment,
                        f"Container attachment copy ({attachment.name})",
                        _guess_mime_type(attachment),
                    )
                )

            if metadata_sidecar is not None:
                if metadata_sidecar.exists():
                    attachment_entries.append(
                        (
                            metadata_sidecar,
                            "Pre-re-encode metadata",
                            "application/json",
                        )
                    )
                finally_cleanup_files.append(str(metadata_sidecar))

            mux_cmd = [
                "mkvmerge",
                "-o",
                remux_output,
                "--disable-track-statistics-tags",
                str(selected_output_path),
            ]
            _print_command(mux_cmd)
            mux_proc = subprocess.run(mux_cmd)
            if mux_proc.returncode != 0:
                logging.error("mkvmerge failed for %s", src)
                mark_pending(f"mkvmerge exited with code {mux_proc.returncode}")
                continue

            if not os.path.exists(remux_output):
                logging.error("expected remuxed output missing for %s", src)
                mark_pending("remuxed output missing")
                continue

            try:
                os.replace(remux_output, stage_part)
            except OSError as exc:
                logging.error("failed to finalize remuxed output for %s: %s", src, exc)
                mark_pending("failed to finalize remuxed output")
                continue
            creation_date_to_apply = original_creation_date
            if not creation_date_to_apply:
                for key_name in ("creation_time", "com.apple.quicktime.creationdate"):
                    raw_value = container_tags.get(key_name)
                    if isinstance(raw_value, str):
                        parsed = _parse_creation_date(raw_value)
                        if parsed:
                            creation_date_to_apply = parsed
                            break
            try:
                _apply_container_metadata(
                    stage_part,
                    creation_date_to_apply,
                    container_tags,
                    finally_cleanup_files,
                )
            except RuntimeError as exc:
                logging.error("failed to apply container metadata for %s: %s", src, exc)
                mark_pending("failed to apply container metadata")
                continue

            try:
                _attach_sidecar_files(stage_part, attachment_entries)
            except RuntimeError as exc:
                logging.error("failed to attach auxiliary outputs for %s: %s", src, exc)
                mark_pending("failed to attach auxiliary outputs")
                continue

            try:
                shutil.copy2(stage_part, part_path)
                _apply_source_timestamps(src, part_path, st)
            except Exception as e:
                logging.error("failed to copy staged result to output: %s", e)
                mark_pending("failed to copy staged result")
                continue

            os.replace(part_path, final_path)

            rec.update({"status": "done", "finished_at": now_utc_iso()})
            manifest["items"][key] = rec
            save_manifest(manifest, manifest_path)
            encoded_count += 1

        finally:
            for pth in finally_cleanup_files:
                try:
                    if os.path.exists(pth):
                        os.remove(pth)
                except FileNotFoundError:
                    pass
            if streams_root.exists():
                shutil.rmtree(streams_root, ignore_errors=True)

    videos_by_dir: dict[str, list[dict[str, Any]]] = {}
    for meta in video_metadata:
        videos_by_dir.setdefault(meta["dir"], []).append(meta)

    asset_renames: dict[str, str] = {}
    for asset in assets:
        asset_dir = os.path.abspath(os.path.dirname(asset))
        asset_base = os.path.basename(asset)
        for meta in videos_by_dir.get(asset_dir, []):
            if meta.get("used_original"):
                continue
            if not meta["ext_changed"]:
                continue
            original_name = meta["original"]
            if original_name and original_name in asset_base:
                new_base = asset_base.replace(original_name, meta["desired"], 1)
                if new_base != asset_base:
                    asset_renames[asset] = new_base
                break

    copied_assets = copy_assets(
        assets,
        args.output_dir,
        asset_renames,
        manifest=manifest,
        manifest_path=manifest_path,
    )
    for asset_src, dest_name in copied_assets:
        output_by_input[os.path.abspath(asset_src)] = os.path.normpath(dest_name)

    ordered_outputs: list[str] = []
    for src in all_files:
        dest_rel = output_by_input.get(os.path.abspath(src))
        if dest_rel:
            ordered_outputs.append(dest_rel)

    if use_constant_quality:
        save_manifest(manifest, manifest_path)
    logging.warning("videos encoded (this run): %d / %d", encoded_count, len(videos))
    if all_videos_done(manifest, args.output_dir):
        logging.warning("all videos complete; manifest retained at %s", manifest_path)


if __name__ == "__main__":
    main()
