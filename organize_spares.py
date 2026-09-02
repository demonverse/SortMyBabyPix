"""
Sweeps up everything that is NOT a photo or a video from one or more drives
and copies it into one flat folder (D:\\Spares by default) for manual
sorting, skipping exact duplicate files and common OS junk (Thumbs.db,
desktop.ini, .DS_Store).

No external dependencies.
"""
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

# Same extension sets as organize_photos.py / organize_videos.py — anything
# matching these is considered "already handled" and skipped here.
PHOTO_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff",
    ".heic", ".heif", ".webp",
}
VIDEO_EXTENSIONS = {
    ".mp4", ".mov", ".avi", ".m4v", ".3gp", ".3g2",
    ".mkv", ".m2ts", ".mts", ".wmv", ".flv", ".webm",
}
HANDLED_EXTENSIONS = PHOTO_EXTENSIONS | VIDEO_EXTENSIONS

IGNORE_FILENAMES = {"thumbs.db", "desktop.ini", ".ds_store"}
SKIP_DIR_NAMES = {"system volume information", "$recycle.bin"}
INDEX_FILENAME = ".spares_sync_index.json"
HASH_CHUNK_SIZE = 1024 * 1024
DEFAULT_DESTINATION = r"D:\Spares"

UNSAFE_DEST_DIRS = {
    r"c:\windows",
    r"c:\program files",
    r"c:\program files (x86)",
}


def ask_yes_no(prompt):
    while True:
        answer = input(f"{prompt} (y/n): ").strip().lower()
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print("Please answer y or n.")


def ask_path(prompt, must_exist=True, must_be_absolute=False, default=None):
    suffix = f" [{default}]" if default else ""
    while True:
        raw = input(f"{prompt}{suffix}: ").strip().strip('"')
        if not raw and default is not None:
            raw = default
        if not raw:
            print("  Please type a path (can't be blank).")
            continue
        path = Path(raw)
        if must_be_absolute and not path.is_absolute():
            print(f"  Please enter a full path starting with a drive letter, e.g. D:\\Spares (got '{raw}').")
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
    sources.append(ask_path("  Path (e.g. E:\\ or E:\\)"))

    while ask_yes_no("\nAdd another drive to scan?"):
        sources.append(ask_path("  Path"))

    dest_drive_root = Path(destination.resolve().anchor)
    if ask_yes_no(
        f"\nAlso scan the destination drive itself ({dest_drive_root}) for "
        f"existing loose non-photo/video files to fold in?"
    ):
        sources.append(dest_drive_root)

    return sources


def file_hash(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(HASH_CHUNK_SIZE):
            h.update(chunk)
    return h.hexdigest()


def load_index(destination):
    index_path = destination / INDEX_FILENAME
    if index_path.exists():
        with open(index_path, "r") as f:
            return json.load(f)
    return {}


def save_index(destination, index):
    with open(destination / INDEX_FILENAME, "w") as f:
        json.dump(index, f, indent=2)


def seed_index_from_existing(destination, index):
    """Hash any files already sitting in the destination so files placed
    there manually before the first run also count as 'already have it'."""
    known_paths = set(index.values())
    for name in os.listdir(destination):
        file_path = destination / name
        if not file_path.is_file() or name == INDEX_FILENAME:
            continue
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


def scan_source(source, destination, exclude_dirs, index, stats):
    for root, dirs, files in os.walk(source, onerror=lambda e: None):
        root_path = Path(root)
        if root_path in exclude_dirs or any(ex in root_path.parents for ex in exclude_dirs):
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if d.lower() not in SKIP_DIR_NAMES]

        for name in files:
            if name.lower() in IGNORE_FILENAMES:
                continue
            ext = os.path.splitext(name)[1].lower()
            if ext in HANDLED_EXTENSIONS:
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

            dest_path = unique_destination_path(destination, name)

            try:
                shutil.copy2(file_path, dest_path)
            except Exception as e:
                print(f"  ! couldn't copy {file_path}: {e}")
                stats["errors"] += 1
                continue

            index[digest] = str(dest_path)
            stats["copied"] += 1
            if stats["copied"] % 100 == 0:
                print(f"  ...{stats['copied']} files copied so far")


def main():
    print("=== Spares Collector ===")
    print("Copies everything that ISN'T a photo or video into one folder for you to sort manually.\n")
    while True:
        destination = ask_path(
            "Destination folder (full path)",
            must_exist=False,
            must_be_absolute=True,
            default=DEFAULT_DESTINATION,
        )
        if is_unsafe_destination(destination):
            print(f"  Refusing to use '{destination.resolve()}' — that's a system folder or a bare drive root. Pick a specific folder, e.g. D:\\Spares.")
            continue
        break

    destination.mkdir(parents=True, exist_ok=True)
    destination = destination.resolve()
    print(f"  Using destination: {destination}")

    sources = gather_sources(destination)

    print(f"\nDestination: {destination}")
    print("Sources to scan:")
    for s in sources:
        print(f"  - {s}")
    if not ask_yes_no("\nProceed?"):
        print("Cancelled.")
        return

    index = load_index(destination)
    seed_index_from_existing(destination, index)

    stats = {"scanned": 0, "copied": 0, "duplicates": 0, "errors": 0}
    exclude_dirs = {destination}

    for source in sources:
        print(f"\nScanning {source} ...")
        scan_source(source.resolve(), destination, exclude_dirs, index, stats)
        save_index(destination, index)

    print("\n=== Done ===")
    print(f"Scanned:            {stats['scanned']}")
    print(f"Copied:              {stats['copied']}")
    print(f"Duplicates skipped:  {stats['duplicates']}")
    print(f"Errors:              {stats['errors']}")
    print(f"\nEverything else is in: {destination}")


if __name__ == "__main__":
    main()
