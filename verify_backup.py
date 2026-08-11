#!/usr/bin/env python3
"""
verify_backup.py

Compares two folders (e.g. your original photo/video library and a backup
copy on an SD card or SSD) by hashing every file and checking they match.

Usage:
    python verify_backup.py /path/to/original /path/to/backup

Or generate a checksum manifest now, and verify against it later
(useful for checking a fireproof-box copy months/years down the line):

    python verify_backup.py /path/to/original --save manifest.txt
    python verify_backup.py /path/to/backup --check manifest.txt
"""

import argparse
import hashlib
import os
import sys
from pathlib import Path


def hash_file(path, chunk_size=1024 * 1024):
    """Return the SHA-256 hash of a file, reading in chunks (safe for large video files)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def build_manifest(root):
    """Walk a directory and return {relative_path: hash} for every file."""
    root = Path(root)
    manifest = {}
    files = [p for p in root.rglob("*") if p.is_file()]
    total = len(files)

    for i, path in enumerate(files, 1):
        rel = path.relative_to(root)
        print(f"\rHashing {i}/{total}: {rel}", end="", flush=True)
        try:
            manifest[str(rel)] = hash_file(path)
        except (OSError, PermissionError) as e:
            print(f"\n  WARNING: could not read {rel}: {e}")
            manifest[str(rel)] = None
    print()
    return manifest


def save_manifest(manifest, out_path):
    with open(out_path, "w", encoding="utf-8") as f:
        for rel, digest in sorted(manifest.items()):
            f.write(f"{digest}  {rel}\n")
    print(f"Saved manifest of {len(manifest)} files to {out_path}")


def load_manifest(path):
    manifest = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            digest, rel = line.split("  ", 1)
            manifest[rel] = digest if digest != "None" else None
    return manifest


def compare(manifest_a, manifest_b, label_a="original", label_b="backup"):
    files_a = set(manifest_a)
    files_b = set(manifest_b)

    missing_in_b = sorted(files_a - files_b)
    missing_in_a = sorted(files_b - files_a)
    common = files_a & files_b

    mismatches = sorted(
        rel for rel in common if manifest_a[rel] != manifest_b[rel]
    )
    matches = len(common) - len(mismatches)

    print("\n--- Verification report ---")
    print(f"Files in {label_a}: {len(files_a)}")
    print(f"Files in {label_b}: {len(files_b)}")
    print(f"Matching (identical): {matches}")

    if missing_in_b:
        print(f"\nMissing from {label_b} ({len(missing_in_b)}):")
        for rel in missing_in_b[:20]:
            print(f"  - {rel}")
        if len(missing_in_b) > 20:
            print(f"  ... and {len(missing_in_b) - 20} more")

    if missing_in_a:
        print(f"\nExtra files in {label_b}, not in {label_a} ({len(missing_in_a)}):")
        for rel in missing_in_a[:20]:
            print(f"  - {rel}")
        if len(missing_in_a) > 20:
            print(f"  ... and {len(missing_in_a) - 20} more")

    if mismatches:
        print(f"\nCONTENT MISMATCHES ({len(mismatches)}) -- these files differ between copies:")
        for rel in mismatches[:20]:
            print(f"  - {rel}")
        if len(mismatches) > 20:
            print(f"  ... and {len(mismatches) - 20} more")

    ok = not missing_in_b and not missing_in_a and not mismatches
    print("\nResult:", "PASS - backup is a verified exact match." if ok else "FAIL - see issues above.")
    return ok


def main():
    parser = argparse.ArgumentParser(description="Verify a backup by comparing file hashes.")
    parser.add_argument("path", help="Folder to hash (original or backup)")
    parser.add_argument("second_path", nargs="?", help="Second folder to compare against")
    parser.add_argument("--save", metavar="MANIFEST", help="Save hashes of `path` to this manifest file")
    parser.add_argument("--check", metavar="MANIFEST", help="Compare `path` against a previously saved manifest")
    args = parser.parse_args()

    if args.save:
        manifest = build_manifest(args.path)
        save_manifest(manifest, args.save)
        return

    if args.check:
        manifest_now = build_manifest(args.path)
        manifest_saved = load_manifest(args.check)
        ok = compare(manifest_saved, manifest_now, label_a="saved manifest", label_b="current folder")
        sys.exit(0 if ok else 1)

    if args.second_path:
        manifest_a = build_manifest(args.path)
        manifest_b = build_manifest(args.second_path)
        ok = compare(manifest_a, manifest_b)
        sys.exit(0 if ok else 1)

    parser.print_help()


if __name__ == "__main__":
    main()
