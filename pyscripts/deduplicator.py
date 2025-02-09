#!/usr/bin/env python3
import argparse
import hashlib
import os
import shutil
import fnmatch
import threading
import time
import concurrent.futures
from collections import defaultdict

# ----------------------------------------------------------------------
# Global progress (for live summary)
# ----------------------------------------------------------------------
progress_lock = threading.Lock()
progress = {
    "files_scanned": 0,       # files scanned during the gathering phase
    "files_total": 0,         # total files discovered (for scanning progress)
    "processed_files": 0,     # number of files processed (deleted/moved)
    "total_size": 0,          # cumulative size processed (in bytes)
    "ext_summary": defaultdict(lambda: {"count": 0, "size": 0}),
    "total_to_delete": 0      # number of files scheduled for deletion/backup
}
stop_event = threading.Event()

# ----------------------------------------------------------------------
# Helper: compute file hash
# ----------------------------------------------------------------------
def compute_hash(file_path, block_size=65536):
    """Compute SHA-256 hash of a file."""
    hasher = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            for block in iter(lambda: f.read(block_size), b""):
                hasher.update(block)
    except Exception as e:
        # In production you might log this error.
        return None
    return hasher.hexdigest()

# ----------------------------------------------------------------------
# File gathering with recursion-depth limit
# ----------------------------------------------------------------------
def gather_files(base_dir, pattern, max_depth):
    """
    Recursively gather files from base_dir (up to max_depth).
    max_depth: use float('inf') for no limit.
    Returns a list of tuples: (dirpath, filename, full_file_path).
    """
    file_entries = []
    for dirpath, dirs, files in os.walk(base_dir):
        rel_path = os.path.relpath(dirpath, base_dir)
        depth = 0 if rel_path == "." else len(rel_path.split(os.sep))
        if depth > max_depth:
            dirs[:] = []  # do not descend further
            continue
        for filename in files:
            if pattern and not fnmatch.fnmatch(filename, pattern):
                continue
            file_path = os.path.join(dirpath, filename)
            file_entries.append((dirpath, filename, file_path))
        # (You could update scanning progress here if desired.)
    return file_entries

# ----------------------------------------------------------------------
# Find duplicates (using concurrent hashing)
# ----------------------------------------------------------------------
def find_duplicates(base_dir, pattern=None, check_name=False, check_similar=False, max_depth=float('inf')):
    """
    Gathers files (using gather_files) and computes their hash concurrently.
    Returns three dictionaries:
      - hash_map: {hash: [file_paths, ...]}
      - name_map: {(dir, filename): [file_paths, ...]} if check_name is True, else None.
      - similar_map: {(dir, filename, size): [file_paths, ...]} if check_similar is True, else None.
    """
    file_entries = gather_files(base_dir, pattern, max_depth)
    with progress_lock:
        progress["files_total"] = len(file_entries)
    hash_map = defaultdict(list)
    name_map = defaultdict(list) if check_name else None
    similar_map = defaultdict(list) if check_similar else None

    def process_entry(entry):
        dirpath, filename, file_path = entry
        h = compute_hash(file_path)
        result = {"dirpath": dirpath, "filename": filename, "file_path": file_path, "hash": h}
        if check_similar:
            try:
                size = os.path.getsize(file_path)
            except:
                size = -1
            result["size"] = size
        return result

    results = []
    with concurrent.futures.ThreadPoolExecutor() as executor:
        future_to_entry = {executor.submit(process_entry, entry): entry for entry in file_entries}
        for future in concurrent.futures.as_completed(future_to_entry):
            try:
                res = future.result()
                results.append(res)
            except Exception as e:
                continue
            with progress_lock:
                progress["files_scanned"] += 1

    for res in results:
        file_path = res["file_path"]
        h = res["hash"]
        if h is not None:
            hash_map[h].append(file_path)
        if check_name and name_map is not None:
            key = (res["dirpath"], res["filename"])
            name_map[key].append(file_path)
        if check_similar and similar_map is not None:
            try:
                size = res.get("size", os.path.getsize(file_path))
            except:
                size = -1
            key = (res["dirpath"], res["filename"], size)
            similar_map[key].append(file_path)
    return hash_map, name_map, similar_map

