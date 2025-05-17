#!/usr/bin/env python3
import os
import zipfile
import argparse
import fnmatch
import shutil
from pathlib import Path

# Default patterns
DEFAULT_EXCLUDE_DIRS = {
    ".git", ".hg", ".svn", "__pycache__",
    "node_modules", ".idea", ".vscode",
    ".mypy_cache", ".pytest_cache"
}
DEFAULT_EXCLUDE_EXTS = {
    ".pyc", ".pyo", ".exe", ".dll", ".bin",
    ".o", ".so", ".zip", ".tar", ".gz", ".7z"
}
DEFAULT_EXCLUDE_FILES = {
    "package-lock.json", "yarn.lock", "Pipfile.lock"
}

def get_directory_size(directory: Path) -> int:
    """Returns total size (bytes) of files under `directory`."""
    return sum(
        f.stat().st_size
        for f in directory.rglob('*')
        if f.is_file()
    )

def should_exclude(path: Path,
                   exclude_dirs: set[str],
                   exclude_exts: set[str],
                   exclude_files: set[str]) -> bool:
    """Checks default exclusions (dirs, exts, filenames)."""
    return (
        (path.is_dir() and path.name in exclude_dirs) or
        (path.suffix in exclude_exts) or
        (path.name in exclude_files)
    )

def matches_patterns(path: Path, patterns: list[str]) -> bool:
    """Returns True if `path.name` matches any glob in patterns."""
    return any(fnmatch.fnmatch(path.name, pat) for pat in patterns)

def flatten_directory(source_dir: Path, name_by_path: bool) -> Path:
    """
    Moves all non-excluded files into `<source_dir>/_flattened`,
    optionally renaming to include path.
    """
    source_dir = source_dir.resolve()
    flat = source_dir / "_flattened"
    flat.mkdir(exist_ok=True)
    moved = []

    for root, _, files in os.walk(source_dir):
        root_path = Path(root)
        if root_path == flat:
            continue
        for fn in files:
            orig = root_path / fn
            # skip excluded by default sets
            if should_exclude(orig,
                              DEFAULT_EXCLUDE_DIRS,
                              DEFAULT_EXCLUDE_EXTS,
                              DEFAULT_EXCLUDE_FILES):
                continue
            # skip if already in flat
            if orig.parent == flat:
                continue
            if name_by_path:
                rel = orig.relative_to(source_dir)
                new_name = "_".join(rel.parts)
            else:
                new_name = fn
            dest = flat / new_name
            shutil.move(str(orig), str(dest))
            moved.append(str(dest))

    print(f"Flattened {len(moved)} files into {flat}.")
    return flat

def delete_files_to_fit_size(directory: Path,
                             target_size_mb: int,
                             preferences: list[str]) -> list[str]:
    """
    Deletes files (largest first, respecting preferences order)
    until total size <= target_size_mb. Returns list of deleted paths.
    """
    target = target_size_mb * 1024 * 1024
    current = get_directory_size(directory)
    if current <= target:
        return []

    print(f"Reducing size... Current: {current/(1024*1024):.2f} MB, Target: {target_size_mb} MB")
    all_files = sorted(
        (f for f in directory.rglob('*') if f.is_file()),
        key=lambda f: f.stat().st_size,
        reverse=True
    )

    # order by preferences
    ordered: list[Path] = []
    for ext in preferences:
        ordered.extend([f for f in all_files if f.suffix == ext])
    ordered.extend([f for f in all_files if f.suffix not in preferences])

    removed = []
    for f in ordered:
        if current <= target:
            break
        sz = f.stat().st_size
        f.unlink()
        removed.append(str(f))
        current -= sz

    print(f"Deleted {len(removed)} files to meet size constraint.")
    return removed

def zip_folder(source_dir: str,
               output_zip: str,
               exclude_dirs: set[str],
               exclude_exts: set[str],
               exclude_files: set[str],
               remove_patterns: list[str],
               keep_patterns: list[str],
               max_size: int | None,
               preferences: list[str],
               flatten: bool,
               name_by_path: bool,
               verbose: bool) -> None:
    """
    Zips the folder at `source_dir` into `output_zip`, applying exclusions,
    optional flattening, and max-size pruning. Also writes `folder_structure.txt`.
    """
    src = Path(source_dir).resolve()
    out = Path(output_zip).resolve()

    # generate hierarchy file
    hier = src / "folder_structure.txt"
    with open(hier, 'w', encoding='utf-8') as f:
        f.write("Folder Structure\n")
        for root, dirs, _ in os.walk(src):
            rel = Path(root).relative_to(src)
            indent = '    ' * len(rel.parts)
            name = rel.name if rel.parts else src.name
            f.write(f"{indent}{name}/\n")

    # optionally flatten
    working = flatten_directory(src, name_by_path) if flatten else src

    # loop: create zip, check size, prune if needed
    while True:
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(working):
                rp = Path(root)
                # prune dirs in-place
                dirs[:] = [
                    d for d in dirs
                    if not should_exclude(rp / d, exclude_dirs, exclude_exts, exclude_files)
                ]
                for fn in files:
                    fp = rp / fn
                    if should_exclude(fp, exclude_dirs, exclude_exts, exclude_files):
                        continue
                    if matches_patterns(fp, remove_patterns) and not matches_patterns(fp, keep_patterns):
                        continue
                    arc = fp.relative_to(working)
                    zf.write(fp, arc)
                    if verbose:
                        print(f"Added: {arc}")

        size_mb = out.stat().st_size / (1024 * 1024)
        if max_size is None or size_mb <= max_size:
            print(f"\nFinal zip file size: {size_mb:.2f} MB")
            break

        print(f"Zip file too large ({size_mb:.2f} MB > {max_size} MB). Pruning...")
        delete_files_to_fit_size(working, max_size, preferences)

