#!/usr/bin/env python3
import argparse, os, sys, subprocess, json, time, shutil, pathlib, hashlib
from typing import List, Optional
from datetime import datetime, timezone

# --- constants ---
VIDEO_EXTS = {".mp4",".mov",".mkv",".avi",".m4v",".webm",".mpg",".mpeg",".wmv",".flv"}
OUT_EXT = ".mkv"
DEFAULT_SUFFIX = "_vcrunch_av1"
MANIFEST_NAME = ".job.json"
MAX_SVT_KBPS = 100_000  # libsvtav1 maximum accepted target bitrate

# --- tiny utils ---
def eprint(*a, **k): print(*a, **k, file=sys.stderr)

def parse_size(s: str) -> int:
    s = s.strip().lower().replace("ib","")
    mult = 1
    if s.endswith("k"): mult = 1024; s = s[:-1]
    elif s.endswith("m"): mult = 1024**2; s = s[:-1]
    elif s.endswith("g"): mult = 1024**3; s = s[:-1]
    elif s.endswith("t"): mult = 1024**4; s = s[:-1]
    return int(float(s) * mult)

def kbps_to_bps(s: str) -> int:
    s = s.strip().lower()
    if s.endswith("k"): return int(float(s[:-1]) * 1000)
    if s.endswith("m"): return int(float(s[:-1]) * 1_000_000)
    return int(float(s))

def ffprobe_json(cmd: list) -> dict:
    out = subprocess.check_output(cmd)
    return json.loads(out)

def ffprobe_duration(path: str) -> float:
    data = ffprobe_json([
        "ffprobe","-hide_banner","-v","error",
        "-show_entries","format=duration","-of","json","-i",path
    ])
    return float(data["format"]["duration"])

def is_valid_media(path: str) -> bool:
    try:
        return ffprobe_duration(path) > 0.0
    except Exception:
        return False

def run(cmd: list):
    eprint("+", " ".join(map(str, cmd)))
    p = subprocess.run(cmd)
    if p.returncode != 0:
        raise SystemExit(p.returncode)

def collect_all_files(paths: List[str], pattern: Optional[str]) -> List[str]:
    files = []
    for p in paths:
        p = os.path.abspath(p)
        if os.path.isfile(p):
            files.append(p)
        elif os.path.isdir(p):
            for root,_,fn in os.walk(p):
                for f in fn:
                    fp = os.path.abspath(os.path.join(root, f))
                    if os.path.isfile(fp): files.append(fp)
    if pattern:
        files = [p for p in files if pathlib.PurePath(p).match(pattern)]
    return sorted(set(files))

def read_paths_from(fpath: str) -> List[str]:
    fh = sys.stdin if fpath == "-" else open(fpath,"r",encoding="utf-8")
    with fh:
        return [ln.strip() for ln in fh if ln.strip()]

def sanitize_base(stem: str) -> str:
    base = os.path.basename(stem).replace("\\","_")
    while base.startswith("."): base = base[1:]
    return base or "file"

def now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def load_manifest(path: str) -> dict:
    if not os.path.exists(path):
        return {"version":1,"updated":now_utc_iso(),"items":{}}
    try:
        with open(path,"r",encoding="utf-8") as f:
            m = json.load(f)
            if "items" not in m: m["items"] = {}
            return m
    except Exception:
        return {"version":1,"updated":now_utc_iso(),"items":{}}

def save_manifest(manifest: dict, path: str):
    manifest["updated"] = now_utc_iso()
    tmp = path + ".tmp"
    with open(tmp,"w",encoding="utf-8") as f:
        json.dump(manifest, f, indent=2); f.write("\n")
    os.replace(tmp, path)

def src_key(src_abs: str, st: os.stat_result) -> str:
    return f"{src_abs}|{st.st_size}|{int(st.st_mtime)}"