# ----------------------------------------------------------------------
# Retention policy: which files to delete?
# ----------------------------------------------------------------------
def sorting_key(keep_newest, keep_deepest):
    """
    Returns a key function that sorts a file path based on modification time and path depth.
    By default: oldest (lowest mtime) and shallowest (lowest depth) are preferred.
    If keep_newest is True, reverse time order.
    If keep_deepest is True, reverse depth order.
    """
    def key_func(f):
        try:
            mtime = os.path.getmtime(f)
        except Exception:
            mtime = 0
        time_key = -mtime if keep_newest else mtime
        depth = len(os.path.normpath(f).split(os.sep))
        depth_key = -depth if keep_deepest else depth
        return (time_key, depth_key)
    return key_func

def get_deletions_for_group(group, all_dirs, keep_newest, keep_deepest):
    """
    From a group of duplicate files, decide which ones to delete.
    If all_dirs is True, consider the group as a whole; otherwise, work folder‐by‐folder.
    In each group (or sub‐group) the “best” file is kept and the others are deleted.
    """
    deletions = []
    if all_dirs:
        group.sort(key=sorting_key(keep_newest, keep_deepest))
        if len(group) > 1:
            deletions.extend(group[1:])
    else:
        # Group files by their parent folder.
        dir_map = defaultdict(list)
        for f in group:
            dir_map[os.path.dirname(f)].append(f)
        for files in dir_map.values():
            if len(files) > 1:
                files.sort(key=sorting_key(keep_newest, keep_deepest))
                deletions.extend(files[1:])
    return deletions

def determine_deletions(duplicates, all_dirs=False, keep_newest=False, keep_deepest=False):
    """
    For each duplicate group (a value in the dictionary), decide which files to delete.
    Returns a set of file paths.
    """
    to_delete = set()
    for group in duplicates.values():
        if len(group) < 2:
            continue
        deletions = get_deletions_for_group(group, all_dirs, keep_newest, keep_deepest)
        to_delete.update(deletions)
    return to_delete

# ----------------------------------------------------------------------
# Backup (or delete) file operation
# ----------------------------------------------------------------------
def backup_file(file_path, backup_dir, base_dir):
    """
    Moves the file to backup_dir, preserving the folder hierarchy relative to base_dir.
    """
    rel_path = os.path.relpath(file_path, base_dir)
    backup_path = os.path.join(backup_dir, rel_path)
    os.makedirs(os.path.dirname(backup_path), exist_ok=True)
    shutil.move(file_path, backup_path)

# ----------------------------------------------------------------------
# Live summary thread (updates every 2 seconds)
# ----------------------------------------------------------------------
def live_summary():
    """Every 2 seconds, clear the terminal and print current progress."""
    while not stop_event.is_set():
        with progress_lock:
            scanned = progress.get("files_scanned", 0)
            total = progress.get("files_total", '?')
            processed = progress.get("processed_files", 0)
            total_size = progress.get("total_size", 0)
            ext_summary_copy = dict(progress.get("ext_summary", {}))
            total_to_delete = progress.get("total_to_delete", 0)
        # Clear screen and move cursor to top (ANSI codes)
        print("\033[2J\033[H", end="")
        print("=== Live Summary ===")
        print(f"Files scanned: {scanned}/{total}")
        print(f"Files processed for deletion/backup: {processed}/{total_to_delete}")
        print(f"Total size processed: {total_size / (1024 * 1024):.2f} MB")
        print("\nBreakdown by extension:")
        for ext, data in sorted(ext_summary_copy.items()):
            ext_display = ext if ext else "[No Extension]"
            print(f"  {ext_display}: {data['count']} files, {data['size'] / (1024 * 1024):.2f} MB")
        time.sleep(2)