def text_file_mode(source_dir: str,
                   output_file: str,
                   exclude_dirs: set[str],
                   exclude_exts: set[str],
                   exclude_files: set[str],
                   remove_patterns: list[str],
                   keep_patterns: list[str],
                   flatten: bool,
                   name_by_path: bool,
                   verbose: bool) -> None:
    """
    Creates a single text file containing:
      - Folder hierarchy
      - Each file's contents under `-- File: path --`
      - Prints stats: hierarchy printed, files processed, files added
      - In verbose mode: lists skipped files
    """
    src = Path(source_dir).resolve()
    if flatten:
        src = flatten_directory(src, name_by_path)

    total = 0
    added: list[str] = []
    skipped: list[str] = []

    with open(output_file, 'w', encoding='utf-8') as out:
        # hierarchy
        out.write("Folder Structure\n")
        for root, dirs, _ in os.walk(src):
            rel = Path(root).relative_to(src)
            indent = '    ' * len(rel.parts)
            name = rel.name if rel.parts else src.name
            out.write(f"{indent}{name}/\n")

        # files
        for root, _, files in os.walk(src):
            for fn in files:
                total += 1
                fp = Path(root) / fn
                rel = fp.relative_to(src)

                if should_exclude(fp, exclude_dirs, exclude_exts, exclude_files) \
                   or (matches_patterns(fp, remove_patterns) and not matches_patterns(fp, keep_patterns)):
                    skipped.append(str(rel))
                    continue

                out.write(f"\n-- File: {rel} --\n")
                try:
                    out.write(fp.read_text() + "\n")
                except Exception:
                    skipped.append(str(rel))
                    if verbose:
                        print(f"Could not read: {rel}")
                    continue

                added.append(str(rel))

    # stats
    print("Hierarchy printed:")
    print(f"Files processed: {total}")
    print("Files added:")
    for f in added:
        print(f)
    if verbose and skipped:
        print("Skipped files:")
        for f in skipped:
            print(f)
    print(f"Created text file: {output_file}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Package a folder for LLMs (zip or text mode)"
    )
    parser.add_argument("-s", "--source",     required=True, help="Folder to process")
    parser.add_argument("-o", "--output",     required=True, help="Output path (zip or txt)")
    parser.add_argument(
        "-F", "--file-mode",
        action="store_true",
        help="Produce one big text file instead of a zip"
    )
    parser.add_argument(
        "-xd", "--exclude-dir",
        nargs="*", default=list(DEFAULT_EXCLUDE_DIRS),
        help="Directories to exclude"
    )
    parser.add_argument(
        "-xe", "--exclude-ext",
        nargs="*", default=list(DEFAULT_EXCLUDE_EXTS),
        help="File extensions to exclude"
    )
    parser.add_argument(
        "-xf", "--exclude-file",
        nargs="*", default=list(DEFAULT_EXCLUDE_FILES),
        help="Specific filenames to exclude"
    )
    parser.add_argument(
        "-if", "--include-file",
        nargs="*", default=[],
        help="Force-include specific files"
    )
    parser.add_argument(
        "-r", "--remove-patterns",
        nargs="*", default=[],
        help="Glob patterns to remove"
    )
    parser.add_argument(
        "-k", "--keep-patterns",
        nargs="*", default=[],
        help="Glob patterns to keep"
    )
    parser.add_argument(
        "-ms", "--max-size",
        type=int, help="Maximum zip size in MB"
    )
    parser.add_argument(
        "-p", "--preferences",
        nargs="*", default=[],
        help="Extensions prioritized for deletion"
    )
    parser.add_argument(
        "-f", "--flatten",
        action="store_true",
        help="Flatten directory before packaging"
    )
    parser.add_argument(
        "-np", "--name-by-path",
        action="store_true",
        help="When flattening, include path in filename"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output"
    )

    args = parser.parse_args()

    exclude_dirs  = set(args.exclude_dir)
    exclude_exts  = set(args.exclude_ext)
    exclude_files = set(args.exclude_file) - set(args.include_file)

    if args.file_mode:
        text_file_mode(
            args.source, args.output,
            exclude_dirs, exclude_exts, exclude_files,
            args.remove_patterns, args.keep_patterns,
            args.flatten, args.name_by_path, args.verbose
        )
    else:
        zip_folder(
            args.source, args.output,
            exclude_dirs, exclude_exts, exclude_files,
            args.remove_patterns, args.keep_patterns,
            args.max_size, args.preferences,
            args.flatten, args.name_by_path, args.verbose
        )
