#!/usr/bin/env python3
import argparse
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import suppress
from datetime import datetime, timezone
from typing import Any

VERBOSE: bool = False


# ---------- small helpers ----------
def eprint(*a: object, **k: Any) -> None:
    print(*a, **k, file=sys.stderr)


def vlog(*a: object, **k: Any) -> None:
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
    raise AssertionError("unreachable")


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


def calc_udf_blocks(n_bytes: int, block_size: int = 2048) -> int:
    """Return the number of blocks required for the filesystem image."""

    # Allow some slack for filesystem metadata while keeping the image
    # reasonably sized. Provide a floor so empty trees still produce a valid
    # filesystem. The heuristics are conservative to avoid running out of
    # space mid-copy when the metadata grows slightly beyond the data size.
    min_blocks = max((32 * 1024 * 1024) // block_size, 1)  # 32 MiB minimum image
    if n_bytes <= 0:
        return min_blocks

    overhead = max(16 * 1024 * 1024, int(n_bytes * 0.1))
    total = n_bytes + overhead
    blocks = math.ceil(total / block_size)
    return max(blocks, min_blocks)


def run_mkudffs(
    src_dir: str, label: str, out_path: str, n_bytes: int, media_type: str
) -> None:
    block_size = 2048
    blocks = calc_udf_blocks(n_bytes, block_size)
    out_dir = os.path.dirname(os.path.abspath(out_path)) or os.getcwd()
    tmp_path = f"{out_path}.tmp"
    with suppress(FileNotFoundError):
        os.remove(tmp_path)

    success = False
    size_bytes = blocks * block_size
    media_arg = media_type.strip() or "bdr"
    truncate_cmd = ["truncate", "-s", str(size_bytes), tmp_path]
    vlog(f"+ {' '.join(truncate_cmd)}")
    proc = subprocess.run(
        truncate_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    if proc.returncode != 0:
        if proc.stderr:
            eprint(proc.stderr.strip())
        with suppress(FileNotFoundError):
            os.remove(tmp_path)
        raise SystemExit(proc.returncode)
    mkudffs_cmd: list[str] = [
        "mkudffs",
        "--utf8",
        "--new-file",
        f"--label={label}",
        "--blocksize=2048",
        f"--media-type={media_arg}",
        "--udfrev=0x0201",
        tmp_path,
        str(blocks),
    ]
    vlog(f"+ {' '.join(mkudffs_cmd)}")
    try:
        proc = subprocess.run(
            mkudffs_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        if proc.returncode != 0:
            if proc.stderr:
                eprint(proc.stderr.strip())
            raise SystemExit(proc.returncode)

        mount_dir = tempfile.mkdtemp(prefix="mkiso-", dir=out_dir)
        try:
            mount_cmd = ["mount", "-t", "udf", "-o", "loop", tmp_path, mount_dir]
            vlog(f"+ {' '.join(mount_cmd)}")
            mnt = subprocess.run(
                mount_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            if mnt.returncode != 0:
                if mnt.stderr:
                    eprint(mnt.stderr.strip())
                raise SystemExit(mnt.returncode)

            try:
                shutil.copytree(src_dir, mount_dir, dirs_exist_ok=True, symlinks=True)
            except Exception as exc:  # pragma: no cover - defensive error path
                eprint(f"[mkiso] ERROR: failed to populate image: {exc}")
                raise SystemExit(1) from exc
            finally:
                with suppress(AttributeError):
                    os.sync()
        finally:
            umount_cmd = ["umount", mount_dir]
            vlog(f"+ {' '.join(umount_cmd)}")
            umnt = subprocess.run(
                umount_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            if umnt.returncode != 0:
                if umnt.stderr:
                    eprint(umnt.stderr.strip())
                raise SystemExit(umnt.returncode)
            os.rmdir(mount_dir)

        os.replace(tmp_path, out_path)
        success = True
    finally:
        if not success:
            with suppress(FileNotFoundError):
                os.remove(tmp_path)


# ---------- main ----------
def main() -> None:
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
        "--media-type",
        default="bdr",
        help="Media type hint for mkudffs (default: bdr).",
    )
    ap.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose logging."
    )
    args: argparse.Namespace = ap.parse_args()

    global VERBOSE
    VERBOSE = args.verbose

    start = time.time()
    if not os.path.isdir(args.src_dir):
        eprint(f"[mkiso] ERROR: source directory not found: {args.src_dir}")
        sys.exit(2)

    label: str = args.label or utc_ts()

    if args.out_file is not None:
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
    run_mkudffs(args.src_dir, label, out_path, n_bytes, args.media_type)

    # Final summary
    size: int = 0
    try:
        size = os.path.getsize(out_path)
    except OSError:
        pass
    dur = time.time() - start
    eprint(f"{out_path} {fmt_bytes(size)} {dur:.1f}s label={label}")
    print(os.path.basename(out_path))


if __name__ == "__main__":
    main()