# ----------------------------------------------------------------------
# Process files: delete (or back up) each file marked for deletion.
# ----------------------------------------------------------------------
def process_files(file_paths, dry_run=False, backup_dir=None, base_dir=None):
    """
    For each file in file_paths, either delete it or, if backup_dir is set, move it.
    Update the progress counters.
    Returns the total number of files processed and total size.
    """
    local_count = 0
    local_size = 0
    for file_path in file_paths:
        try:
            file_size = os.path.getsize(file_path)
        except OSError:
            file_size = 0
        file_ext = os.path.splitext(file_path)[-1].lower()
        if not dry_run:
            if backup_dir and base_dir:
                backup_file(file_path, backup_dir, base_dir)
            else:
                try:
                    os.remove(file_path)
                except Exception as e:
                    pass
        local_count += 1
        local_size += file_size
        with progress_lock:
            progress["processed_files"] += 1
            progress["total_size"] += file_size
            progress["ext_summary"][file_ext]["count"] += 1
            progress["ext_summary"][file_ext]["size"] += file_size
    return local_count, local_size

def print_final_summary(total_deleted, total_size_deleted, ext_summary, dry_run=False):
    """Print a final summary after processing is complete."""
    print("\n=== Final Summary ===")
    if dry_run:
        print("Dry run mode: no files were actually deleted or backed up.")
    print(f"Total duplicate files processed: {total_deleted}")
    print(f"Total size processed: {total_size_deleted / (1024 * 1024):.2f} MB")
    print("\nBreakdown by extension:")
    for ext, data in sorted(ext_summary.items()):
        ext_display = ext if ext else "[No Extension]"
        print(f"  {ext_display}: {data['count']} files, {data['size'] / (1024 * 1024):.2f} MB")

# ----------------------------------------------------------------------
# Report mode: show duplicate counts without making any changes.
# ----------------------------------------------------------------------
def report_mode(base_dir, max_depth):
    """
    For each folder (up to max_depth) within base_dir, report:
      - The number of exact duplicate groups (files with matching hashes)
      - The number of “similar” duplicate groups (files with matching name and size but differing hashes)
    Comparisons are limited to files within each folder.
    """
    for dirpath, dirs, files in os.walk(base_dir):
        rel_path = os.path.relpath(dirpath, base_dir)
        depth = 0 if rel_path == "." else len(rel_path.split(os.sep))
        if depth > max_depth:
            dirs[:] = []
            continue
        if not files:
            continue
        file_info = []  # list of (name, size, hash, full_path)
        for filename in files:
            file_path = os.path.join(dirpath, filename)
            try:
                size = os.path.getsize(file_path)
            except:
                size = 0
            h = compute_hash(file_path)
            file_info.append((filename, size, h, file_path))
        # Group by hash:
        hash_groups = defaultdict(list)
        for name, size, h, path in file_info:
            if h is not None:
                hash_groups[h].append(path)
        hash_dup_groups = [group for group in hash_groups.values() if len(group) > 1]
        hash_dup_count = len(hash_dup_groups)
        hash_dup_files = sum(len(group) for group in hash_dup_groups)
        # Group by (name, size):
        name_size_groups = defaultdict(list)
        for name, size, h, path in file_info:
            name_size_groups[(name, size)].append((path, h))
        similar_dup_groups = []
        for group in name_size_groups.values():
            if len(group) > 1:
                hashes = {h for (_, h) in group if h is not None}
                if len(hashes) > 1:
                    similar_dup_groups.append(group)
        similar_dup_count = len(similar_dup_groups)
        similar_dup_files = sum(len(group) for group in similar_dup_groups)
        print(f"Folder: {dirpath}")
        print(f"  Exact duplicates (by hash): {hash_dup_count} groups, {hash_dup_files} files")
        print(f"  Similar duplicates (by name & size but not hash): {similar_dup_count} groups, {similar_dup_files} files")
        print("-" * 40)
    print("=== End of Report ===")

