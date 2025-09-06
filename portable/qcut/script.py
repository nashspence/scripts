#!/usr/bin/env python3
# mypy: ignore-errors
import argparse
import json
import math
import os
import random
import re
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone


# ------------------------- logging & misc -------------------------
def eprint(msg: str):  # errors/warnings to stderr
    print(msg, file=sys.stderr)


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(msg: str):  # timestamped progress logs
    eprint(f"[{now_utc_iso()}] [autoedit] {msg}")


VIDEO_EXTS = (".mp4", ".mkv", ".mov", ".m4v", ".MP4", ".MKV", ".MOV", ".M4V")
DEFAULT_FONT = "/usr/share/fonts/TTF/DejaVuSansMono.ttf"  # present in container
# Colons in the format must be escaped for the %{...} macro parser.
DATE_FMT_FOR_OVERLAY = r"%m/%d/%Y %H\:%M\:%S"
FFCONCAT_HEADER = "ffconcat version 1.0\n"
MANIFEST_NAME = ".job.json"


# ------------------------- system/ffmpeg helpers -------------------------
def need(cmd: str):
    r = subprocess.run(["sh", "-lc", f"command -v {cmd} >/dev/null 2>&1"])
    if r.returncode != 0:
        eprint(f"[autoedit] ERROR: required command missing: {cmd}")
        sys.exit(1)


def ffprobe_duration(path: str, timeout_sec: int = 30) -> float:
    t0 = time.time()
    log(f"ffprobe start: {os.path.basename(path)}")
    try:
        r = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "csv=p=0",
                path,
            ],
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired:
        log(f"ffprobe TIMEOUT ({timeout_sec}s): {path}")
        return 0.0

    dur_s = r.stdout.strip()
    log(
        f"ffprobe done ({time.time()-t0:.2f}s): {os.path.basename(path)} -> {dur_s or 'N/A'}"
    )
    try:
        return float(dur_s)
    except Exception:
        return 0.0


def has_audio_stream(path: str, timeout_sec: int = 15) -> bool:
    try:
        r = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=index",
                "-of",
                "csv=p=0",
                path,
            ],
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired:
        log(f"ffprobe (audio check) TIMEOUT ({timeout_sec}s): {path}")
        return False
    return bool(r.stdout.strip())


def walk_video_files(root: str):
    files = []
    for dp, _, fns in os.walk(root):
        for f in fns:
            if f.endswith(VIDEO_EXTS):
                files.append(os.path.join(dp, f))
    return sorted(files)


# ------------------------- epoch-from-filename (Perl port) -------------------------
_PATTERNS = [
    re.compile(
        r"(?<!\d)(\d{4})[._-]?([01]\d)[._-]?([0-3]\d)[ T_-]?([0-2]\d)[.:_-]?([0-5]\d)[.:_-]?([0-5]\d)(?!\d)"
    ),
    re.compile(
        r"(?<!\d)(\d{2})[._-]?([01]\d)[._-]?([0-3]\d)[ T_-]?([0-2]\d)[.:_-]?([0-5]\d)[.:_-]?([0-5]\d)(?!\d)"
    ),
    re.compile(r"(\d{4})[-_]?([01]\d)[-_]?([0-3]\d)T([0-2]\d)([0-5]\d)([0-5]\d)"),
    re.compile(r"(\d{4})-(\d{2})-(\d{2})\s+at\s+([0-2]\d)\.([0-5]\d)\.([0-5]\d)", re.I),
]


def epoch_from_filename(name: str):
    bn = os.path.basename(name)
    for rx in _PATTERNS:
        m = rx.search(bn)
        if not m:
            continue
        Y, M, D, h, mn, s = [int(x) for x in m.groups()]
        if len(m.group(1)) == 2:  # 2-digit year heuristic
            Y = 2000 + Y if Y < 70 else 1900 + Y
        try:
            dt = datetime(Y, M, D, h, mn, s)  # local time
            return int(time.mktime(dt.timetuple()))
        except Exception:
            pass
    return None


