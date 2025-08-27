# File: scripts/pyscripts/zip_for_llms.py
#!/usr/bin/env python3
import os
import zipfile
import argparse
import fnmatch
import shutil
from pathlib import Path
import time
from typing import Iterable

try:
    from rich.console import Console
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

# Fallback basic print if rich is not available
if RICH_AVAILABLE:
    console = Console()
    def rprint(*args, **kwargs):
        return console.print(*args, **kwargs)
else:
    def rprint(*args, **kwargs):
        if 'style' in kwargs:
            kwargs.pop('style', None)
        print(*args, **kwargs)

# ===============================
# Default ignore sets (repo-agnostic)
# ===============================
# Common VCS / editors / caches / vendored deps
DEFAULT_EXCLUDE_DIRS = {
    ".git", ".hg", ".svn",
    "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".ipynb_checkpoints", ".cache", ".gradle", ".idea", ".vscode",
    "node_modules", "bower_components",
    # Python & build
    ".venv", "venv", "env", ".tox", ".nox", "build", "dist", "htmlcov",
    # Java/Scala/Go build outputs
    "target", "out", "bazel-bin", "bazel-out", "bazel-testlogs",
    "bin", "obj",
}

# Extensions typically unhelpful for LLM code understanding (kept conservative)
DEFAULT_EXCLUDE_EXTS = {
    # Python/compiled
    ".pyc", ".pyo", ".pyd",
    # Native/binaries & objects
    ".exe", ".dll", ".bin", ".o", ".so", ".dylib", ".a", ".lib", ".obj", ".pdb",
    # Archives
    ".zip", ".tar", ".gz", ".tgz", ".7z", ".bz2", ".xz", ".rar",
    # Temp & swap & logs
    ".tmp", ".bak", ".swp", ".swo", ".log",
}

# Files commonly large/noisy for understanding
DEFAULT_EXCLUDE_FILES = {
    # Lock files (often huge/noisy and not needed to understand structure)
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "Pipfile.lock", "poetry.lock",
    # Platform cruft
    ".DS_Store", "Thumbs.db", "desktop.ini",
    # Coverage/dbs
    ".coverage", ".coverage.sqlite",
}