# ----------------------------------------------------------------------
# Main: argument parsing and orchestration
# ----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Duplicate file deduplicator and reporter.")
    parser.add_argument("directory", type=str, help="Directory to scan for duplicates")
    parser.add_argument("-p", "--pattern", type=str, help="Glob pattern for files to check")
    parser.add_argument("-n", "--name", action="store_true",
                        help="Delete files with the same name in the same directory (ignoring content differences)")
    parser.add_argument("-s", "--similar", action="store_true",
                        help="Treat files as duplicates if they have the same name and size in the same folder")
    parser.add_argument("-a", "--all-dirs", action="store_true",
                        help="Consider duplicates across all directories (keep one highest-level version)")
    parser.add_argument("-r", "--recursive", nargs="?", const=-1, type=int,
                        help="Recursively search directories. If no depth is given, search as deep as possible. "
                             "If an integer is provided, limit recursion to that depth (base directory is depth 0)")
    parser.add_argument("--new", action="store_true", help="Keep the newest file instead of the oldest")
    parser.add_argument("-d", "--deepest", action="store_true",
                        help="Keep the deepest file instead of the highest-level one")
    parser.add_argument("-x", "--dry-run", action="store_true",
                        help="Show files that would be deleted without deleting them")
    parser.add_argument("-b", "--backup", type=str,
                        help="Backup directory to move deleted files instead of deleting them")
    parser.add_argument("-H", "--hash", dest="hash_mode", action="store_true",
                        help="Report mode: print duplicate counts by hash and by name+size (similar) for each folder, without making any changes")
    
    args = parser.parse_args()
    base_dir = os.path.abspath(args.directory)
    
    # Determine recursion depth:
    # • If -r is not given, scan only the base directory (depth 0).
    # • If -r is given with no parameter, use unlimited depth.
    # • If -r <number> is given, limit to that depth.
    if args.recursive is None:
        max_depth = 0
    elif args.recursive == -1:
        max_depth = float('inf')
    else:
        max_depth = args.recursive

    if args.hash_mode:
        # Report mode – simply report duplicate counts per folder.
        report_mode(base_dir, max_depth)
        return

    # Start the live summary thread early so that scanning progress is shown.
    summary_thread = threading.Thread(target=live_summary, daemon=True)
    summary_thread.start()

    # Gather files and compute duplicates.
    hash_map, name_map, similar_map = find_duplicates(
        base_dir,
        pattern=args.pattern,
        check_name=args.name,
        check_similar=args.similar,
        max_depth=max_depth
    )

    # Determine files to delete based on each criterion.
    to_delete = set()
    # Always use hash‐based duplicates.
    to_delete.update(determine_deletions(hash_map, all_dirs=args.all_dirs, keep_newest=args.new, keep_deepest=args.deepest))
    if args.name and name_map is not None:
        to_delete.update(determine_deletions(name_map, all_dirs=False, keep_newest=args.new, keep_deepest=args.deepest))
    if args.similar and similar_map is not None:
        to_delete.update(determine_deletions(similar_map, all_dirs=False, keep_newest=args.new, keep_deepest=args.deepest))

    with progress_lock:
        progress["total_to_delete"] = len(to_delete)

    total_deleted, total_size_deleted = process_files(
        list(to_delete), dry_run=args.dry_run, backup_dir=args.backup, base_dir=base_dir
    )

    stop_event.set()
    summary_thread.join()

    with progress_lock:
        ext_summary_final = dict(progress["ext_summary"])
    print_final_summary(total_deleted, total_size_deleted, ext_summary_final, dry_run=args.dry_run)

if __name__ == "__main__":
    main()
