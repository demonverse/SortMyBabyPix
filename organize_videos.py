"""
Consolidates videos from one or more drives into one destination, organized
as Videos/YYYY/, using the video's creation-date metadata where available,
falling back to a date embedded in the filename, then the file's modified
date, and skipping exact duplicate files.

Requires: pip install hachoir
"""
import hashlib
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

try:
    from hachoir.parser import createParser
    from hachoir.metadata import extractMetadata
except ImportError:
    print("This script needs hachoir. Install it with:  pip install hachoir")
    sys.exit(1)

VIDEO_EXTENSIONS = {
    ".mp4", ".mov", ".avi", ".m4v", ".3gp", ".3g2",
    ".mkv", ".m2ts", ".mts", ".wmv", ".flv", ".webm",
}
SKIP_DIR_NAMES = {"system volume information", "$recycle.bin"}
INDEX_FILENAME = ".video_sync_index.json"
HASH_CHUNK_SIZE = 1024 * 1024

UNSAFE_DEST_DIRS = {
    r"c:\windows",
    r"c:\program files",
    r"c:\program files (x86)",
}

FILENAME_DATE_PATTERNS = [
    re.compile(r"(\d{4})(\d{2})(\d{2})[-_](\d{2})(\d{2})(\d{2})"),  # YYYYMMDD_HHMMSS
    re.compile(r"(\d{4})(\d{2})(\d{2})"),  # YYYYMMDD (date only)
]
EPOCH_MS_PATTERN = re.compile(r"\b(1[5-9]\d{11})\b")  # 13-digit ms timestamp


def ask_yes_no(prompt):
    while True:
        answer = input(f"{prompt} (y/n): ").strip().lower()
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print("Please answer y or n.")


def ask_path(prompt, must_exist=True, must_be_absolute=False):
    while True:
        raw = input(f"{prompt}: ").strip().strip('"')
        if not raw:
            print("  Please type a path (can't be blank).")
            continue
        path = Path(raw)
        if must_be_absolute and not path.is_absolute():
            print(f"  Please enter a full path starting with a drive letter, e.g. D:\\Photos (got '{raw}').")
            continue
        if must_exist and not path.exists():
            print(f"  '{path}' doesn't exist or isn't accessible. Try again.")
            continue
        return path


def is_unsafe_destination(path):
    resolved = str(path.resolve()).lower()
    if len(resolved) <= 3:  # a bare drive root like "C:\"
        return True
    return any(resolved == d or resolved.startswith(d + "\\") for d in UNSAFE_DEST_DIRS)


def gather_sources(destination):
    sources = []
    print("\nFirst drive/folder to scan:")
    sources.append(ask_path("  Path (e.g. E:\\ or E:\\DCIM)"))

    while ask_yes_no("\nAdd another drive to scan?"):
        sources.append(ask_path("  Path"))

    dest_drive_root = Path(destination.resolve().anchor)
    if ask_yes_no(
        f"\nAlso scan the destination drive itself ({dest_drive_root}) for "
        f"existing loose videos to fold into the organized year folders?"
    ):
        sources.append(dest_drive_root)

    return sources


def get_metadata_date(path):
    try:
        parser = createParser(str(path))
        if not parser:
            return None
        with parser:
            metadata = extractMetadata(parser)
        if metadata and metadata.has("creation_date"):
            value = metadata.get("creation_date")
            if isinstance(value, datetime) and value.year > 1990:
                return value
    except Exception:
        pass
    return None


def get_filename_date(name):
    for pattern in FILENAME_DATE_PATTERNS:
        match = pattern.search(name)
        if not match:
            continue
        groups = [int(g) for g in match.groups()]
        try:
            if len(groups) == 6:
                candidate = datetime(*groups[:3], groups[3], groups[4], groups[5])
            else:
                candidate = datetime(*groups[:3])
        except ValueError:
            continue
        if 1990 < candidate.year <= datetime.now().year + 1:
            return candidate

    match = EPOCH_MS_PATTERN.search(name)
    if match:
        try:
            candidate = datetime.fromtimestamp(int(match.group(1)) / 1000)
            if 1990 < candidate.year <= datetime.now().year + 1:
                return candidate
        except (ValueError, OSError):
            pass
    return None


def get_video_date(path):
    return (
        get_metadata_date(path)
        or get_filename_date(path.name)
        or datetime.fromtimestamp(path.stat().st_mtime)
    )