# Language presets extend defaults
PRESETS = {
    "python": {
        "dirs": {".venv", ".tox", ".nox", "build", "dist", "htmlcov"},
        "patterns": ["*.egg-info", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"],
        "exts": {".pyd"},
        "files": {".coverage", ".coverage.sqlite"},
    }
}

# ===============================
# Helpers
# ===============================
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
    """Basic excludes by exact name/extension/file name."""
    if path.is_dir():
        return path.name in exclude_dirs
    return (
        (path.suffix in exclude_exts) or
        (path.name in exclude_files)
    )

def matches_patterns(name_or_path: str, patterns: Iterable[str]) -> bool:
    """Glob match against provided patterns."""
    return any(fnmatch.fnmatch(name_or_path, pat) for pat in patterns)

def should_exclude_dir_advanced(dir_name: str,
                                rel_path_posix: str,
                                exclude_specs: Iterable[str]) -> bool:
    """
    Directory exclusion that supports:
      - Exact directory name (e.g., "__pycache__")
      - Path fragment (substring) match (e.g., "scripts/__pycache__")
      - Glob match on name or relative path (e.g., "analysistmp*", "**/__pycache__")
    """
    for spec in exclude_specs:
        spec_clean = spec.strip("/")

        # Exact name match
        if dir_name == spec_clean:
            return True

        # Substring fragment (path contains spec)
        if spec_clean and spec_clean in rel_path_posix:
            return True

        # Glob match against name and full relative path
        if fnmatch.fnmatch(dir_name, spec_clean) or fnmatch.fnmatch(rel_path_posix, spec_clean):
            return True

    return False

def flatten_directory(source_dir: Path, name_by_path: bool, verbose: bool) -> Path:
    source_dir = source_dir.resolve()
    flat_dir_name = "_flattened"
    flat_dest_path = source_dir / flat_dir_name
    flat_dest_path.mkdir(exist_ok=True)
    moved_count = 0

    if verbose:
        rprint(f"Flattening directory [cyan]{source_dir.name}[/cyan] into [cyan]{flat_dest_path.name}[/cyan]...")

    for root, dirs, files in os.walk(source_dir, topdown=True):
        root_path = Path(root)

        if root_path == flat_dest_path:
            dirs[:] = []
            continue

        # Simple default excludes for traversal speed
        dirs[:] = [d for d in dirs if d not in DEFAULT_EXCLUDE_DIRS and d != flat_dir_name]

        if root_path.name in DEFAULT_EXCLUDE_DIRS and root_path != source_dir:
            continue

        for fn in files:
            original_file_path = root_path / fn

            if should_exclude(original_file_path, set(), DEFAULT_EXCLUDE_EXTS, DEFAULT_EXCLUDE_FILES):
                if verbose:
                    rel = original_file_path.relative_to(source_dir)
                    rprint(f"  [dim yellow]Skipping (default rule):[/dim yellow] {rel}")
                continue

            if original_file_path.parent == flat_dest_path:
                continue

            if name_by_path:
                try:
                    relative_path_from_source = original_file_path.relative_to(source_dir)
                    new_name = "_".join(relative_path_from_source.parts)
                except ValueError:
                    new_name = fn
            else:
                new_name = fn

            destination_file_path_in_flat = flat_dest_path / new_name

            if destination_file_path_in_flat != original_file_path:
                shutil.move(str(original_file_path), str(destination_file_path_in_flat))
                moved_count += 1

    rprint(f"[green]Flattened {moved_count} files into {flat_dest_path}.[green]")
    return flat_dest_path

def delete_files_to_fit_size(directory_to_prune: Path,
                             target_zip_size_mb: int,
                             preferences: list[str],
                             verbose: bool) -> list[str]:
    target_dir_bytes = target_zip_size_mb * 1024 * 1024
    current_dir_size = get_directory_size(directory_to_prune)

    if current_dir_size <= target_dir_bytes:
        if verbose:
            rprint(f"Directory '{directory_to_prune}' size ({current_dir_size/(1024*1024):.2f}MB) is already below/near heuristic target ({target_zip_size_mb}MB). No files deleted by pruning logic itself.", style="dim")
        return []

    if verbose:
        rprint(f"Attempting to reduce source directory [cyan]'{directory_to_prune.name}'[/cyan] size... Current: {current_dir_size/(1024*1024):.2f} MB. Heuristic target: {target_zip_size_mb} MB")

    all_files_in_dir = sorted(
        (f for f in directory_to_prune.rglob('*') if f.is_file()),
        key=lambda f: f.stat().st_size,
        reverse=True
    )

    ordered_files_for_deletion: list[Path] = []
    for pref_ext in preferences:
        ordered_files_for_deletion.extend([f for f in all_files_in_dir if f.suffix == pref_ext and f not in ordered_files_for_deletion])
    ordered_files_for_deletion.extend([f for f in all_files_in_dir if f not in ordered_files_for_deletion])

    removed_paths = []
    if verbose and ordered_files_for_deletion:
        rprint("  [bold yellow]Pruning files:[/bold yellow]")

    for file_to_delete in ordered_files_for_deletion:
        if current_dir_size <= target_dir_bytes:
            break
        try:
            file_size = file_to_delete.stat().st_size
            file_to_delete.unlink()
            removed_paths.append(str(file_to_delete))
            current_dir_size -= file_size
            if verbose:
                rprint(f"    - [red]Pruned:[/red] {file_to_delete.name} ({file_size/(1024*1024):.2f}MB). Source dir size now: {current_dir_size/(1024*1024):.2f}MB")
        except OSError as e:
            rprint(f"  [yellow]Warning:[/yellow] Could not delete file {file_to_delete} during pruning: {e}")

    if current_dir_size <= target_dir_bytes:
        if verbose:
            rprint(f"  [green]Pruned {len(removed_paths)} files.[/green] Final source dir size for '{directory_to_prune.name}': {current_dir_size/(1024*1024):.2f} MB.")
    else:
        if verbose:
            rprint(f"  [yellow]Warning:[/yellow] After pruning {len(removed_paths)} files, source dir size for '{directory_to_prune.name}' ({current_dir_size/(1024*1024):.2f}MB) may still be too large for heuristic target ({target_zip_size_mb}MB).")
    return removed_paths

# ===============================
# Core operations
# ===============================
def zip_folder(source_dir_str: str,
               output_zip_str: str,
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
    src_path = Path(source_dir_str).resolve()
    output_zip_path = Path(output_zip_str).resolve()

    temp_source_copy_for_pruning: Path | None = None
    temp_dir_to_flatten_base: Path | None = None

    if flatten:
        temp_dir_to_flatten_base = src_path.parent / f"_temp_to_flatten_{src_path.name}_{int(time.time())}"
        shutil.copytree(src_path, temp_dir_to_flatten_base, dirs_exist_ok=True)
        working_dir_for_zip = flatten_directory(temp_dir_to_flatten_base, name_by_path, verbose)
        if verbose:
            rprint(f"Flatten mode: Zipping from temporary flattened directory: [cyan]{working_dir_for_zip}[/cyan]")
    elif not flatten and max_size is not None:
        temp_source_copy_for_pruning = src_path.parent / f"_temp_zip_src_{src_path.name}_{int(time.time())}"
        if verbose:
            rprint(f"Max size set and not flattening. Using temp copy for zipping: [cyan]{temp_source_copy_for_pruning}[/cyan]")
        shutil.copytree(src_path, temp_source_copy_for_pruning, dirs_exist_ok=True)
        working_dir_for_zip = temp_source_copy_for_pruning
    else:
        working_dir_for_zip = src_path

    if not working_dir_for_zip.exists():
        rprint(f"[red]Error:[/red] Working directory '{working_dir_for_zip}' does not exist. Aborting zip.")
        if temp_dir_to_flatten_base and temp_dir_to_flatten_base.exists():
            shutil.rmtree(temp_dir_to_flatten_base)
        if temp_source_copy_for_pruning and temp_source_copy_for_pruning.exists():
            shutil.rmtree(temp_source_copy_for_pruning)
        return

    # Write structure of ORIGINAL src_path (not flattened) to help navigation
    hierarchy_file_path = working_dir_for_zip / "folder_structure.txt"
    with open(hierarchy_file_path, 'w', encoding='utf-8') as f:
        f.write(f"Folder Structure for: {src_path.name}\n")
        paths_for_structure = []
        for root, dirs, _ in os.walk(src_path, topdown=True):
            current_root_path = Path(root)
            pruned = []
            for d_name in dirs:
                candidate_rel = (current_root_path / d_name)
                try:
                    rel_posix = candidate_rel.relative_to(src_path).as_posix()
                except ValueError:
                    rel_posix = d_name
                if should_exclude_dir_advanced(d_name, rel_posix, exclude_dirs) or (
                    matches_patterns(d_name, remove_patterns) and not matches_patterns(d_name, keep_patterns)
                ):
                    continue
                pruned.append(d_name)
            dirs[:] = pruned

            relative_path = current_root_path.relative_to(src_path)
            indent_level = len(relative_path.parts)
            indent = '    ' * indent_level
            dir_name_display = current_root_path.name if current_root_path != src_path else src_path.name
            paths_for_structure.append(f"{indent}{dir_name_display}/\n")
        for line in paths_for_structure:
            f.write(line)
    if verbose:
        rprint(f"Generated [magenta]folder_structure.txt[/magenta] at [cyan]{hierarchy_file_path}[/cyan]")

    while True:
        zip_file_count = 0
        output_zip_path.parent.mkdir(parents=True, exist_ok=True)

        if verbose:
            rprint(f"\n[bold blue]Processing files for zip '{output_zip_path.name}':[/bold blue]")

        with zipfile.ZipFile(output_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files_in_dir in os.walk(working_dir_for_zip, topdown=True):
                current_root_path_in_working = Path(root)

                pruned = []
                for d_name in dirs:
                    candidate_rel = (current_root_path_in_working / d_name)
                    try:
                        rel_posix = candidate_rel.relative_to(working_dir_for_zip).as_posix()
                    except ValueError:
                        rel_posix = d_name
                    if should_exclude_dir_advanced(d_name, rel_posix, exclude_dirs) or (
                        matches_patterns(d_name, remove_patterns) and not matches_patterns(d_name, keep_patterns)
                    ):
                        continue
                    pruned.append(d_name)
                dirs[:] = pruned

                for filename in files_in_dir:
                    file_path_in_working = current_root_path_in_working / filename
                    relative_display_path = file_path_in_working.relative_to(working_dir_for_zip)

                    if should_exclude(file_path_in_working, set(), exclude_exts, exclude_files):
                        if verbose:
                            rprint(f"  - [yellow]Skipping (default rule):[/yellow] {relative_display_path}")
                        continue

                    if matches_patterns(filename, remove_patterns) and not matches_patterns(filename, keep_patterns):
                        if verbose:
                            rprint(f"  - [yellow]Skipping (pattern rule on '{filename}'):[/yellow] {relative_display_path}")
                        continue

                    archive_name = relative_display_path
                    zf.write(file_path_in_working, archive_name)
                    zip_file_count += 1
                    if verbose:
                        rprint(f"  + [green]Added to zip:[/green] {archive_name}")

        if verbose:
            rprint(f"Total files added to current zip iteration: {zip_file_count}")

        current_zip_size_bytes = output_zip_path.stat().st_size
        current_zip_size_mb = current_zip_size_bytes / (1024 * 1024)

        if max_size is None or current_zip_size_mb <= max_size:
            rprint(f"\n[bold green]Final zip file '{output_zip_path.name}' size: {current_zip_size_mb:.2f} MB[/bold green]")
            break

        if verbose:
            rprint(f"\n[bold yellow]Zip file is too large ({current_zip_size_mb:.2f} MB > {max_size} MB).[/bold yellow] Pruning files from [cyan]'{working_dir_for_zip.name}'[/cyan]...")

        deleted_files = delete_files_to_fit_size(working_dir_for_zip, max_size, preferences, verbose)

        if not deleted_files:
            rprint(f"[yellow]Warning:[/yellow] No files were deleted from '{working_dir_for_zip.name}' during pruning, but zip is still too large ({current_zip_size_mb:.2f} MB > {max_size} MB). "
                  "The zip might exceed max_size if no more files can be pruned or preferences don't match. Check file sizes and compressibility.")
            break

    if temp_source_copy_for_pruning and temp_source_copy_for_pruning.exists():
        if verbose: rprint(f"Cleaning up temporary source copy for zipping: [cyan]{temp_source_copy_for_pruning}[/cyan]", style="dim")
        shutil.rmtree(temp_source_copy_for_pruning)
    if temp_dir_to_flatten_base and temp_dir_to_flatten_base.exists():
        if verbose: rprint(f"Cleaning up temporary flattened structure for zipping: [cyan]{temp_dir_to_flatten_base}[/cyan]", style="dim")
        shutil.rmtree(temp_dir_to_flatten_base)

def text_file_mode(source_dir_str: str,
                   output_file_str: str,
                   exclude_dirs: set[str],
                   exclude_exts: set[str],
                   exclude_files: set[str],
                   remove_patterns: list[str],
                   keep_patterns: list[str],
                   flatten_mode: bool,
                   name_by_path: bool,
                   verbose: bool) -> None:
    src_path = Path(source_dir_str).resolve()
    output_file_path = Path(output_file_str).resolve()

    temp_flatten_root_for_text: Path | None = None
    working_dir_for_text = src_path

    if flatten_mode:
        temp_flatten_root_for_text = src_path.parent / f"_temp_text_flatten_base_{src_path.name}_{int(time.time())}"
        shutil.copytree(src_path, temp_flatten_root_for_text, dirs_exist_ok=True)
        working_dir_for_text = flatten_directory(temp_flatten_root_for_text, name_by_path, verbose)
        if verbose:
            rprint(f"Text mode: Using temporary flattened content from: [cyan]{working_dir_for_text}[/cyan]")

    files_processed_count = 0
    files_added_to_text_count = 0
    files_skipped_list: list[str] = []
    paths_for_hierarchy_display: list[str] = []

    output_file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file_path, 'w', encoding='utf-8') as out_f:
        # LLM preamble (kept minimal so tests remain stable)
        out_f.write(
            "This document packages a repository for a Large Language Model (LLM).\n"
            "It contains a high-level folder structure followed by concatenated file contents.\n"
            "Use the structure to locate files; each file section starts with a marker like:\n"
            "-- File: relative/path/to/file --\n\n"
        )

        rprint(f"[bold blue]Generating folder structure for text output...[/bold blue]")
        out_f.write(f"Folder Structure for: {src_path.name}\n")
        for root, dirs, _ in os.walk(src_path, topdown=True):
            current_root_path = Path(root)

            pruned = []
            for d_name in dirs:
                candidate_rel = (current_root_path / d_name)
                try:
                    rel_posix = candidate_rel.relative_to(src_path).as_posix()
                except ValueError:
                    rel_posix = d_name
                if should_exclude_dir_advanced(d_name, rel_posix, exclude_dirs) or (
                    matches_patterns(d_name, remove_patterns) and not matches_patterns(d_name, keep_patterns)
                ):
                    continue
                pruned.append(d_name)
            dirs[:] = pruned

            relative_path = current_root_path.relative_to(src_path)
            indent_level = len(relative_path.parts)
            indent = '    ' * indent_level
            dir_name_display = current_root_path.name if current_root_path != src_path else src_path.name
            paths_for_hierarchy_display.append(f"{indent}{dir_name_display}/\n")
        for line in paths_for_hierarchy_display:
            out_f.write(line)
        out_f.write("\n--- End of Folder Structure ---\n")

        if verbose:
            rprint("Folder structure written to text file.")
            rprint(f"\n[bold blue]Processing files for text output '{output_file_path.name}':[/bold blue]")

        for root, dirs, files_in_dir in os.walk(working_dir_for_text, topdown=True):
            current_root_path_in_working = Path(root)

            pruned = []
            for d_name in dirs:
                candidate_rel = (current_root_path_in_working / d_name)
                try:
                    rel_posix = candidate_rel.relative_to(working_dir_for_text).as_posix()
                except ValueError:
                    rel_posix = d_name
                if should_exclude_dir_advanced(d_name, rel_posix, exclude_dirs) or (
                    matches_patterns(d_name, remove_patterns) and not matches_patterns(d_name, keep_patterns)
                ):
                    continue
                pruned.append(d_name)
            dirs[:] = pruned

            for filename in files_in_dir:
                files_processed_count += 1
                file_path_in_working = current_root_path_in_working / filename

                if flatten_mode:
                    rel_path_for_display_str = filename
                else:
                    try:
                        rel_path_for_display_str = str(file_path_in_working.relative_to(src_path))
                    except ValueError:
                        rel_path_for_display_str = filename

                if should_exclude(file_path_in_working, set(), exclude_exts, exclude_files):
                    skip_msg = f"{rel_path_for_display_str} (excluded by dir/ext/file rule on '{file_path_in_working.name}')"
                    files_skipped_list.append(skip_msg)
                    if verbose:
                        rprint(f"  - [yellow]Skipping (default rule):[/yellow] {skip_msg}")
                    continue
                if matches_patterns(filename, remove_patterns) and not matches_patterns(filename, keep_patterns):
                    skip_msg = f"{rel_path_for_display_str} (pattern on name '{filename}')"
                    files_skipped_list.append(skip_msg)
                    if verbose:
                        rprint(f"  - [yellow]Skipping (pattern rule):[/yellow] {skip_msg}")
                    continue

                out_f.write(f"\n-- File: {rel_path_for_display_str} --\n")
                try:
                    content = file_path_in_working.read_text(encoding='utf-8')
                    out_f.write(content)
                    if not content.endswith('\n'):
                        out_f.write('\n')
                    files_added_to_text_count += 1
                    if verbose:
                        rprint(f"  + [green]Added to text:[/green] {rel_path_for_display_str}")
                except UnicodeDecodeError:
                    skip_msg = f"{rel_path_for_display_str} (binary or non-UTF-8 content)"
                    files_skipped_list.append(skip_msg)
                    if verbose:
                        rprint(f"  - [yellow]Skipping (read error):[/yellow] {skip_msg}")
                except Exception as e:
                    skip_msg = f"{rel_path_for_display_str} (read error: {e})"
                    files_skipped_list.append(skip_msg)
                    if verbose:
                        rprint(f"  - [yellow]Skipping (read error):[/yellow] {skip_msg}")

    if temp_flatten_root_for_text and temp_flatten_root_for_text.exists():
        try:
            shutil.rmtree(temp_flatten_root_for_text)
            if verbose:
                rprint(f"Cleaned up temporary flatten base for text mode: [cyan]{temp_flatten_root_for_text}[/cyan]", style="dim")
        except OSError as e:
            rprint(f"[yellow]Warning:[/yellow] Could not clean up temporary directory {temp_flatten_root_for_text}: {e}")

    rprint(f"\n[bold green]Text file generation complete: {output_file_path.name}[/bold green]")
    rprint(f"Total files encountered in content source: {files_processed_count}")
    rprint(f"Files added to text output: {files_added_to_text_count}")
    if files_skipped_list:
        rprint(f"Files skipped from content: {len(files_skipped_list)}")
        if verbose:
            rprint("  [bold yellow]Skipped file details:[/bold yellow]")
            for f_skipped in files_skipped_list:
                rprint(f"    - {f_skipped}")

# ===============================
# CLI
# ===============================
if __name__ == "__main__":
    if not RICH_AVAILABLE:
        print("Warning: 'rich' library not found. Output will be basic.")
        print("Consider installing it with: pip install rich\n")

    parser = argparse.ArgumentParser(
        description="Package a folder for LLMs (zip and/or text file mode)."
    )
    parser.add_argument("-s", "--source", required=True, help="Folder to process")
    parser.add_argument("-o", "--output", required=True, help="Base output path (e.g., 'myarchive' or 'myarchive.zip')")

    mode_group = parser.add_argument_group(title="Output Modes")
    mode_group.add_argument("-F", "--file-mode", action="store_true", help="Produce one consolidated text file.")
    mode_group.add_argument("-Z", "--zip-mode", action="store_true", help="Produce a zip file. (Default if no mode is specified)")

    filter_group = parser.add_argument_group(title="Filtering and Exclusion")
    # Keep old flags for compatibility; add intuitive aliases
    filter_group.add_argument("-xd", "-D", "--exclude-dir", nargs="*", default=list(DEFAULT_EXCLUDE_DIRS),
                              help="Directory EXCLUDE specs (name, path fragment, or glob). Multiple allowed.")
    filter_group.add_argument("-xe", "-E", "--exclude-ext", nargs="*", default=list(DEFAULT_EXCLUDE_EXTS),
                              help="File extensions to exclude (e.g., .log .tmp). Multiple allowed.")
    filter_group.add_argument("-xf", "-X", "--exclude-file", nargs="*", default=list(DEFAULT_EXCLUDE_FILES),
                              help="Specific filenames to exclude. Multiple allowed.")
    filter_group.add_argument("-if", "-I", "--include-file", nargs="*", default=[],
                              help="Force-include specific files (overrides -X/--exclude-file if names match).")
    filter_group.add_argument("-r", "-R", "--remove-patterns", nargs="*", default=[],
                              help="Glob patterns for filenames/dirnames to remove. Matched against names.")
    filter_group.add_argument("-k", "-K", "--keep-patterns", nargs="*", default=[],
                              help="Glob patterns for filenames/dirnames to keep (overrides remove-patterns).")
    filter_group.add_argument("-P", "--preset", choices=PRESETS.keys(),
                              help="Use a preset for language-specific defaults (e.g., 'python').")

    zip_options_group = parser.add_argument_group(title="Zip Mode Options")
    zip_options_group.add_argument("-ms", "-m", "--max-size", type=int,
                                   help="Maximum zip file size in MB. If exceeded, files are pruned from source/flattened copy.")
    zip_options_group.add_argument("-p", "--preferences", nargs="*", default=[],
                                   help="Preferred file extensions for deletion if zip exceeds max-size.")

    format_group = parser.add_argument_group(title="Formatting Options")
    format_group.add_argument("-f", "--flatten", action="store_true",
                              help="Flatten directory structure before packaging.")
    format_group.add_argument("-np", "-n", "--name-by-path", action="store_true",
                              help="When flattening, rename files to include their original relative path.")

    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose output.")

    args = parser.parse_args()

    run_file_mode = args.file_mode
    run_zip_mode = args.zip_mode
    if not run_file_mode and not run_zip_mode:
        run_zip_mode = True

    # --- Apply presets and finalize exclusion/removal lists ---
    final_exclude_files = set(args.exclude_file) - set(args.include_file)
    final_exclude_dirs = set(args.exclude_dir)
    final_exclude_exts = set(args.exclude_ext)
    final_remove_patterns = list(args.remove_patterns)

    if args.preset:
        preset = PRESETS[args.preset]
        final_exclude_dirs.update(preset.get("dirs", set()))
        final_exclude_exts.update(preset.get("exts", set()))
        final_exclude_files.update(preset.get("files", set()))
        final_remove_patterns.extend(preset.get("patterns", []))
        if args.verbose:
            rprint(f"[bold cyan]Applied preset '{args.preset}'[/bold cyan]")

    output_path_arg = Path(args.output)
    output_dir = output_path_arg.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    if output_path_arg.name.startswith('.') and not output_path_arg.stem.startswith('.'):
        base_name_for_output = output_path_arg.name
    else:
        base_name_for_output = output_path_arg.stem if output_path_arg.stem else output_path_arg.name

    actual_text_output_path: Path | None = None
    actual_zip_output_path: Path | None = None

    if run_file_mode and run_zip_mode:
        original_suffix = output_path_arg.suffix.lower()
        if original_suffix == ".txt":
            actual_text_output_path = output_path_arg
            actual_zip_output_path = output_dir / (base_name_for_output + ".zip")
        elif original_suffix == ".zip":
            actual_zip_output_path = output_path_arg
            actual_text_output_path = output_dir / (base_name_for_output + ".txt")
        else:
            if original_suffix:
                rprint(f"[yellow]Warning:[/yellow] Output path '{args.output}' has an unrecognized extension ('{original_suffix}') for combined mode. "
                       f"Using '{base_name_for_output}.txt' and '{base_name_for_output}.zip'.")
            actual_text_output_path = output_dir / (base_name_for_output + ".txt")
            actual_zip_output_path = output_dir / (base_name_for_output + ".zip")
    elif run_file_mode:
        if output_path_arg.suffix.lower() == ".txt":
            actual_text_output_path = output_path_arg
        else:
            if output_path_arg.suffix:
                rprint(f"[yellow]Warning:[/yellow] Output path '{args.output}' has suffix '{output_path_arg.suffix}'. "
                       f"File mode is active, final output will be '{base_name_for_output}.txt'.")
            actual_text_output_path = output_dir / (base_name_for_output + ".txt")
    elif run_zip_mode:
        if output_path_arg.suffix.lower() == ".zip":
            actual_zip_output_path = output_path_arg
        else:
            if output_path_arg.suffix:
                rprint(f"[yellow]Warning:[/yellow] Output path '{args.output}' has suffix '{output_path_arg.suffix}'. "
                       f"Zip mode is active, final output will be '{base_name_for_output}.zip'.")
            actual_zip_output_path = output_dir / (base_name_for_output + ".zip")

    if actual_text_output_path:
        rprint(f"[bold magenta]Starting text file mode.[/bold magenta] Output to: [cyan]{actual_text_output_path}[/cyan]")
        text_file_mode(
            args.source, str(actual_text_output_path),
            final_exclude_dirs, final_exclude_exts, final_exclude_files,
            final_remove_patterns, args.keep_patterns,
            args.flatten, args.name_by_path, args.verbose
        )

    if actual_zip_output_path:
        rprint(f"[bold magenta]Starting zip mode.[/bold magenta] Output to: [cyan]{actual_zip_output_path}[/cyan]")
        zip_folder(
            args.source, str(actual_zip_output_path),
            final_exclude_dirs, final_exclude_exts, final_exclude_files,
            final_remove_patterns, args.keep_patterns,
            args.max_size, args.preferences,
            args.flatten, args.name_by_path, args.verbose
        )
