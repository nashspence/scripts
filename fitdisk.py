#!/usr/bin/env python3

import argparse
import logging
import os
import shutil
import sys
from typing import Iterable, List, Optional, Sequence, Tuple

MEDIA_PRESETS: dict[str, dict[str, float | str]] = {
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

DEFAULT_TARGET_SIZE = "23.30G"
DEFAULT_MANIFEST_NAME = ".job.json"


def _normalize_media(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    key = value.strip().lower().replace("_", "").replace(" ", "")
    key = key.replace("gb", "").replace("gib", "").replace("-", "")
    if key in MEDIA_PRESETS:
        return key
    return _MEDIA_ALIASES.get(key)


def parse_size(text: str) -> int:
    cleaned = text.strip().lower().replace("ib", "")
    multiplier = 1
    if cleaned.endswith("k"):
        multiplier = 1024
        cleaned = cleaned[:-1]
    elif cleaned.endswith("m"):
        multiplier = 1024**2
        cleaned = cleaned[:-1]
    elif cleaned.endswith("g"):
        multiplier = 1024**3
        cleaned = cleaned[:-1]
    elif cleaned.endswith("t"):
        multiplier = 1024**4
        cleaned = cleaned[:-1]
    return int(float(cleaned) * multiplier)


def _iter_input_files(root: str) -> Iterable[Tuple[str, int]]:
    for dirpath, _dirs, filenames in os.walk(root):
        for name in sorted(filenames):
            path = os.path.join(dirpath, name)
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            yield path, size


def _unique_name(existing: set[str], name: str) -> str:
    if name not in existing:
        existing.add(name)
        return name
    stem, ext = os.path.splitext(name)
    index = 1
    while True:
        candidate = f"{stem}_{index}{ext}"
        if candidate not in existing:
            existing.add(candidate)
            return candidate
        index += 1


def _plan_groups(
    files: Sequence[Tuple[str, int]], target_bytes: int
) -> List[List[Tuple[str, int]]]:
    groups: List[List[Tuple[str, int]]] = []
    current: List[Tuple[str, int]] = []
    current_size = 0
    for item in files:
        path, size = item
        if current and current_size + size > target_bytes:
            groups.append(current)
            current = []
            current_size = 0
        current.append(item)
        current_size += size
    if current:
        groups.append(current)
    return groups


def bundle_directories(
    input_dir: str,
    output_dir: str,
    target_bytes: int,
    manifest_name: str = DEFAULT_MANIFEST_NAME,
    move: bool = False,
) -> List[str]:
    records: List[Tuple[str, int]] = []
    manifest_norm = os.path.normpath(manifest_name)
    input_dir = os.path.abspath(input_dir)

    for path, size in _iter_input_files(input_dir):
        rel = os.path.relpath(path, input_dir)
        if os.path.normpath(rel) == manifest_norm:
            continue
        records.append((path, size))

    if not records:
        return []

    records.sort(key=lambda item: os.path.relpath(item[0], input_dir))

    groups = _plan_groups(records, target_bytes)
    if not groups:
        return []

    tmp_base = os.path.join(output_dir, ".fitdisk_tmp")
    if os.path.exists(tmp_base):
        shutil.rmtree(tmp_base)
    os.makedirs(tmp_base, exist_ok=True)

    used_names: set[str] = set()
    created: List[str] = []

    for idx, group in enumerate(groups, start=1):
        subdir_name = f"{idx:02d}"
        subdir_tmp = os.path.join(tmp_base, subdir_name)
        os.makedirs(subdir_tmp, exist_ok=True)
        for src, _ in group:
            base = os.path.basename(src)
            dest_name = _unique_name(used_names, base)
            dest_path = os.path.join(subdir_tmp, dest_name)
            if move:
                shutil.move(src, dest_path)
            else:
                shutil.copy2(src, dest_path)
        created.append(subdir_name)

    for name in created:
        dest_dir = os.path.join(output_dir, name)
        if os.path.exists(dest_dir):
            shutil.rmtree(dest_dir)
        shutil.move(os.path.join(tmp_base, name), dest_dir)

    shutil.rmtree(tmp_base, ignore_errors=True)
    return created


def main(argv: Optional[Sequence[str]] = None) -> None:
    ap = argparse.ArgumentParser(
        description="Group files into media-sized directories."
    )
    ap.add_argument(
        "--input-dir", default="/in", help="Directory containing files to group."
    )
    ap.add_argument(
        "--output-dir", default="/out", help="Destination directory for bundles."
    )
    ap.add_argument(
        "--media",
        help="Media preset (cdr700, dvd5, dvd9, dvd10, dvd18, bdr25, bdr50, bdr100, bdr128).",
    )
    ap.add_argument(
        "--target-size",
        default=None,
        help="Explicit target size (e.g., 23.30G). Overrides --media.",
    )
    ap.add_argument(
        "--manifest-name",
        default=DEFAULT_MANIFEST_NAME,
        help="Manifest filename to ignore when scanning the input directory.",
    )
    ap.add_argument(
        "--move",
        action="store_true",
        help="Move files instead of copying them to the bundles.",
    )
    ap.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase logging verbosity.",
    )
    args = ap.parse_args(argv)

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
            ", ".join(sorted(MEDIA_PRESETS)),
        )
        sys.exit(2)

    preset = MEDIA_PRESETS.get(canon_media) if canon_media else None
    target_size = (
        args.target_size
        if args.target_size is not None
        else (preset["target_size"] if preset else DEFAULT_TARGET_SIZE)
    )
    target_bytes = parse_size(str(target_size))

    os.makedirs(args.output_dir, exist_ok=True)

    created = bundle_directories(
        args.input_dir,
        args.output_dir,
        target_bytes,
        manifest_name=args.manifest_name,
        move=args.move,
    )

    if not created:
        logging.warning("no files processed")
        return

    logging.info("created %d bundle%s", len(created), "" if len(created) == 1 else "s")


if __name__ == "__main__":
    main()