def base_epoch_for_file(path: str) -> int:
    e = epoch_from_filename(path)
    if e is not None:
        return e
    try:
        return int(os.stat(path).st_mtime)
    except Exception:
        return int(time.time())


# ------------------------- planning helpers (SECONDS units) -------------------------
def build_len_slots(target_sec: int, min_slot_sec: int, max_slot_sec: int) -> list[int]:
    """Build integer-second slot lengths with the same logic as the zsh version."""
    remain = int(target_sec)
    slots: list[int] = []
    while remain >= min_slot_sec:
        r = random.randint(min_slot_sec, max_slot_sec)
        if r > remain:
            r = remain
        slots.append(r)
        remain -= r
    i = 0
    while remain > 0 and slots:
        slots[i] += 1
        i = (i + 1) % len(slots)
        remain -= 1
    return slots


def _round_half_up(x: float) -> int:
    """AWK printf(\"%.0f\") style rounding for positive numbers."""
    if x <= 0:
        return 0
    return int(math.floor(x + 0.5))


def quotas_like_zsh(
    durations_sec: list[float], slot_count: int, min_seconds: int
) -> list[int]:
    """
    Match the zsh planning:
      q_i = round( (d_i / sum_d) * slot_count )  [round half up]
      if q_i == 0 and floor(d_i) >= MIN_SECONDS: q_i = 1
      while sum(q) != slot_count:
        for i in files:
          if sum<slot_count: q_i += 1
          elif q_i > 1: q_i -= 1
    """
    n = len(durations_sec)
    if n == 0 or slot_count <= 0:
        return [0] * n

    total = sum(max(0.0, d) for d in durations_sec)
    if total <= 0:
        return [0] * n

    q = []
    for d in durations_sec:
        share = (d / total) * slot_count
        q.append(_round_half_up(share))

    # Enforce at least one slot for sufficiently long files
    min_seconds = max(0, int(min_seconds))
    for i, d in enumerate(durations_sec):
        if q[i] == 0 and int(d) >= min_seconds:
            q[i] = 1

    s = sum(q)
    if s == slot_count:
        return q

    # Round-robin correction like the zsh loop
    guard = 0
    while s != slot_count and guard < 100000:
        for i in range(n):
            if s == slot_count:
                break
            if s < slot_count:
                q[i] += 1
                s += 1
            elif q[i] > 1:
                q[i] -= 1
                s -= 1
        guard += 1

    return q


def build_drawtext_pts(fontfile: str, epoch_int: int) -> str:
    # Use strftime expansion with a stable basetime (µs) anchored to the clip's epoch.
    basetime_us = int(epoch_int) * 1_000_000
    return (
        f"drawtext=fontfile={fontfile}"
        f":expansion=strftime:basetime={basetime_us}"
        f":fontcolor=white:fontsize=h/40:box=1:boxcolor=black@1:boxborderw=6"
        f":text='%m/%d/%Y %H\\:%M\\:%S':x=24:y=24"
    )


# ------------------------- manifest helpers -------------------------
def manifest_path(out_dir: str) -> str:
    return os.path.join(out_dir, MANIFEST_NAME)


def load_manifest(out_dir: str) -> dict:
    path = manifest_path(out_dir)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_manifest(out_dir: str, m: dict):
    # Atomic, non-destructive update (never deletes the manifest file outright)
    m["updated"] = now_utc_iso()
    tmp = manifest_path(out_dir) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(m, f, indent=2)
        f.write("\n")
    os.replace(tmp, manifest_path(out_dir))