def all_videos_done(manifest: dict, out_dir: str) -> bool:
    """Success = every video record is status=done and output file exists & is valid.
       Also requires at least one video record."""
    saw_video = False
    for rec in manifest.get("items", {}).values():
        if rec.get("type") != "video":
            continue
        saw_video = True
        out_name = rec.get("output")
        if not out_name:
            return False
        fp = os.path.join(out_dir, out_name)
        if not (rec.get("status") == "done" and os.path.exists(fp) and is_valid_media(fp)):
            return False
    return saw_video

# --- main ---
def main():
    ap = argparse.ArgumentParser(
        description="Encode videos (SVT-AV1 defaults) with resume manifest. "
                    "Non-video files are NOT copied, but their sizes are accounted from inputs."
    )
    # Inputs
    ap.add_argument("--input", action="append", default=["/in"], help="File or directory (repeatable).")
    ap.add_argument("--paths-from", help="Newline-delimited paths, or '-' for stdin.")
    ap.add_argument("--pattern", default=None, help="Optional glob to filter inputs (e.g., '*').")

    # Targeting (default 25G)
    ap.add_argument("--target-size", default="25G", help="Total target size (default 25G).")
    ap.add_argument("--audio-bitrate", default="128k", help="Per-title audio bitrate (e.g., 128k).")
    ap.add_argument("--safety-overhead", type=float, default=0.06, help="Reserve fraction for mux/fs overhead.")

    # Output dir + manifest
    ap.add_argument("--output-dir", default="/out", help="Output directory.")
    ap.add_argument("--manifest-name", default=MANIFEST_NAME, help="Manifest filename under output dir.")
    ap.add_argument("--name-suffix", default=DEFAULT_SUFFIX, help="Suffix before extension for encoded files.")

    args = ap.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    manifest_path = os.path.join(args.output_dir, args.manifest_name)
    manifest = load_manifest(manifest_path)

    # --- EARLY EXIT if manifest already shows success ---
    if all_videos_done(manifest, args.output_dir):
        eprint("=== encode_videos: already complete ===")
        eprint("Manifest indicates all videos are done and outputs are valid. Nothing to do.")
        eprint(f"Manifest: {manifest_path}")
        return  # return immediately without touching anything

    # Gather inputs
    inputs = []
    if args.paths_from: inputs += read_paths_from(args.paths_from)
    inputs += args.input

    all_files = collect_all_files([p for p in inputs if p], args.pattern)
    if not all_files:
        eprint("No input files found."); sys.exit(1)

    # Split
    videos = [p for p in all_files if pathlib.Path(p).suffix.lower() in VIDEO_EXTS]
    assets = [p for p in all_files if pathlib.Path(p).suffix.lower() not in VIDEO_EXTS]

    eprint("=== encode_videos: start ===")
    eprint(f"Outputs -> {args.output_dir}")
    eprint(f"Total inputs: {len(all_files)}  (videos: {len(videos)}, assets: {len(assets)})")
    eprint("Note: No staging or deleting will occur. Assets are only accounted for sizing; they are not copied.")

    # Account assets directly from inputs (no copying)
    asset_bytes = 0
    for src in assets:
        try:
            asset_bytes += os.path.getsize(src)
        except FileNotFoundError:
            pass

    # Compute bitrate budget for videos
    target_bytes = parse_size(args.target_size)
    audio_bps = kbps_to_bps(args.audio_bitrate)

    total_duration = 0.0
    total_audio_bytes = 0
    durations = []
    for src in videos:
        d = ffprobe_duration(src)
        durations.append(d)
        total_duration += d
        total_audio_bytes += int((audio_bps/8.0)*d)

    reserved = int(target_bytes * args.safety_overhead) + 20_000_000
    video_budget_bytes = target_bytes - asset_bytes - total_audio_bytes - reserved

    if video_budget_bytes <= 0 and videos:
        eprint("ERROR: Assets + audio + overhead exceed target size; no room left for video.")
        sys.exit(1)

    avg_video_bps = 0
    if videos:
        if total_duration <= 0:
            eprint("ERROR: Total video duration is zero; cannot compute bitrate."); sys.exit(1)
        avg_video_bps = int((video_budget_bytes * 8) / total_duration)
        if avg_video_bps < 50_000:  # 50 kbps sanity check
            eprint("ERROR: Computed video bitrate unrealistically low."); sys.exit(1)

    # Choose encoder target kbps (clamped to SVT max)
    computed_kbps = max(1, int(avg_video_bps/1000)) if avg_video_bps else 1
    if computed_kbps > MAX_SVT_KBPS:
        eprint(f"Warn: computed average video bitrate {computed_kbps} kbps exceeds SVT-AV1 max "
               f"{MAX_SVT_KBPS} kbps; clamping to {MAX_SVT_KBPS} kbps. "
               f"Final size will undershoot target.")
        global_video_kbps = MAX_SVT_KBPS
    else:
        global_video_kbps = computed_kbps

    eprint(f"Target size: {target_bytes:,} bytes")
    eprint(f"Assets accounted (no copy): {asset_bytes:,} bytes")
    eprint(f"Video duration: {total_duration/3600:.2f} h; Audio bytes: {total_audio_bytes:,}")
    if videos:
        eprint(f"Video budget: {max(0,video_budget_bytes):,} bytes; "
               f"Avg video bitrate: {computed_kbps:,} kbps (using {global_video_kbps:,} kbps)")
    else:
        eprint("No videos to encode.")

    # Encode videos (SVT-AV1 defaults)
    encoded_count = 0
    for (src, dur) in zip(videos, durations):
        st = os.stat(src)
        stem = sanitize_base(pathlib.Path(src).stem)
        out_name = f"{stem}{args.name_suffix}{OUT_EXT}"
        final_path = os.path.join(args.output_dir, out_name)
        part_path  = final_path + ".part"

        key = src_key(os.path.abspath(src), st)
        rec = manifest["items"].get(key, {"type":"video","src":src,"output":out_name,"status":"pending"})

        # Clean stale partial
        if os.path.exists(part_path):
            eprint(f"Removing stale partial: {part_path}")
            try: os.remove(part_path)
            except FileNotFoundError: pass

        # Skip when already done & valid
        if os.path.exists(final_path) and rec.get("status")=="done" and is_valid_media(final_path):
            eprint(f"Skip (done): {final_path}")
            continue

        # Re-encode if invalid existing
        if os.path.exists(final_path) and not is_valid_media(final_path):
            eprint(f"Invalid existing output; re-encoding: {final_path}")
            try: os.remove(final_path)
            except FileNotFoundError: pass

        video_kbps = global_video_kbps
        audio_kbps = max(1, int(audio_bps/1000))

        ff = [
            "ffmpeg",
            "-hide_banner","-loglevel","warning","-stats","-y",
            "-ignore_unknown","-ignore_editlist","1",
            "-i", src,
            "-map","0:v:0","-map","0:a?","-map","0:s?",
            "-fps_mode","passthrough",
            "-c:v","libsvtav1","-b:v",f"{video_kbps}k","-g","240","-preset","5",
            "-svtav1-params","scd=1",
            "-c:a","libopus","-b:a",f"{audio_kbps}k",
            "-c:s","copy",
            "-cues_to_front","1","-reserve_index_space","200k",
            "-f","matroska",
            part_path
        ]

        rec.update({"status":"encoding_started","started_at":now_utc_iso(),"output":out_name})
        manifest["items"][key] = rec; save_manifest(manifest, manifest_path)

        run(ff)

        if not is_valid_media(part_path):
            eprint(f"ERROR: Encoded output invalid: {part_path} (will retry next run)")
            continue

        os.replace(part_path, final_path)
        rec.update({"status":"done","finished_at":now_utc_iso()})
        manifest["items"][key] = rec; save_manifest(manifest, manifest_path)
        encoded_count += 1

    eprint(f"=== encode_videos: done ===")
    eprint(f"Videos encoded (this run): {encoded_count} / {len(videos)}")
    eprint(f"Manifest retained: {manifest_path}")

    # Keep manifest indefinitely; just report completion state
    if all_videos_done(manifest, args.output_dir):
        eprint("All videos complete. Leaving manifest in place.")

if __name__ == "__main__":
    main()