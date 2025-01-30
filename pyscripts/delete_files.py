import os
import argparse
import fnmatch
from pathlib import Path

def find_files(base_path, pattern, max_depth=None):
    """Finds files matching pattern within base_path. If max_depth is set, limits recursion depth."""
    found_files = []
    base_path = Path(base_path).resolve()

    for root, dirs, files in os.walk(base_path):
        depth = len(Path(root).relative_to(base_path).parts)

        if max_depth is not None and depth > max_depth:
            del dirs[:]  # Prevents further recursion
            continue

        for filename in files:
            if fnmatch.fnmatch(filename, pattern):
                found_files.append(Path(root) / filename)

    return found_files


def delete_files(base_path, pattern, recursive, max_depth, dry_run):
    """Deletes files matching pattern, with optional recursion and depth limit."""
    print(f"🔍 Searching for '{pattern}' in '{base_path}' (recursive={recursive}, depth={max_depth})...")

    # Set max_depth if recursion is disabled
    max_depth = None if recursive else 0

    files_to_delete = find_files(base_path, pattern, max_depth)

    if not files_to_delete:
        print("✅ No matching files found.")
        return

    for file in files_to_delete:
        if dry_run:
            print(f"🟡 (Dry Run) Would delete: {file}")
        else:
            try:
                file.unlink()
                print(f"🗑️ Deleted: {file}")
            except Exception as e:
                print(f"❌ Error deleting {file}: {e}")

    print(f"✅ Done. {'No files deleted (dry run).' if dry_run else 'All matching files deleted.'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Delete files matching a pattern with optional recursion and dry run.")

    parser.add_argument("-p", "--pattern", required=True, help="Filename pattern to match (e.g., '*.log')")
    parser.add_argument("-s", "--source", default="./", help="Base directory to search (default: current directory)")
    parser.add_argument("-r", "--recursive", nargs="?", const=True, type=int, help="Enable recursive search (optional depth limit)")
    parser.add_argument("-d", "--dry-run", action="store_true", help="Dry run mode (list files but don't delete)")

    args = parser.parse_args()

    # Handle recursion depth
    if args.recursive is True:
        max_depth = None  # Unlimited recursion
    elif isinstance(args.recursive, int):
        max_depth = args.recursive  # Limited depth
    else:
        max_depth = 0  # No recursion

    delete_files(args.source, args.pattern, args.recursive, max_depth, args.dry_run)