def new_manifest(src_dir: str, files_with_stats: list[dict], out_dir: str) -> dict:
    total_size = sum(f["size"] for f in files_with_stats)
    return {
        "version": 1,
        "created": now_utc_iso(),
        "updated": now_utc_iso(),
        "sources": {
            "src_dir": os.path.abspath(src_dir),
            "count": len(files_with_stats),
            "total_size": total_size,
            "files": files_with_stats,  # [{path,size,mtime}]
        },
        "plan": {},
        "clips": {},  # index -> {out, src, start, length, epoch, status}
        "final": {"status": "pending", "out_path": None, "finished_at": None},
    }


def current_sources_sig(src_dir: str) -> list[dict]:
    files = walk_video_files(src_dir)
    stats = []
    for p in files:
        try:
            st = os.stat(p)
            stats.append(
                {
                    "path": os.path.abspath(p),
                    "size": st.st_size,
                    "mtime": int(st.st_mtime),
                }
            )
        except FileNotFoundError:
            continue
    return stats


def sources_sig_same(m: dict, src_dir: str) -> bool:
    try:
        cur = current_sources_sig(src_dir)
        prev = m.get("sources", {})
        if os.path.abspath(src_dir) != prev.get("src_dir"):
            return False
        if prev.get("count") != len(cur):
            return False
        if prev.get("total_size") != sum(f["size"] for f in cur):
            return False
        # quick path: same set of (path,size,mtime)
        prev_set = {(f["path"], f["size"], f["mtime"]) for f in prev.get("files", [])}
        cur_set = {(f["path"], f["size"], f["mtime"]) for f in cur}
        return prev_set == cur_set
    except Exception:
        return False


