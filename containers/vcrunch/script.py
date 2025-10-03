#!/usr/bin/env python3

import argparse
import hashlib
import json
import logging
import os
import pathlib
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any, List, Optional, Sequence, TypedDict, cast

OUT_EXT = ".mkv"
DEFAULT_SUFFIX = ""
MANIFEST_NAME = ".job.json"
MAX_SVT_KBPS = 100_000
DEFAULT_TARGET_SIZE = "23.30G"
DEFAULT_SAFETY_OVERHEAD = 0.012


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


def _duration_from_timebase(duration_ts: Any, time_base: Any) -> Optional[float]:
    if duration_ts is None or time_base is None:
        return None
    try:
        ts = float(duration_ts)
    except (TypeError, ValueError):
        try:
            ts = float(str(duration_ts).strip())
        except (ValueError, TypeError):
            return None
    base = _parse_fraction(time_base)
    if base is None:
        return None
    return ts * base


def _duration_from_frames(stream: dict[str, Any]) -> Optional[float]:
    nb_frames = stream.get("nb_frames")
    if nb_frames in (None, "N/A"):
        return None
    try:
        frames = float(str(nb_frames))
    except (TypeError, ValueError):
        return None
    fps = _parse_fraction(stream.get("avg_frame_rate"))
    if fps is None or fps <= 0:
        fps = _parse_fraction(stream.get("r_frame_rate"))
    if fps is None or fps <= 0:
        return None
    return frames / fps


def _parse_frame_count(value: Any) -> Optional[float]:
    if value in (None, "N/A"):
        return None
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def probe_media_info(path: str) -> MediaProbeResult:
    cmd = [
        "ffprobe",
        "-count_frames",
        "-hide_banner",
        "-loglevel",
        "error",
        "-show_entries",
        (
            "format=duration:format_tags=DURATION:stream="
            "codec_type,duration,duration_ts,time_base,avg_frame_rate,nb_frames,"
            "nb_read_frames,r_frame_rate"
        ),
        "-of",
        "json",
        "-i",
        path,
    ]
    try:
        data = ffprobe_json(cmd)
    except subprocess.CalledProcessError as exc:
        err = ""
        if getattr(exc, "stderr", None):
            err = exc.stderr.decode("utf-8", "replace").strip()
        failure: MediaProbeResult = {"is_video": False, "duration": None}
        if err:
            failure["error"] = err
        return failure

    has_video_stream = False
    positive_stream_durations: list[float] = []
    streams = data.get("streams")
    if isinstance(streams, list):
        for stream in streams:
            if not isinstance(stream, dict):
                continue
            if stream.get("codec_type") != "video":
                continue
            has_video_stream = True
            frame_count = _parse_frame_count(stream.get("nb_frames"))
            if frame_count is None:
                frame_count = _parse_frame_count(stream.get("nb_read_frames"))
            stream_duration = _parse_duration_value(stream.get("duration"))
            if stream_duration is None:
                stream_duration = _duration_from_timebase(
                    stream.get("duration_ts"), stream.get("time_base")
                )
            if stream_duration is None:
                stream_duration = _duration_from_frames(stream)
            if (
                stream_duration is not None
                and stream_duration > 0
                and (frame_count is None or frame_count > 1)
            ):
                positive_stream_durations.append(stream_duration)

    has_video = has_video_stream and bool(positive_stream_durations)

    duration = positive_stream_durations[0] if positive_stream_durations else None
    success: MediaProbeResult = {"is_video": has_video, "duration": duration}
    return success


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
    assets: List[str], out_dir: str, rename_map: Optional[dict[str, str]] = None
) -> list[tuple[str, str]]:
    copied: list[tuple[str, str]] = []
    rename_map = rename_map or {}
    for src in assets:
        dest_name = rename_map.get(src, os.path.basename(src))
        dest = os.path.join(out_dir, dest_name)
        if os.path.abspath(src) == os.path.abspath(dest):
            continue
        try:
            shutil.copy2(src, dest)
            logging.info("copied asset: %s -> %s", src, dest)
            copied.append((src, dest_name))
        except Exception as e:
            logging.error("failed to copy asset %s -> %s: %s", src, dest, e)
    return copied