def file_hash(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(HASH_CHUNK_SIZE):
            h.update(chunk)
    return h.hexdigest()


def load_index(video_root):
    index_path = video_root / INDEX_FILENAME
    if index_path.exists():
        with open(index_path, "r") as f:
            return json.load(f)
    return {}


def save_index(video_root, index):
    with open(video_root / INDEX_FILENAME, "w") as f:
        json.dump(index, f, indent=2)


def seed_index_from_existing(video_root, index):
    """Hash any files already sitting in the destination so videos placed
    there manually before the first run also count as 'already have it'."""
    known_paths = set(index.values())
    for root, dirs, files in os.walk(video_root):
        dirs[:] = [d for d in dirs if d.lower() not in SKIP_DIR_NAMES]
        for name in files:
            ext = os.path.splitext(name)[1].lower()
            if ext not in VIDEO_EXTENSIONS:
                continue
            file_path = Path(root) / name
            if str(file_path) in known_paths:
                continue
            try:
                digest = file_hash(file_path)
            except Exception:
                continue
            index.setdefault(digest, str(file_path))


def unique_destination_path(dest_dir, filename):
    candidate = dest_dir / filename
    if not candidate.exists():
        return candidate
    stem, ext = os.path.splitext(filename)
    counter = 1
    while candidate.exists():
        candidate = dest_dir / f"{stem}_{counter}{ext}"
        counter += 1
    return candidate


def scan_source(source, video_root, exclude_dirs, index, stats):
    for root, dirs, files in os.walk(source, onerror=lambda e: None):
        root_path = Path(root)
        if root_path in exclude_dirs or any(ex in root_path.parents for ex in exclude_dirs):
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if d.lower() not in SKIP_DIR_NAMES]

        for name in files:
            ext = os.path.splitext(name)[1].lower()
            if ext not in VIDEO_EXTENSIONS:
                continue
            file_path = root_path / name
            stats["scanned"] += 1
            try:
                digest = file_hash(file_path)
            except Exception as e:
                print(f"  ! couldn't read {file_path}: {e}")
                stats["errors"] += 1
                continue

            if digest in index:
                stats["duplicates"] += 1
                continue

            video_date = get_video_date(file_path)
            year_dir = video_root / str(video_date.year)
            year_dir.mkdir(parents=True, exist_ok=True)
            dest_path = unique_destination_path(year_dir, name)

            try:
                shutil.copy2(file_path, dest_path)
            except Exception as e:
                print(f"  ! couldn't copy {file_path}: {e}")
                stats["errors"] += 1
                continue

            index[digest] = str(dest_path)
            stats["copied"] += 1
            if stats["copied"] % 20 == 0:
                print(f"  ...{stats['copied']} videos copied so far")


def main():
    print("=== Video Consolidator ===\n")
    while True:
        destination = ask_path(
            "Destination folder for organized media (full path, e.g. D:\\Photos)",
            must_exist=False,
            must_be_absolute=True,
        )
        if is_unsafe_destination(destination):
            print(f"  Refusing to use '{destination.resolve()}' — that's a system folder or a bare drive root. Pick a specific folder, e.g. D:\\Photos.")
            continue
        break

    destination.mkdir(parents=True, exist_ok=True)
    destination = destination.resolve()
    video_root = destination / "Videos"
    video_root.mkdir(parents=True, exist_ok=True)
    print(f"  Videos will be organized under: {video_root}")

    sources = gather_sources(destination)

    print(f"\nVideo destination: {video_root}")
    print("Sources to scan:")
    for s in sources:
        print(f"  - {s}")
    if not ask_yes_no("\nProceed?"):
        print("Cancelled.")
        return

    index = load_index(video_root)
    seed_index_from_existing(video_root, index)

    stats = {"scanned": 0, "copied": 0, "duplicates": 0, "errors": 0}
    exclude_dirs = {destination}

    for source in sources:
        print(f"\nScanning {source} ...")
        scan_source(source.resolve(), video_root, exclude_dirs, index, stats)
        save_index(video_root, index)

    print("\n=== Done ===")
    print(f"Scanned:            {stats['scanned']}")
    print(f"Copied:              {stats['copied']}")
    print(f"Duplicates skipped:  {stats['duplicates']}")
    print(f"Errors:              {stats['errors']}")
    print(f"\nOrganized videos are in: {video_root}")


if __name__ == "__main__":
    main()
