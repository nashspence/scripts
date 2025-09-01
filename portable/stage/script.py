#!/usr/bin/env python3
# mypy: ignore-errors
import argparse
import hashlib
import json
import os
import pathlib
import shutil
import sys
import time
from datetime import datetime, timezone
from typing import List, Optional, Tuple

DEFAULT_MANIFEST = ".job.json"
HASH_BUF = 8 * 1024 * 1024  # 8MB


# ---------- tiny utils ----------
def eprint(*a, **k):
    print(*a, **k, file=sys.stderr)


def log_created(path: str):
    eprint(f"created {path}")


def log_deleted(path: str):
    eprint(f"deleted {path}")


def warn(msg: str):
    eprint(f"warn: {msg}")


def error(msg: str):
    eprint(f"error: {msg}")


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_paths_from(fpath: str) -> List[str]:
    fh = sys.stdin if fpath == "-" else open(fpath, "r", encoding="utf-8")
    with fh:
        return [ln.strip() for ln in fh if ln.strip()]


def load_manifest(path: str) -> dict:
    if not os.path.exists(path):
        return {"version": 1, "updated": now_utc_iso(), "items": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            m = json.load(f)
            if "items" not in m:
                m["items"] = {}
            return m
    except Exception:
        return {"version": 1, "updated": now_utc_iso(), "items": {}}


def save_manifest(manifest: dict, path: str):
    manifest["updated"] = now_utc_iso()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def src_key(src_abs: str, st: os.stat_result) -> str:
    return f"{src_abs}|{st.st_size}|{int(st.st_mtime)}"


# ---------- integrity + durability ----------
def file_hash(path: str, algo: str = "sha256") -> str:
    h = hashlib.new(algo)
    with open(path, "rb") as f:
        while True:
            b = f.read(HASH_BUF)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def verify_copy_srcsize(
    src_size: int, dst: str, use_hash: bool, algo: str, src_path_for_hash: Optional[str]
) -> bool:
    try:
        ds = os.stat(dst)
        if src_size != ds.st_size:
            return False
        if use_hash and src_path_for_hash:
            return file_hash(src_path_for_hash, algo) == file_hash(dst, algo)
        return True
    except FileNotFoundError:
        return False


def fsync_path(path: str):
    try:
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except Exception:
        pass
    try:
        dfd = os.open(os.path.dirname(path) or ".", os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except Exception:
        pass


def copy_atomic_infinite_retry(src: str, dst: str, use_hash: bool, algo: str):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    attempt = 0
    while True:
        attempt += 1
        tmp = dst + ".part"
        try:
            with open(src, "rb") as fsrc, open(tmp, "wb") as fdst:
                shutil.copyfileobj(fsrc, fdst, HASH_BUF)
                fdst.flush()
                os.fsync(fdst.fileno())
            try:
                shutil.copystat(src, tmp, follow_symlinks=True)
            except Exception:
                pass
            os.replace(tmp, dst)
            fsync_path(dst)
            if verify_copy_srcsize(os.stat(src).st_size, dst, use_hash, algo, src):
                return
            warn(f"verification failed; retrying {src} -> {dst}")
        except Exception as ex:
            warn(f"copy error for {src} -> {dst}: {ex}; retrying")
        finally:
            try:
                os.remove(tmp)
            except Exception:
                pass
        time.sleep(min(60, 2 ** min(10, attempt)))


def delete_with_retry(path: str):
    attempt = 0
    while True:
        attempt += 1
        try:
            os.remove(path)
            log_deleted(path)
            return
        except FileNotFoundError:
            return
        except Exception as ex:
            warn(f"delete failed (attempt {attempt}) for {path}: {ex}")
            time.sleep(min(60, 2 ** min(10, attempt)))


# ---------- completion helpers ----------
def manifest_indicates_completed(manifest: dict) -> bool:
    """
    True if manifest says the job is complete:
      - top-level `complete` flag, OR
      - all items are 'done' and their dst files exist with matching sizes.
    """
    if manifest.get("complete") is True:
        return True
    items = manifest.get("items", {})
    if not items:
        return False
    for rec in items.values():
        if rec.get("status") != "done":
            return False
    for rec in items.values():
        dst = rec.get("dst")
        size = rec.get("size")
        if not dst:
            return False
        try:
            st = os.stat(dst)
            if size is not None and st.st_size != size:
                return False
        except FileNotFoundError:
            return False
    return True


# ---------- planning ----------
def gather_roots(cli_inputs: List[str]) -> List[str]:
    roots = []
    for p in cli_inputs:
        if not p:
            continue
        ap = os.path.abspath(p)
        if os.path.exists(ap):
            roots.append(ap)
    return roots


def walk_root(root: str) -> List[str]:
    if os.path.isfile(root):
        return [root]
    files = []
    for r, _, fn in os.walk(root):
        for f in fn:
            fp = os.path.join(r, f)
            if os.path.isfile(fp):
                files.append(fp)
    return files


def unique_with_suffix(dest_dir: str, rel_path: str, used: set) -> str:
    base_dir = os.path.dirname(rel_path)
    name = os.path.basename(rel_path)
    stem, ext = os.path.splitext(name)
    candidate = rel_path
    k = 2
    while candidate in used or os.path.exists(os.path.join(dest_dir, candidate)):
        candidate = (
            os.path.join(base_dir, f"{stem}_{k}{ext}")
            if base_dir
            else f"{stem}_{k}{ext}"
        )
        k += 1
    used.add(candidate)
    return candidate


def plan_dest_for_file(src: str, root: str) -> str:
    """
    Mirror-by-default, excluding the root folder name:
      - If root is a directory: dest = relpath(src, root)
      - If root is a file:      dest = basename(src)
    """
    if os.path.isdir(root):
        return os.path.relpath(src, root)
    else:
        return os.path.basename(src)


# ---------- main ----------
def main():
    ap = argparse.ArgumentParser(
        description="Generic, durable file staging: mirrors subdirectories by default (EXCLUDES root). "
        "Atomic writes, infinite retries, auto-resume, and a retained manifest."
    )
    # Inputs
    ap.add_argument(
        "--input",
        action="append",
        default=["/in"],
        help="File or directory (repeatable).",
    )
    ap.add_argument("--paths-from", help="Newline-delimited paths, or '-' for stdin.")
    ap.add_argument(
        "--pattern", default=None, help="Optional glob to filter (e.g., '*.pdf')."
    )

    # Destination + manifest
    ap.add_argument("--dest-dir", default="/out", help="Destination staging directory.")
    ap.add_argument(
        "--manifest-name",
        default=DEFAULT_MANIFEST,
        help="Manifest filename under dest dir.",
    )

    # Behavior
    ap.add_argument(
        "--keep-sources",
        action="store_true",
        help="Do NOT delete sources after verified copy.",
    )
    ap.add_argument(
        "--hash", default="sha256", help="Hash algorithm (sha256, sha1, blake2b, ...)."
    )
    ap.add_argument(
        "--skip-hash",
        action="store_true",
        help="Skip content hashing. Size-only verification (faster, less strict).",
    )
    ap.add_argument(
        "--dry-run", action="store_true", help="List planned actions; make no changes."
    )

    args = ap.parse_args()

    os.makedirs(args.dest_dir, exist_ok=True)
    manifest_path = os.path.join(args.dest_dir, args.manifest_name)
    manifest = load_manifest(manifest_path)

    # ----- EARLY EXIT if manifest already indicates successful completion -----
    if manifest_indicates_completed(manifest):
        warn("manifest indicates job already complete; nothing to do")
        return

    roots = []
    if args.paths_from:
        roots += read_paths_from(args.paths_from)
    roots += args.input or []
    roots = gather_roots(roots)

    # Build file list per-root (and remember each file's root)
    file_entries: List[Tuple[str, str]] = []
    for root in roots:
        for f in walk_root(root):
            apath = os.path.abspath(f)
            if os.path.abspath(apath).startswith(
                os.path.abspath(args.dest_dir) + os.sep
            ):
                continue
            if args.pattern and not pathlib.PurePath(apath).match(args.pattern):
                continue
            file_entries.append((apath, os.path.abspath(root)))

    if not file_entries:
        error("no input files found")
        sys.exit(1)

    # Plan destinations. If manifest already has a recorded dst for this (src_key), reuse it exactly.
    used_relpaths = set()
    planned: List[Tuple[str, str, str, os.stat_result]] = []  # (src, dst_abs, key, st)
    for src, root in file_entries:
        st = os.stat(src)
        key = src_key(src, st)

        prev = manifest["items"].get(key)
        if (
            prev
            and "dst" in prev
            and prev["dst"].startswith(os.path.abspath(args.dest_dir) + os.sep)
        ):
            rel_prev = os.path.relpath(prev["dst"], args.dest_dir)
            used_relpaths.add(rel_prev)  # reserve exactly
            dst_abs = prev["dst"]
            planned.append((src, dst_abs, key, st))
            continue

        rel = plan_dest_for_file(src, root).replace("\\", "/")
        rel_unique = unique_with_suffix(args.dest_dir, rel, used_relpaths)
        dst_abs = os.path.join(args.dest_dir, rel_unique)
        planned.append((src, dst_abs, key, st))

    if args.dry_run:
        for src, dst, _, _ in planned:
            print(f"[DRY RUN] {src} -> {dst}")
        return

    copied = 0
    for src, dst, key, st in planned:
        rec = manifest["items"].get(key, {"src": src, "dst": dst, "status": "pending"})
        rec.update(
            {"src": src, "dst": dst, "size": st.st_size, "mtime": int(st.st_mtime)}
        )
        manifest["items"][key] = rec
        save_manifest(manifest, manifest_path)

        # Already good?
        if os.path.exists(dst) and verify_copy_srcsize(
            rec["size"],
            dst,
            use_hash=not args.skip_hash,
            algo=args.hash,
            src_path_for_hash=src,
        ):
            if rec.get("status") != "done":
                rec.update({"status": "done", "finished_at": now_utc_iso()})
                manifest["items"][key] = rec
                save_manifest(manifest, manifest_path)
            if not args.keep_sources:
                delete_with_retry(src)
            continue

        # Copy with infinite retries + verify
        copy_atomic_infinite_retry(
            src, dst, use_hash=not args.skip_hash, algo=args.hash
        )
        if not verify_copy_srcsize(
            rec["size"],
            dst,
            use_hash=not args.skip_hash,
            algo=args.hash,
            src_path_for_hash=src,
        ):
            error(f"could not verify copy for {src} -> {dst}; will retry on next run")
            rec.update({"status": "pending"})
            manifest["items"][key] = rec
            save_manifest(manifest, manifest_path)
            continue

        rec.update({"status": "done", "finished_at": now_utc_iso()})
        manifest["items"][key] = rec
        save_manifest(manifest, manifest_path)
        copied += 1
        log_created(dst)

        if not args.keep_sources:
            delete_with_retry(src)

    # ----- completion check: mark manifest complete if ALL planned items are done and present -----
    success = True
    for _src, _dst, key, _st in planned:
        rec = manifest["items"].get(key)
        if not rec or rec.get("status") != "done":
            success = False
            break
        try:
            ds = os.stat(rec["dst"])
            if ds.st_size != rec.get("size", ds.st_size):
                success = False
                break
        except FileNotFoundError:
            success = False
            break

    if success:
        manifest["complete"] = True
        manifest["completed_at"] = now_utc_iso()
        save_manifest(manifest, manifest_path)
    else:
        warn(f"manifest retained for auto-resume next run: {manifest_path}")


if __name__ == "__main__":
    main()