def group_outputs_by_target_size(
    output_dir: str,
    manifest: dict[str, Any],
    manifest_name: str,
    target_bytes: int,
    ordered_relpaths: Sequence[str],
) -> None:
    if target_bytes <= 0:
        logging.warning("target bytes <= 0; skipping grouping into directories")
        return

    files: list[tuple[str, int]] = []
    for root, _, filenames in os.walk(output_dir):
        for name in filenames:
            rel = os.path.relpath(os.path.join(root, name), output_dir)
            norm_rel = os.path.normpath(rel)
            if os.path.normpath(manifest_name) == norm_rel:
                continue
            if name.endswith(".part"):
                continue
            path = os.path.join(output_dir, rel)
            try:
                size = os.path.getsize(path)
            except FileNotFoundError:
                continue
            files.append((rel, size))

    if not files:
        return

    order_map: dict[str, int] = {}
    for idx, rel in enumerate(ordered_relpaths):
        norm = os.path.normpath(rel)
        if norm not in order_map:
            order_map[norm] = idx

    def sort_key(item: tuple[str, int]) -> tuple[int, int | str, str]:
        rel, _size = item
        norm_rel = os.path.normpath(rel)
        if norm_rel in order_map:
            return (0, order_map[norm_rel], norm_rel)
        return (1, norm_rel.lower(), norm_rel)

    files.sort(key=sort_key)

    filtered_files: list[tuple[str, int]] = []
    seen_names: set[str] = set()
    for rel, size in files:
        base = pathlib.Path(rel).name
        if base in seen_names:
            try:
                os.remove(os.path.join(output_dir, rel))
            except OSError:
                pass
            continue
        seen_names.add(base)
        filtered_files.append((rel, size))

    files = filtered_files

    groups: list[list[tuple[str, int]]] = []
    current: list[tuple[str, int]] = []
    current_size = 0
    for rel, size in files:
        if current and current_size + size > target_bytes:
            groups.append(current)
            current = []
            current_size = 0
        current.append((rel, size))
        current_size += size
    if current:
        groups.append(current)

    tmp_base = os.path.join(output_dir, ".vcrunch_grouping")
    if os.path.exists(tmp_base):
        shutil.rmtree(tmp_base)
    os.makedirs(tmp_base, exist_ok=True)

    dest_rel_map: dict[str, str] = {}
    used_names: set[str] = set()

    def unique_name(name: str) -> str:
        if name not in used_names:
            used_names.add(name)
            return name
        stem, ext = os.path.splitext(name)
        idx = 1
        while True:
            candidate = f"{stem}_{idx}{ext}"
            if candidate not in used_names:
                used_names.add(candidate)
                return candidate
            idx += 1

    for idx, group in enumerate(groups, start=1):
        subdir_name = f"{idx:02d}"
        subdir_tmp = os.path.join(tmp_base, subdir_name)
        os.makedirs(subdir_tmp, exist_ok=True)
        for rel, _ in group:
            src = os.path.join(output_dir, rel)
            if not os.path.exists(src):
                continue
            dest_name = unique_name(os.path.basename(rel))
            dest_rel = os.path.normpath(os.path.join(subdir_name, dest_name))
            dest_path = os.path.join(subdir_tmp, dest_name)
            if os.path.exists(dest_path):
                os.remove(dest_path)
            shutil.move(src, dest_path)
            dest_rel_map[os.path.normpath(rel)] = dest_rel

    for root_dir, dirs, _ in os.walk(output_dir, topdown=False):
        if os.path.normpath(root_dir) == os.path.normpath(tmp_base):
            continue
        if os.path.normpath(root_dir) == os.path.normpath(output_dir):
            continue
        for d in dirs:
            d_path = os.path.join(root_dir, d)
            if os.path.normpath(d_path) == os.path.normpath(tmp_base):
                continue
            try:
                os.rmdir(d_path)
            except OSError:
                pass

    for idx, _ in enumerate(groups, start=1):
        subdir_name = f"{idx:02d}"
        src_dir = os.path.join(tmp_base, subdir_name)
        dest_dir = os.path.join(output_dir, subdir_name)
        if os.path.exists(dest_dir):
            shutil.rmtree(dest_dir)
        if os.path.exists(src_dir):
            shutil.move(src_dir, dest_dir)

    shutil.rmtree(tmp_base, ignore_errors=True)

    manifest_items = manifest.get("items", {})
    output_map: dict[str, dict[str, Any]] = {}
    for rec in manifest_items.values():
        if rec.get("type") != "video":
            continue
        output_rel = rec.get("output")
        if not output_rel:
            continue
        output_map[os.path.normpath(output_rel)] = rec

    for original_rel, new_rel in dest_rel_map.items():
        rec = output_map.get(original_rel)
        if rec is not None:
            rec["output"] = new_rel

    logging.info(
        "grouped outputs into %d director%s",
        len(groups),
        "y" if len(groups) == 1 else "ies",
    )


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
    if all_videos_done(manifest, args.output_dir):
        logging.warning(
            "already complete; manifest indicates all videos are done and outputs are valid"
        )
        logging.info("manifest: %s", manifest_path)
        return

    inputs: List[str] = []
    if args.paths_from:
        inputs += read_paths_from(args.paths_from)
    inputs += args.input
    all_files = collect_all_files([p for p in inputs if p], args.pattern)
    if not all_files:
        logging.error("no input files found")
        sys.exit(1)

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
            error_value = probe_result.get("error")
            if error_value:
                entry["error"] = str(error_value)
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

    target_bytes = parse_size(target_size_str)
    total_input_bytes = 0
    for src in all_files:
        try:
            total_input_bytes += os.path.getsize(src)
        except FileNotFoundError:
            pass

    if total_input_bytes <= target_bytes:
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

    use_constant_quality = args.constant_quality is not None
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
        if use_constant_quality:
            logging.info("constant quality mode: files will be grouped by target size")
        else:
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
        out_name = f"{stem}{args.name_suffix}{OUT_EXT}"
        video_metadata.append(
            {
                "dir": os.path.abspath(os.path.dirname(src)),
                "original": os.path.basename(src),
                "desired": out_name,
                "ext_changed": ext.lower() != OUT_EXT.lower(),
            }
        )
        h = _short_hash(os.path.abspath(src))
        stage_src = os.path.join(args.stage_dir, f"{stem}.{h}{ext}")
        stage_part = os.path.join(args.stage_dir, out_name + ".part")
        key = src_key(os.path.abspath(src), st)
        rec = manifest["items"].get(
            key, {"type": "video", "src": src, "output": out_name, "status": "pending"}
        )

        output_rel = rec.get("output") or out_name
        rec["output"] = output_rel
        output_by_input[os.path.abspath(src)] = os.path.normpath(output_rel)
        final_path = os.path.join(args.output_dir, output_rel)
        final_dir = os.path.dirname(final_path)
        if final_dir and not os.path.exists(final_dir):
            os.makedirs(final_dir, exist_ok=True)
        part_path = final_path + ".part"

        for stale in (part_path, stage_part):
            if os.path.exists(stale):
                try:
                    os.remove(stale)
                except FileNotFoundError:
                    pass

        if (
            os.path.exists(final_path)
            and rec.get("status") == "done"
            and is_valid_media(final_path)
        ):
            logging.info("skip done: %s", final_path)
            continue

        if os.path.exists(final_path) and not is_valid_media(final_path):
            try:
                os.remove(final_path)
            except FileNotFoundError:
                pass

        try:
            if os.path.exists(stage_src):
                try:
                    os.remove(stage_src)
                except FileNotFoundError:
                    pass
            if args.verbose:
                logging.info("staging -> %s", stage_src)
            shutil.copy2(src, stage_src)
        except Exception as e:
            logging.error("failed to stage source %s -> %s: %s", src, stage_src, e)
            continue

        audio_kbps = max(1, int(audio_bps / 1000))
        ff = [
            "ffmpeg",
        ]
        if args.verbose:
            ff += [
                "-stats",
                "-loglevel",
                "info",
            ]
        else:
            ff += [
                "-hide_banner",
                "-loglevel",
                "warning",
            ]
        ff += [
            "-y",
            "-ignore_unknown",
            "-ignore_editlist",
            "1",
            "-i",
            stage_src,
            "-map",
            "0:v:0",
            "-map",
            "0:a?",
            "-map",
            "0:s?",
            "-fps_mode",
            "passthrough",
            "-c:v",
            "libsvtav1",
        ]
        if use_constant_quality:
            ff += ["-crf", str(args.constant_quality), "-b:v", "0"]
        else:
            ff += ["-b:v", f"{global_video_kbps}k"]
        ff += [
            "-g",
            "240",
            "-preset",
            "5",
            "-svtav1-params",
            f"lp={args.svt_lp}",
            "-c:a",
            "libopus",
            "-b:a",
            f"{audio_kbps}k",
            "-c:s",
            "copy",
            "-cues_to_front",
            "1",
            "-reserve_index_space",
            "200k",
            "-f",
            "matroska",
            stage_part,
        ]

        rec.update(
            {
                "status": "encoding_started",
                "started_at": now_utc_iso(),
                "output": output_rel,
            }
        )
        manifest["items"][key] = rec
        save_manifest(manifest, manifest_path)

        try:
            logging.debug("+ %s", " ".join(map(str, ff)))
            env = os.environ.copy()

            if not args.verbose:
                env["SVT_LOG"] = "2"
            else:
                env["SVT_LOG"] = "4"

            p = subprocess.run(ff, env=env)
            if p.returncode != 0:
                logging.error("ffmpeg failed for %s", src)
                continue

            if not is_valid_media(stage_part):
                logging.error("encoded output invalid (staged): %s", stage_part)
                continue

            try:
                shutil.copy2(stage_part, part_path)
            except Exception as e:
                logging.error("failed to copy staged result to output: %s", e)
                continue

            os.replace(part_path, final_path)
            rec.update({"status": "done", "finished_at": now_utc_iso()})
            manifest["items"][key] = rec
            save_manifest(manifest, manifest_path)
            encoded_count += 1

        finally:
            for pth in (stage_part, stage_src):
                try:
                    if os.path.exists(pth):
                        os.remove(pth)
                except FileNotFoundError:
                    pass

    videos_by_dir: dict[str, list[dict[str, Any]]] = {}
    for info in video_metadata:
        videos_by_dir.setdefault(info["dir"], []).append(info)

    asset_renames: dict[str, str] = {}
    for asset in assets:
        asset_dir = os.path.abspath(os.path.dirname(asset))
        asset_base = os.path.basename(asset)
        for info in videos_by_dir.get(asset_dir, []):
            if not info["ext_changed"]:
                continue
            original_name = info["original"]
            if original_name and original_name in asset_base:
                new_base = asset_base.replace(original_name, info["desired"], 1)
                if new_base != asset_base:
                    asset_renames[asset] = new_base
                break

    copied_assets = copy_assets(assets, args.output_dir, asset_renames)
    for asset_src, dest_name in copied_assets:
        output_by_input[os.path.abspath(asset_src)] = os.path.normpath(dest_name)

    ordered_outputs: list[str] = []
    for src in all_files:
        dest_rel = output_by_input.get(os.path.abspath(src))
        if dest_rel:
            ordered_outputs.append(dest_rel)

    if use_constant_quality:
        group_outputs_by_target_size(
            args.output_dir,
            manifest,
            args.manifest_name,
            target_bytes,
            ordered_outputs,
        )
        save_manifest(manifest, manifest_path)
    logging.warning("videos encoded (this run): %d / %d", encoded_count, len(videos))
    if all_videos_done(manifest, args.output_dir):
        logging.warning("all videos complete; manifest retained at %s", manifest_path)


if __name__ == "__main__":
    main()