# ------------------------- main -------------------------
def main():
    ap = argparse.ArgumentParser(
        description="Auto-edit from a source directory of videos with timestamp overlays and resumable manifest."
    )
    ap.add_argument(
        "--src-dir",
        default="/in",
        help="Directory containing source video files (default: /in).",
    )
    # Match zsh semantics: TARGET/MIN/MAX are in SECONDS.
    ap.add_argument(
        "--target",
        type=int,
        default=int(os.getenv("TARGET", "300")),  # 5 minutes
        help="Target SECONDS total (default 300 = 5 minutes).",
    )
    ap.add_argument(
        "--min",
        type=int,
        default=int(os.getenv("MIN", "6")),
        help="Minimum clip length in SECONDS (default 6).",
    )
    ap.add_argument(
        "--max",
        type=int,
        default=int(os.getenv("MAX", "9")),
        help="Maximum clip length in SECONDS (default 9).",
    )
    ap.add_argument("--svt-preset", type=int, default=int(os.getenv("SVT_PRESET", "5")))
    ap.add_argument("--svt-crf", type=int, default=int(os.getenv("SVT_CRF", "30")))
    ap.add_argument("--svt-gop", type=int, default=int(os.getenv("SVT_GOP", "240")))
    ap.add_argument("--opus-br", default=os.getenv("OPUS_BR", "128k"))
    ap.add_argument("--tp", default=os.getenv("TP", "-1.5"))
    ap.add_argument("--lufs-clip", default=os.getenv("LUFS_CLIP", "-9"))
    ap.add_argument("--fontfile", default=os.getenv("FONTFILE", DEFAULT_FONT))
    ap.add_argument("--autoedit-dir", default=os.getenv("AUTOEDIT_DIR", "/out"))
    ap.add_argument(
        "--debug-cmds",
        action="store_true",
        help="Print full ffmpeg/ffprobe commands before running.",
    )
    args = ap.parse_args()

    for cmd in ("ffmpeg", "ffprobe"):
        need(cmd)

    if not os.path.isdir(args.src_dir):
        eprint(
            f"[autoedit] ERROR: --src-dir must be an existing directory (got: {args.src_dir})"
        )
        sys.exit(1)

    os.makedirs(args.autoedit_dir, exist_ok=True)
    work_dir = os.path.join(args.autoedit_dir, ".autoedit_work")
    os.makedirs(work_dir, exist_ok=True)
    m = load_manifest(args.autoedit_dir)

    # ------------------------- Early exit if already completed -------------------------
    if m and m.get("final", {}).get("status") == "done":
        outp = m["final"].get("out_path")
        finished_at = m["final"].get("finished_at") or "unknown time"
        if outp and os.path.exists(outp) and ffprobe_duration(outp) > 0:
            log(
                f"Manifest indicates job already completed successfully at {finished_at}. Output: {outp}. Returning."
            )
            print(outp)
            return
        else:
            log(
                "Manifest says 'done' but final output is missing or invalid; proceeding with rebuild."
            )

    # Reset manifest if source set changed or missing (never delete; only overwrite atomically)
    if not m or not sources_sig_same(m, args.src_dir):
        files_stats = current_sources_sig(args.src_dir)
        m = new_manifest(args.src_dir, files_stats, args.autoedit_dir)
        save_manifest(args.autoedit_dir, m)
        log("New manifest created.")

    start_time = time.time()
    log("Start")
    log(
        f"Source dir: {m['sources']['src_dir']}  "
        f"({m['sources']['count']} video files, {m['sources']['total_size']:,} bytes)"
    )
    log(f"Output:    {args.autoedit_dir}")
    log(f"Clips dir: {work_dir}  (kept for resume)")

    # 1) Gather files & durations (videos only)
    files = [f["path"] for f in m["sources"]["files"]]
    if not files:
        eprint("[autoedit] ERROR: no video files found in source directory")
        sys.exit(1)

    log(f"Probing durations for {len(files)} file(s)…")
    durations = [ffprobe_duration(p) for p in files]  # seconds
    if not any(d > 0 for d in durations):
        eprint("[autoedit] ERROR: cannot read durations")
        sys.exit(1)
    combined = sum(durations)  # seconds

    # Build or load the plan
    if not m.get("plan"):
        # Cap TARGET to available total (seconds)
        target_sec = args.target if combined >= args.target else int(combined)

        # Build slot lengths in SECONDS (zsh-compatible)
        len_slots_sec = build_len_slots(target_sec, args.min, args.max)
        if not len_slots_sec:
            # If target < min, make a single short slot exactly equal to target
            len_slots_sec = [target_sec]

        slot_count = len(len_slots_sec)
        if slot_count < len(files):
            log(
                f"WARNING: slot_count ({slot_count}) < number of files ({len(files)}). "
                "Some files may receive 0 quota."
            )

        # Quotas with zsh-equivalent rounding + correction (MIN is in seconds)
        q = quotas_like_zsh(durations, slot_count, args.min)

        base_epochs = [base_epoch_for_file(p) for p in files]

        plan = {
            "target_sec": target_sec,
            "min_sec": args.min,
            "max_sec": args.max,
            "svt_preset": args.svt_preset,
            "svt_crf": args.svt_crf,
            "svt_gop": args.svt_gop,
            "opus_br": args.opus_br,
            "tp": args.tp,
            "lufs_clip": args.lufs_clip,
            "fontfile": args.fontfile,
            "len_slots_sec": len_slots_sec,
            "files": [
                {
                    "path": files[i],
                    "duration": durations[i],
                    "quota": q[i],
                    "base_epoch": base_epochs[i],
                }
                for i in range(len(files))
            ],
        }
        clips = {}
        idx = 1
        random.seed()  # persisted outcomes for resume via manifest
        for i, fi in enumerate(plan["files"]):
            qi = fi["quota"]
            if qi == 0:
                continue
            d = fi["duration"]
            part = d / qi if qi > 0 else 0.0
            for slot in range(1, qi + 1):
                Ls = len_slots_sec[idx - 1] if (idx - 1) < slot_count else args.min
                L = float(Ls)  # seconds
                ps = (slot - 1) * part
                mo = max(0.0, part - L)
                off = random.random() * mo if mo > 0 else 0.0
                rs = ps + off
                hi = max(0.0, d - L)
                if rs > hi:
                    rs = hi
                epoch_int = int(fi["base_epoch"] + int(rs))
                out_clip = os.path.join(work_dir, f"clip{idx:03d}.mkv")
                clips[str(idx)] = {
                    "index": idx,
                    "src_idx": i,
                    "src": fi["path"],
                    "start": float(f"{rs:.6f}"),
                    "length": float(f"{L:.6f}"),
                    "epoch": epoch_int,
                    "out": out_clip,
                    "status": "pending",
                }
                idx += 1
        m["plan"] = plan
        m["clips"] = clips
        save_manifest(args.autoedit_dir, m)

        # Plan visibility logs
        log(
            f"Plan: target={target_sec} s (~{target_sec/60:.1f} min), "
            f"slots={len_slots_sec} (count={len(len_slots_sec)}), files={len(files)}"
        )
        for i, fi in enumerate(plan["files"]):
            log(
                f"  file[{i}] quota={fi['quota']} duration={fi['duration']:.1f}s name={os.path.basename(fi['path'])}"
            )

        log(
            f"Plan created: {len(m['clips'])} clips, "
            f"target {plan['target_sec']} s (~{plan['target_sec']/60:.1f} min)"
        )
    else:
        log(f"Plan loaded: {len(m['clips'])} clips")

    # 2) Encode pending clips
    done = sum(
        1
        for c in m["clips"].values()
        if c["status"] == "done"
        and os.path.exists(c["out"])
        and ffprobe_duration(c["out"]) > 0
    )
    total = len(m["clips"])
    log(f"Encoding clips: {done}/{total} already done")

    for k in sorted(m["clips"], key=lambda x: int(x)):
        clip = m["clips"][k]
        out_clip = clip["out"]
        if (
            clip["status"] == "done"
            and os.path.exists(out_clip)
            and ffprobe_duration(out_clip) > 0
        ):
            continue

        src = clip["src"]
        start = clip["start"]
        L = clip["length"]
        epoch_int = int(clip["epoch"])

        draw = build_drawtext_pts(m["plan"]["fontfile"], epoch_int)

        has_a = has_audio_stream(src)
        if has_a:
            afilt = f"highpass=f=120,loudnorm=I={m['plan']['lufs_clip']}:TP={m['plan']['tp']}:LRA=11:linear=true,aresample=async=1:first_pts=0"
            fcomplex = f"[0:v]{draw}[v];[0:a]{afilt}[a]"
            map_seq = ["-map", "[v]", "-map", "[a]", "-map", "0:s?"]
        else:
            # synthesize stereo silent audio for concat uniformity
            fcomplex = f"[0:v]{draw}[v];anullsrc=r=48000:cl=stereo,atrim=duration={L:.6f},aresample=async=1:first_pts=0[a]"
            map_seq = ["-map", "[v]", "-map", "[a]", "-map", "0:s?"]

        os.makedirs(os.path.dirname(out_clip), exist_ok=True)
        cmd = (
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-stats",
                "-y",
                "-ss",
                f"{start:.6f}",
                "-t",
                f"{L:.6f}",
                "-i",
                src,
                "-fps_mode",
                "passthrough",
                "-filter_complex",
                fcomplex,
            ]
            + map_seq
            + [
                "-c:v",
                "libsvtav1",
                "-preset",
                str(m["plan"]["svt_preset"]),
                "-crf",
                str(m["plan"]["svt_crf"]),
                "-g",
                str(m["plan"]["svt_gop"]),
                "-svtav1-params",
                f"keyint={m['plan']['svt_gop']}:irefresh-type=2:scd=1",
                "-c:a",
                "libopus",
                "-b:a",
                m["plan"]["opus_br"],
                "-c:s",
                "copy",
                "-map_metadata",
                "0",
                "-map_chapters",
                "0",
                "-cues_to_front",
                "1",
                "-reserve_index_space",
                "200k",
                out_clip,
            ]
        )

        log(
            f"clip {int(k):03d} START ← {os.path.basename(src)} @ {start:.2f}s for {L:.0f}s → {os.path.basename(out_clip)}"
        )
        if args.debug_cmds:
            log("CMD: " + " ".join(shlex.quote(x) for x in cmd))
        t0 = time.time()
        r = subprocess.run(cmd)
        size_now = os.path.getsize(out_clip) if os.path.exists(out_clip) else 0
        log(
            f"clip {int(k):03d} DONE rc={r.returncode} in {time.time()-t0:.1f}s size={size_now} bytes"
        )

        if r.returncode != 0:
            eprint(f"[autoedit] ERROR: encoding clip {k}")
            save_manifest(args.autoedit_dir, m)
            sys.exit(1)

        if ffprobe_duration(out_clip) <= 0:
            eprint(f"[autoedit] ERROR: invalid clip {k} output")
            save_manifest(args.autoedit_dir, m)
            sys.exit(1)

        clip["status"] = "done"
        m["clips"][k] = clip
        save_manifest(args.autoedit_dir, m)

    # 3) Final concat (only if not already done or file missing)
    files_span = m["plan"]["files"]
    start_epoch = min(f["base_epoch"] for f in files_span)
    last_file = max(files_span, key=lambda f: f["base_epoch"])
    end_epoch = int(last_file["base_epoch"] + math.ceil(last_file["duration"]))
    start_dt = datetime.fromtimestamp(start_epoch)
    end_dt = datetime.fromtimestamp(end_epoch)
    span_name = (
        f"{start_dt.strftime('%Y-%m-%dT%H-%M-%S')}--"
        f"{end_dt.strftime('%Y-%m-%dT%H-%M-%S')}"
    )
    out_path = os.path.join(args.autoedit_dir, f"{span_name} auto-edit.mkv")
    m["final"]["out_path"] = out_path
    save_manifest(args.autoedit_dir, m)

    all_done = all(
        c["status"] == "done" and os.path.exists(c["out"]) for c in m["clips"].values()
    )
    if not all_done:
        eprint("[autoedit] ERROR: not all clips finished; aborting before concat")
        sys.exit(1)

    concat_path = os.path.join(work_dir, "concat.txt")
    with open(concat_path, "w", encoding="utf-8") as f:
        f.write(FFCONCAT_HEADER)
        for k in sorted(m["clips"], key=lambda x: int(x)):
            c = m["clips"][k]
            d_clip = ffprobe_duration(c["out"]) or c["length"]
            f.write(f"file '{c['out']}'\n")
            f.write(f"duration {d_clip:.6f}\n")

    cmd_final = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-stats",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        concat_path,
        "-map",
        "0:v",
        "-map",
        "0:a?",
        "-map",
        "0:s?",
        "-c",
        "copy",
        "-cues_to_front",
        "1",
        "-reserve_index_space",
        "200k",
        out_path,
    ]
    log(f"Concat list: {concat_path} ({len(m['clips'])} 'file' entries)")
    if args.debug_cmds:
        log("CMD: " + " ".join(shlex.quote(x) for x in cmd_final))
    t0 = time.time()
    r = subprocess.run(cmd_final)
    log(f"Final concat rc={r.returncode} in {time.time()-t0:.1f}s → {out_path}")
    if r.returncode != 0:
        eprint("[autoedit] ERROR: final concat failed")
        save_manifest(args.autoedit_dir, m)
        sys.exit(1)

    m["final"]["status"] = "done"
    m["final"]["finished_at"] = now_utc_iso()
    save_manifest(args.autoedit_dir, m)

    # No deletions (inputs or clips). Work dir kept for resume/inspection.
    dur = time.time() - start_time
    size = os.path.getsize(out_path) if os.path.exists(out_path) else 0
    log(f"Success: wrote {size/1024/1024/1024:.2f} GB in {dur:.1f}s")
    print(out_path)


if __name__ == "__main__":
    main()
