#!/usr/bin/env python3
import argparse
import os
import sys
import time
from contextlib import suppress
from datetime import datetime, timezone
from itertools import count
from pathlib import Path
from string import ascii_uppercase, digits
from typing import Any, cast

import pycdlib
from pycdlib.pycdlibexception import PyCdlibException

PyCdlib: type[Any] = cast(Any, pycdlib).PyCdlib

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


def sanitize_volume_ident(label: str) -> str:
    allowed = set(ascii_uppercase + digits + "_")
    sanitized = [ch if ch in allowed else "_" for ch in label.upper()]
    result = "".join(sanitized)[:32]
    return result or "MKISO"


def build_udf_image(
    src_dir: str,
    label: str,
    out_path: str,
    n_bytes: int,
    media_type: str,
    udf_revision: str = "2.01",
) -> None:
    del n_bytes  # Size is unused with pycdlib but retained for compatibility.
    media_hint = media_type.strip() or "bdr"
    vlog(f"[mkiso] building UDF {udf_revision} image via pycdlib (media={media_hint})")

    base = Path(src_dir)
    tmp_path = f"{out_path}.tmp"
    with suppress(FileNotFoundError):
        os.remove(tmp_path)

    iso = PyCdlib()
    success = False
    alias_counter = count(1)

    try:
        vol_ident = sanitize_volume_ident(label)
        if vol_ident != label:
            vlog(f"[mkiso] sanitized volume identifier to '{vol_ident}'")
        iso.new(vol_ident=vol_ident, udf=udf_revision)

        directories = sorted(
            (p for p in base.rglob("*") if p.is_dir()),
            key=lambda p: p.relative_to(base).as_posix(),
        )
        for directory in directories:
            rel = directory.relative_to(base)
            if not rel.parts:
                continue
            udf_path = "/" + rel.as_posix()
            iso.add_directory(udf_path=udf_path)

        entries = sorted(
            (p for p in base.rglob("*") if p.is_file() or p.is_symlink()),
            key=lambda p: p.relative_to(base).as_posix(),
        )
        for entry in entries:
            rel_posix = entry.relative_to(base).as_posix()
            udf_path = "/" + rel_posix
            if entry.is_symlink():
                target = os.readlink(entry)
                iso.add_symlink(udf_symlink_path=udf_path, udf_target=target)
                continue

            iso_alias = f"/F{next(alias_counter):06d}.;1"
            with entry.open("rb") as fp:
                iso.add_fp(fp, entry.stat().st_size, iso_alias, udf_path=udf_path)

        iso.write(tmp_path)
        success = True
    except PyCdlibException as exc:
        eprint(f"[mkiso] ERROR: failed to build UDF image: {exc}")
        raise SystemExit(1) from exc
    finally:
        with suppress(PyCdlibException):
            iso.close()
        if not success:
            with suppress(FileNotFoundError):
                os.remove(tmp_path)

    os.replace(tmp_path, out_path)


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
        help="Media type hint (retained for compatibility; default: bdr).",
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
    build_udf_image(args.src_dir, label, out_path, n_bytes, args.media_type)

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
