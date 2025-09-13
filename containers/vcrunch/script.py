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

VIDEO_EXTS = {
    ".mp4",
    ".mov",
    ".mkv",
    ".avi",
    ".m4v",
    ".webm",
    ".mpg",
    ".mpeg",
    ".wmv",
    ".flv",
}
OUT_EXT = ".mkv"
DEFAULT_SUFFIX = "_vcrunch_av1"
MANIFEST_NAME = ".job.json"
MAX_SVT_KBPS = 100_000
DEFAULT_TARGET_SIZE = "23.30G"
DEFAULT_SAFETY_OVERHEAD = 0.012


class MediaPreset(TypedDict):
    target_size: str
    safety_overhead: float


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
    out = subprocess.check_output(cmd)
    return cast(dict[str, Any], json.loads(out))


def ffprobe_duration(path: str) -> float:
    data = ffprobe_json(
        [
            "ffprobe",
            "-hide_banner",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            "-i",
            path,
        ]
    )
    return float(data["format"]["duration"])


def is_valid_media(path: str) -> bool:
    try:
        return ffprobe_duration(path) > 0.0
    except Exception:
        return False


def collect_all_files(paths: List[str], pattern: Optional[str]) -> List[str]:
    files = []
    for p in paths:
        p = os.path.abspath(p)
        if os.path.isfile(p):
            files.append(p)
        elif os.path.isdir(p):
            for root, _, fn in os.walk(p):
                for f in fn:
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
        return {"version": 1, "updated": now_utc_iso(), "items": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            m = cast(dict[str, Any], json.load(f))
            if "items" not in m:
                m["items"] = {}
            return m
    except Exception:
        return {"version": 1, "updated": now_utc_iso(), "items": {}}


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


def copy_assets(assets: List[str], out_dir: str) -> None:
    for src in assets:
        dest = os.path.join(out_dir, os.path.basename(src))
        if os.path.abspath(src) == os.path.abspath(dest):
            continue
        try:
            shutil.copy2(src, dest)
            logging.info("copied asset: %s -> %s", src, dest)
        except Exception as e:
            logging.error("failed to copy asset %s -> %s: %s", src, dest, e)


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

    videos = [p for p in all_files if pathlib.Path(p).suffix.lower() in VIDEO_EXTS]
    assets = [p for p in all_files if pathlib.Path(p).suffix.lower() not in VIDEO_EXTS]

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
            if pathlib.Path(src).suffix.lower() in VIDEO_EXTS:
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
        d = ffprobe_duration(src)
        durations.append(d)
        total_duration += d
        total_audio_bytes += int((audio_bps / 8.0) * d)

    reserved = int(target_bytes * safety_overhead) + 20_000_000
    video_budget_bytes = target_bytes - asset_bytes - total_audio_bytes - reserved
    if video_budget_bytes <= 0 and videos:
        logging.error("assets + audio + overhead exceed target size; no room for video")
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
        total_duration / 3600,
        f"{total_audio_bytes:,}",
    )
    if videos:
        logging.info(
            "video budget bytes: %s; avg video bitrate: %s kbps (using %s kbps)",
            f"{max(0, video_budget_bytes):,}",
            f"{computed_kbps:,}",
            f"{global_video_kbps:,}",
        )
    else:
        logging.info("no videos to encode")

    encoded_count = 0
    for src, dur in zip(videos, durations):
        st = os.stat(src)
        stem = sanitize_base(pathlib.Path(src).stem)
        ext = pathlib.Path(src).suffix
        out_name = f"{stem}{args.name_suffix}{OUT_EXT}"
        final_path = os.path.join(args.output_dir, out_name)
        part_path = final_path + ".part"
        h = _short_hash(os.path.abspath(src))
        stage_src = os.path.join(args.stage_dir, f"{stem}.{h}{ext}")
        stage_part = os.path.join(args.stage_dir, out_name + ".part")
        key = src_key(os.path.abspath(src), st)
        rec = manifest["items"].get(
            key, {"type": "video", "src": src, "output": out_name, "status": "pending"}
        )

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

        video_kbps = global_video_kbps
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
            "-b:v",
            f"{video_kbps}k",
            "-g",
            "240",
            "-preset",
            "5",
            "-svtav1-params",
            "lp=5",
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
                "output": out_name,
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

    copy_assets(assets, args.output_dir)
    logging.warning("videos encoded (this run): %d / %d", encoded_count, len(videos))
    if all_videos_done(manifest, args.output_dir):
        logging.warning("all videos complete; manifest retained at %s", manifest_path)


if __name__ == "__main__":
    main()
