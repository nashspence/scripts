#!/usr/bin/env python3
# mypy: ignore-errors
import argparse
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

VERBOSE = False


# ---------- small helpers ----------
def eprint(*a, **k):
    print(*a, **k, file=sys.stderr)


def vlog(*a, **k):
    if VERBOSE:
        eprint(*a, **k)


def utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def fmt_bytes(n: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    f = float(n)
    for u in units:
        if f < 1024.0 or u == units[-1]:
            return f"{f:.1f} {u}" if u != "B" else f"{int(f)} {u}"
        f /= 1024.0


def count_files_bytes(root: str) -> tuple[int, int]:
    n_files, n_bytes = 0, 0
    for dp, _, fns in os.walk(root):
        for f in fns:
            p = os.path.join(dp, f)
            try:
                st = os.stat(p)
                n_files += 1
                n_bytes += st.st_size
            except FileNotFoundError:
                continue
    return n_files, n_bytes


def resolve_out_path(out_dir: str, label: str) -> str:
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{label}.iso")
    if os.path.exists(path):
        i = 1
        while True:
            cand = os.path.join(out_dir, f"{label}_{i}.iso")
            if not os.path.exists(cand):
                return cand
            i += 1
    return path


def resolve_out_file(out_dir: str, out_file: str) -> str:
    """
    Accepts a filename or full/relative path. Ensures .iso extension and
    creates the parent directory. If a bare filename is provided, it is
    written under out_dir.
    """
    out_file = os.path.expanduser(out_file)
    # If user supplied a path-like (contains a separator) or absolute path
    if os.path.isabs(out_file) or os.sep in out_file:
        base_dir = os.path.dirname(out_file)
        base_name = os.path.basename(out_file)
        if not base_name.lower().endswith(".iso"):
            base_name += ".iso"
        os.makedirs(base_dir or out_dir, exist_ok=True)
        return os.path.join(base_dir or out_dir, base_name)
    # Bare filename → place under out_dir
    if not out_file.lower().endswith(".iso"):
        out_file += ".iso"
    os.makedirs(out_dir, exist_ok=True)
    return os.path.join(out_dir, out_file)


def run_genisoimage(src_dir: str, label: str, out_path: str):
    cmd = ["genisoimage", "-quiet", "-o", out_path, "-V", label, "-udf", src_dir]
    vlog(f"+ {' '.join(cmd)}")
    proc = subprocess.run(
        cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True
    )
    if proc.returncode != 0:
        if proc.stderr:
            eprint(proc.stderr.strip())
        raise SystemExit(proc.returncode)


# ---------- main ----------
def main():
    ap = argparse.ArgumentParser(description=("Minimal ISO builder (dir → .iso)."))
    ap.add_argument(
        "--src-dir", default="/in", help="Directory to package (default: /in)."
    )
    ap.add_argument(
        "--out-dir",
        default="/out",
        help="Directory to write <label>.iso into (default: /out).",
    )
    ap.add_argument(
        "--label", default=None, help="Volume label; default = UTC ts %Y%m%dT%H%M%SZ."
    )
    ap.add_argument(
        "--out-file",
        default=None,
        help="Filename or path for the output .iso. "
        "If a bare filename is given, it is placed in --out-dir. "
        "Overrides auto-naming.",
    )
    ap.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose logging."
    )
    args = ap.parse_args()

    global VERBOSE
    VERBOSE = args.verbose

    start = time.time()
    if not os.path.isdir(args.src_dir):
        eprint(f"[mkiso] ERROR: source directory not found: {args.src_dir}")
        sys.exit(2)

    label = args.label or utc_ts()

    if args.out_file:
        out_path = resolve_out_file(args.out_dir, args.out_file)
        if os.path.exists(out_path):
            eprint(f"[mkiso] ERROR: output file already exists: {out_path}")
            sys.exit(3)
    else:
        out_path = resolve_out_path(args.out_dir, label)

    n_files, n_bytes = count_files_bytes(args.src_dir)
    vlog("start")
    vlog(f"src={args.src_dir} files={n_files} bytes={fmt_bytes(n_bytes)}")
    vlog(f"label={label}")
    vlog(f"out={out_path}")

    # Build ISO directly from src_dir
    run_genisoimage(args.src_dir, label, out_path)

    # Final summary
    size = 0
    try:
        size = os.path.getsize(out_path)
    except OSError:
        pass
    dur = time.time() - start
    eprint(f"{out_path} {fmt_bytes(size)} {dur:.1f}s label={label}")


if __name__ == "__main__":
    main()
