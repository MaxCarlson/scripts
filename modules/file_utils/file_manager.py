#!/usr/bin/env python3

import os
import hashlib
import argparse
from collections import defaultdict

def calculate_file_hash(file_path, block_size=65536):
    """Calculate the hash of a file."""
    hasher = hashlib.sha256()
    with open(file_path, 'rb') as f:
        while chunk := f.read(block_size):
            hasher.update(chunk)
    return hasher.hexdigest()

def find_duplicates(directory, use_hashes=True):
    """Find duplicate files in a directory."""
    duplicates = defaultdict(list)
    files_by_name = defaultdict(list)

    # Group files by name
    for root, _, files in os.walk(directory):
        for file in files:
            full_path = os.path.join(root, file)
            files_by_name[file].append(full_path)

    if use_hashes:
        # Further filter by hash for files with the same name
        for file_list in files_by_name.values():
            if len(file_list) > 1:  # Only consider duplicates by name
                hash_map = defaultdict(list)
                for file_path in file_list:
                    file_hash = calculate_file_hash(file_path)
                    hash_map[file_hash].append(file_path)
                # Add duplicates (same hash) to the list
                for hash_files in hash_map.values():
                    if len(hash_files) > 1:
                        duplicates.update({hash_files[0]: hash_files[1:]})
    else:
        # If only using file names, add all but the first occurrence
        for file_list in files_by_name.values():
            if len(file_list) > 1:
                duplicates.update({file_list[0]: file_list[1:]})

    return duplicates

def delete_files(duplicates, dry_run=False):
    """Delete duplicate files."""
    stats = {
        "total_files": 0,
        "unique_files": 0,
        "duplicates_found": 0,
        "triplicates_found": 0,
        "total_size_deleted": 0
    }

    for original, dup_list in duplicates.items():
        stats["total_files"] += len(dup_list) + 1
        stats["unique_files"] += 1
        stats["duplicates_found"] += len(dup_list)
        if len(dup_list) > 1:
            stats["triplicates_found"] += len(dup_list) - 1

        for file_path in dup_list:
            try:
                if not dry_run:
                    stats["total_size_deleted"] += os.path.getsize(file_path)
                    os.remove(file_path)
                else:
                    stats["total_size_deleted"] += os.path.getsize(file_path)
                print(f"{'Would delete' if dry_run else 'Deleted'}: {file_path}")
            except OSError as e:
                print(f"Error {'deleting' if dry_run == False else f'dry {file_path}: (passable}'")


                def summarize_statistics(stats):
    """Print summary statistics about duplicate removal."""
    print("\n--- Duplicate Finder Summary ---")
    print(f"Total files scanned: {stats['total_files']}")
    print(f"Unique files: {stats['unique_files']}")
    print(f"Duplicates found: {stats['duplicates_found']}")
    print(f"Triplicates found: {stats['triplicates_found']}")
    print(f"Total size to be deleted: {stats['total_size_deleted'] / (1024 ** 2):.2f} MB")
    print("--------------------------------")

def organize_files(directory, mode):
    """Organize files in the directory based on the mode."""
    if mode == "type":
        for root, _, files in os.walk(directory):
            for file in files:
                ext = os.path.splitext(file)[1][1:].lower() or "no_extension"
                target_dir = os.path.join(directory, ext)
                os.makedirs(target_dir, exist_ok=True)
                os.rename(os.path.join(root, file), os.path.join(target_dir, file))
                print(f"Moved: {file} -> {target_dir}")
    elif mode == "date":
        for root, _, files in os.walk(directory):
            for file in files:
                full_path = os.path.join(root, file)
                ctime = os.path.getctime(full_path)
                date = time.strftime("%Y-%m-%d", time.localtime(ctime))
                target_dir = os.path.join(directory, date)
                os.makedirs(target_dir, exist_ok=True)
                os.rename(full_path, os.path.join(target_dir, file))
                print(f"Moved: {file} -> {target_dir}")

def main():
    parser = argparse.ArgumentParser(description="Advanced file manipulation tool.")
    parser.add_argument("-d", "--dir", required=True, help="Directory to process")
    parser.add_argument("--use-hashes", action="store_true", help="Use file hashes to find duplicates")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be deleted without making changes")
    parser.add_argument("--organize", choices=["type", "date"], help="Organize files by type or date")
    args = parser.parse_args()

    directory = args.dir
    if not os.path.isdir(directory):
        print(f"Error: {directory} is not a valid directory.")
        return

    if args.organize:
        print(f"Organizing files in {directory} by {args.organize}...")
        organize_files(directory, args.organize)
    else:
        print("Scanning for duplicates...")
        duplicates = find_duplicates(directory, args.use_hashes)
        stats = delete_files(duplicates, dry_run=args.dry_run)
        summarize_statistics(stats)

if __name__ == "__main__":
    main()
