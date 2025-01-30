import os
import zipfile
import argparse
import fnmatch
import shutil
from pathlib import Path

# Default patterns
DEFAULT_EXCLUDE_DIRS = {".git", ".hg", ".svn", "__pycache__", "node_modules", ".idea", ".vscode", ".mypy_cache", ".pytest_cache"}
DEFAULT_EXCLUDE_EXTS = {".pyc", ".pyo", ".exe", ".dll", ".bin", ".o", ".so", ".zip", ".tar", ".gz", ".7z"}
DEFAULT_EXCLUDE_FILES = {"package-lock.json", "yarn.lock", "Pipfile.lock"}
DEFAULT_MAX_HIERARCHY_DEPTH = 100
DEFAULT_MAX_HIERARCHY_LINES = 50000  # Roughly estimated for ~10MB

def get_directory_size(directory):
    """Returns total size of directory (in bytes)."""
    return sum(f.stat().st_size for f in Path(directory).rglob('*') if f.is_file())

def should_exclude(path, exclude_dirs, exclude_exts, exclude_files):
    return path.is_dir() and path.name in exclude_dirs or path.suffix in exclude_exts or path.name in exclude_files

def matches_patterns(path, patterns):
    return any(fnmatch.fnmatch(path.name, pattern) for pattern in patterns)

def flatten_directory(source_dir, name_by_path):
    """Moves all files to a single directory and renames them if required."""
    temp_flat_dir = Path(source_dir) / "_flattened"
    temp_flat_dir.mkdir(exist_ok=True)
    moved_files = []
    
    for root, _, files in os.walk(source_dir):
        root_path = Path(root)
        for file in files:
            original_path = root_path / file
            if original_path.parent == temp_flat_dir:
                continue  # Skip already moved files
            
            new_filename = file
            if name_by_path:
                rel_path = original_path.relative_to(source_dir)
                new_filename = f"{'_'.join(rel_path.parts)}"
            
            new_path = temp_flat_dir / new_filename
            shutil.move(str(original_path), str(new_path))
            moved_files.append(str(new_path))

    print(f"Flattened {len(moved_files)} files into {temp_flat_dir}.")
    return temp_flat_dir

def delete_files_to_fit_size(directory, target_size_mb, preferences):
    """Deletes files in order of preference to meet target size."""
    target_size_bytes = target_size_mb * 1024 * 1024
    current_size = get_directory_size(directory)

    if current_size <= target_size_bytes:
        return

    print(f"Reducing size... Current: {current_size / (1024 * 1024):.2f} MB, Target: {target_size_mb} MB")

    all_files = sorted(
        [f for f in Path(directory).rglob('*') if f.is_file()],
        key=lambda f: f.stat().st_size,
        reverse=True
    )

    # Order files by preference
    sorted_files = []
    for ext in preferences:
        sorted_files.extend([f for f in all_files if f.suffix == ext])
    
    sorted_files.extend([f for f in all_files if f.suffix not in preferences])  # Append the rest

    removed_files = []
    for file in sorted_files:
        if current_size <= target_size_bytes:
            break
        file_size = file.stat().st_size
        file.unlink()
        removed_files.append(str(file))
        current_size -= file_size

    print(f"Deleted {len(removed_files)} files to meet size constraint.")
    return removed_files

def zip_folder(source_dir, output_zip, exclude_dirs, exclude_exts, exclude_files, remove_patterns, keep_patterns, max_size, preferences, flatten, name_by_path, verbose):
    """Zips the folder, enforcing a max file size if necessary."""
    source_dir = Path(source_dir).resolve()
    zip_path = Path(output_zip).resolve()
    temp_dir = None

    if flatten:
        temp_dir = flatten_directory(source_dir, name_by_path)
        source_dir = temp_dir

    while True:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(source_dir):
                root_path = Path(root)
                dirs[:] = [d for d in dirs if not should_exclude(root_path / d, exclude_dirs, exclude_exts, exclude_files)]
                
                for file in files:
                    file_path = root_path / file
                    if should_exclude(file_path, exclude_dirs, exclude_exts, exclude_files):
                        continue
                    
                    if matches_patterns(file_path, remove_patterns) and not matches_patterns(file_path, keep_patterns):
                        continue

                    arcname = file_path.relative_to(source_dir)
                    zipf.write(file_path, arcname)
                    if verbose:
                        print(f"Added: {arcname}")

        zip_size_mb = zip_path.stat().st_size / (1024 * 1024)
        if max_size is None or zip_size_mb <= max_size:
            print(f"\nFinal zip file size: {zip_size_mb:.2f} MB")
            break

        print(f"Zip file too large ({zip_size_mb:.2f} MB > {max_size} MB). Removing files...")
        delete_files_to_fit_size(source_dir, max_size, preferences)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Zip a folder while applying exclusions and creating a folder structure file.")

    parser.add_argument("-s", "--source", required=True, help="Path to the folder to zip")
    parser.add_argument("-o", "--output", required=True, help="Output zip file path")

    parser.add_argument("-xd", "--exclude-dir", nargs="*", default=list(DEFAULT_EXCLUDE_DIRS), help="Directories to exclude")
    parser.add_argument("-xe", "--exclude-ext", nargs="*", default=list(DEFAULT_EXCLUDE_EXTS), help="File extensions to exclude")
    parser.add_argument("-xf", "--exclude-file", nargs="*", default=list(DEFAULT_EXCLUDE_FILES), help="Specific filenames to exclude")

    parser.add_argument("-if", "--include-file", nargs="*", default=[], help="Force include specific files")
    parser.add_argument("-r", "--remove-patterns", nargs="*", default=[], help="Glob patterns for additional file removal")
    parser.add_argument("-k", "--keep-patterns", nargs="*", default=[], help="Glob patterns to prevent file removal")

    parser.add_argument("-ms", "--max-size", type=int, help="Maximum zip size in MB")
    parser.add_argument("-p", "--preferences", nargs="*", default=[], help="File extensions prioritized for deletion")

    parser.add_argument("-f", "--flatten", action="store_true", help="Flatten the directory before zipping")
    parser.add_argument("-np", "--name-by-path", action="store_true", help="Use full path in filenames when flattening")

    parser.add_argument("-v", "--verbose", action="store_true", help="Print detailed logs")

    args = parser.parse_args()
    
    exclude_dirs = set(args.exclude_dir)
    exclude_exts = set(args.exclude_ext)
    exclude_files = set(args.exclude_file) - set(args.include_file)

    zip_folder(args.source, args.output, exclude_dirs, exclude_exts, exclude_files, args.remove_patterns, args.keep_patterns, args.max_size, args.preferences, args.flatten, args.name_by_path, args.verbose)
