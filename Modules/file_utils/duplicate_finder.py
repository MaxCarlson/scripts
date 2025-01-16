import os
from collections import defaultdict
from .utils import calculate_file_hash, write_debug


def find_duplicates(directory, use_hashes=True):
    """Find duplicate files in a directory."""
    duplicates = defaultdict(list)
    files_by_name = defaultdict(list)

    for root, _, files in os.walk(directory):
        for file in files:
            full_path = os.path.join(root, file)
            files_by_name[file].append(full_path)

    if use_hashes:
        for file_list in files_by_name.values():
            if len(file_list) > 1:
                hash_map = defaultdict(list)
                for file_path in file_list:
                    file_hash = calculate_file_hash(file_path)
                    hash_map[file_hash].append(file_path)
                for hash_files in hash_map.values():
                    if len(hash_files) > 1:
                        duplicates[hash_files[0]].extend(hash_files[1:])
    else:
        for file_list in files_by_name.values():
            if len(file_list) > 1:
                duplicates[file_list[0]].extend(file_list[1:])

    return duplicates


def delete_files(duplicates, dry_run=False):
    """Delete duplicate files."""
    stats = {"total_files": 0, "unique_files": 0, "duplicates_found": 0, "total_size_deleted": 0}

    for original, dup_list in duplicates.items():
        stats["total_files"] += len(dup_list) + 1
        stats["unique_files"] += 1
        stats["duplicates_found"] += len(dup_list)

        for file_path in dup_list:
            try:
                if not dry_run:
                    os.remove(file_path)
                stats["total_size_deleted"] += os.path.getsize(file_path)
                print(f"{'Would delete' if dry_run else 'Deleted'}: {file_path}")
            except OSError as e:
                write_debug(f"Error deleting file {file_path}: {e}", channel="Error", condition=True)

    return stats


def summarize_statistics(stats):
    """Print summary statistics."""
    print("\n--- Duplicate Finder Summary ---")
    print(f"Total files scanned: {stats['total_files']}")
    print(f"Unique files: {stats['unique_files']}")
    print(f"Duplicates found: {stats['duplicates_found']}")
    print(f"Total size deleted: {stats['total_size_deleted'] / (1024 ** 2):.2f} MB")
    print("--------------------------------")
