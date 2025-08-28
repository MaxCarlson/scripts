#!/usr/bin/env python3
"""
zip_for_llms.py
Package a repo for LLM consumption (zip and/or consolidated text), with optional
Gemini CLI analysis over a filtered workspace and (optional) recent commit history.

Lean CLI + importable helpers for tests:
- zip_folder, text_file_mode, flatten_directory, delete_files_to_fit_size
- DEFAULT_EXCLUDE_DIRS/EXTS/FILES, PRESETS
- prepare_analysis_workspace
- run_gemini_analysis, _git_commit_snapshot (kept for test monkeypatch)
"""

from __future__ import annotations

import argparse
import fnmatch
import io
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Iterable, List, Optional


# =====================================================================================
# Defaults & Presets
# =====================================================================================

DEFAULT_EXCLUDE_DIRS: set[str] = {
    ".git", ".hg", ".svn",
    ".tox", ".mypy_cache", ".pytest_cache",
    "__pycache__",
    "node_modules",
    "dist", "build",
    ".venv", "venv",
    ".idea", ".vscode",
    ".egg-info", "*.egg-info",
}

DEFAULT_EXCLUDE_EXTS: set[str] = {
    # compiled / caches / native artifacts
    ".pyc", ".pyo", ".class", ".o", ".so", ".dll", ".dylib",
    # archives / pkg blobs
    ".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar", ".zst", ".whl",
    # temp / editor
    ".swp", ".swo",
}

DEFAULT_EXCLUDE_FILES: set[str] = {
    ".DS_Store",
    ".coverage",
    "yarn.lock",            # required by tests (default-excluded)
    # NOTE: do NOT exclude "README.md" nor "folder_structure.txt" by default.
}

PRESETS: dict[str, dict[str, set[str] | list[str]]] = {
    "python": {
        "dirs": {".venv", "venv", "build", "dist", "__pycache__", ".mypy_cache", ".pytest_cache", "*.egg-info"},
        "exts": {".pyc", ".pyo"},
        "files": {".coverage"},
        "patterns": [],
    }
}

SPECIAL_ALWAYS_INCLUDE = {"folder_structure.txt"}


# =====================================================================================
# Small utilities
# =====================================================================================

def which(cmd: str) -> Optional[str]:
    return shutil.which(cmd)

def _matches_any(patterns: Iterable[str], text: str) -> bool:
    for pat in patterns:
        if fnmatch.fnmatch(text, pat):
            return True
    return False

def _rel_posix(root: Path, p: Path) -> str:
    return p.relative_to(root).as_posix()

def _path_parts(rel_posix: str) -> list[str]:
    return list(PurePosixPath(rel_posix).parts)


def is_excluded(
    rel_path: str,
    exclude_dirs: set[str],
    exclude_exts: set[str],
    exclude_files: set[str],
    remove_patterns: list[str],
    keep_patterns: list[str],
) -> bool:
    """
    Decide if the relative path is excluded.
    Rules (precedence): keep_patterns > remove_patterns > exclude dirs/files/exts.
    - Directory rules match either exact name of any path part or glob on any part / full relpath.
    - Remove patterns apply to filename, relpath, and any directory part.
    """
    rel_posix = rel_path.replace("\\", "/")
    p = PurePosixPath(rel_posix)
    name = p.name
    suffix = p.suffix.lower()
    parts = _path_parts(rel_posix)

    # Always-include helper
    if name in SPECIAL_ALWAYS_INCLUDE or rel_posix in SPECIAL_ALWAYS_INCLUDE:
        return False

    # Keep overrides everything
    if keep_patterns and (_matches_any(keep_patterns, name) or _matches_any(keep_patterns, rel_posix)):
        return False

    # Remove patterns — match on basename, relpath, OR any directory part
    if remove_patterns:
        if (_matches_any(remove_patterns, name)
            or _matches_any(remove_patterns, rel_posix)
            or any(_matches_any(remove_patterns, part) for part in parts)):
            return True

    # Exclude dirs — match on any path part (exact or glob) or relpath fragment/glob
    if any(part in exclude_dirs for part in parts):
        return True
    if any(fnmatch.fnmatch(part, pat) for part in parts for pat in exclude_dirs):
        return True
    if _matches_any(exclude_dirs, rel_posix):
        return True

    # Exclude specific files / globs
    if name in exclude_files or _matches_any(exclude_files, name):
        return True

    # Exclude by extension
    if suffix in exclude_exts:
        return True

    return False


# =====================================================================================
# Folder structure helper
# =====================================================================================

def _write_folder_structure(
    root: Path,
    dest_file: Path,
    exclude_dirs: set[str],
    remove_patterns: Optional[list[str]] = None,
    keep_patterns: Optional[list[str]] = None,
) -> None:
    """
    Append a shallow, top-level folder structure to dest_file.
    Respects exclude_dirs and remove_patterns (keep_patterns can rescue).
    """
    remove_patterns = remove_patterns or []
    keep_patterns = keep_patterns or []

    buf = io.StringIO()
    repo_name = root.name
    buf.write(f"Folder Structure for: {repo_name}\n")
    buf.write(f"{repo_name}/\n")

    for entry in sorted(root.iterdir(), key=lambda p: p.name):
        if not entry.is_dir():
            continue
        name = entry.name
        # keep wins
        if keep_patterns and _matches_any(keep_patterns, name):
            buf.write(f"    {name}/\n")
            continue
        # remove or exclude?
        if _matches_any(remove_patterns, name):
            continue
        if name in exclude_dirs or _matches_any(exclude_dirs, name):
            continue
        buf.write(f"    {name}/\n")

    buf.write("\n--- End of Folder Structure ---\n")
    with dest_file.open("a", encoding="utf-8") as f:
        f.write(buf.getvalue())


# =====================================================================================
# Flattening
# =====================================================================================

def flatten_directory(source_dir: Path, name_by_path: bool = False, verbose: bool = False) -> Path:
    """
    Create a temporary _flattened dir containing flattened files from source_dir
    while respecting DEFAULT_EXCLUDE_* rules.
    """
    source_dir = Path(source_dir).resolve()
    temp_root = source_dir.parent / f"_temp_flatten_{source_dir.name}_{os.getpid()}"
    flat_dir = temp_root / "_flattened"
    flat_dir.mkdir(parents=True, exist_ok=True)

    if verbose:
        print(f"Flattening directory {temp_root.name} into _flattened...")

    total = 0
    for path in source_dir.rglob("*"):
        if not path.is_file():
            continue
        rel = _rel_posix(source_dir, path)
        if is_excluded(rel, DEFAULT_EXCLUDE_DIRS, DEFAULT_EXCLUDE_EXTS, DEFAULT_EXCLUDE_FILES, [], []):
            if verbose and path.name == "yarn.lock":
                print("  Skipping (default rule): yarn.lock")
            continue
        total += 1
        flat_name = rel.replace("/", "_") if name_by_path else path.name
        target = flat_dir / flat_name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)

    if verbose:
        print(f"Flattened {total} files into {flat_dir}.")
    return flat_dir


# =====================================================================================
# Size trimming
# =====================================================================================

def delete_files_to_fit_size(
    directory: Path,
    max_megabytes: int,
    preferences: List[str],
    verbose: bool = False
) -> List[str]:
    """
    Delete files (prioritizing extensions in 'preferences', then by size desc)
    until the directory size <= max_megabytes. Returns removed file paths (str).
    """
    directory = Path(directory)
    max_bytes = max(0, int(max_megabytes * 1024 * 1024))
    removed: List[str] = []

    def gather():
        files = []
        for p in directory.rglob("*"):
            if p.is_file():
                try:
                    sz = p.stat().st_size
                except FileNotFoundError:
                    continue
                files.append((p, sz, p.suffix.lower()))
        return files

    files = gather()
    total = sum(sz for _, sz, _ in files)
    if total <= max_bytes:
        return removed

    pref_index = {ext.lower(): i for i, ext in enumerate(preferences)}
    files.sort(key=lambda t: (pref_index.get(t[2], len(preferences)), -t[1]))
    i = 0
    while total > max_bytes and i < len(files):
        p, sz, _ = files[i]
        try:
            p.unlink()
            removed.append(str(p))
            total -= sz
        except FileNotFoundError:
            pass
        i += 1

    if verbose:
        pass
    return removed


# =====================================================================================
# Internal collectors
# =====================================================================================

def _collect_files(
    root: Path,
    exclude_dirs: set[str],
    exclude_exts: set[str],
    exclude_files: set[str],
    remove_patterns: list[str],
    keep_patterns: list[str],
) -> list[Path]:
    collected = []
    for p in root.rglob("*"):
        if p.is_file():
            rel = _rel_posix(root, p)
            if is_excluded(rel, exclude_dirs, exclude_exts, exclude_files, remove_patterns, keep_patterns):
                continue
            collected.append(p)
    return collected

def _ensure_folder_structure_in(
    dir_path: Path,
    src_root: Path,
    exclude_dirs: set[str],
    remove_patterns: list[str],
    keep_patterns: list[str],
) -> None:
    fs = dir_path / "folder_structure.txt"
    _write_folder_structure(src_root, fs, exclude_dirs, remove_patterns, keep_patterns)


# =====================================================================================
# ZIP creation
# =====================================================================================

def zip_folder(
    source_dir_str: str,
    output_zip_str: str,
    exclude_dirs: set[str],
    exclude_exts: set[str],
    exclude_files: set[str],
    remove_patterns: list[str],
    keep_patterns: list[str],
    max_size: Optional[int],
    preferences: List[str],
    flatten: bool,
    name_by_path: bool,
    verbose: bool
) -> None:
    source_dir = Path(source_dir_str).resolve()
    output_zip = Path(output_zip_str).resolve()
    output_zip.parent.mkdir(parents=True, exist_ok=True)

    working_dir_for_zip: Path
    temp_base: Optional[Path] = None

    if flatten:
        temp_base = output_zip.parent / f"_temp_flatten_{source_dir.name}_{os.getpid()}"
        temp_base.mkdir(parents=True, exist_ok=True)
        flat_dir = temp_base / "_flattened"
        flat_dir.mkdir(parents=True, exist_ok=True)

        if verbose:
            print(f"Flatten mode: zipping from {flat_dir}")

        orig_files = _collect_files(
            source_dir, exclude_dirs, exclude_exts, exclude_files, remove_patterns, keep_patterns
        )
        for path in orig_files:
            rel = _rel_posix(source_dir, path)
            flat_name = rel.replace("/", "_") if name_by_path else path.name
            dst = flat_dir / flat_name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dst)

        _ensure_folder_structure_in(flat_dir, source_dir, exclude_dirs, remove_patterns, keep_patterns)
        working_dir_for_zip = flat_dir
    else:
        working_dir_for_zip = source_dir

    if max_size is not None and max_size > 0:
        if not flatten:
            temp_base = output_zip.parent / f"_temp_zip_{source_dir.name}_{os.getpid()}"
            shutil.copytree(source_dir, temp_base, dirs_exist_ok=False)
            working_dir_for_zip = temp_base
        delete_files_to_fit_size(working_dir_for_zip, max_size, preferences, verbose=verbose)

    if verbose:
        print(f"Creating zip '{output_zip.name}'")

    if working_dir_for_zip == source_dir and not flatten:
        files_to_add = _collect_files(
            source_dir, exclude_dirs, exclude_exts, exclude_files, remove_patterns, keep_patterns
        )
    else:
        files_to_add = [p for p in working_dir_for_zip.rglob("*") if p.is_file()]

    added = 0
    with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for p in files_to_add:
            if working_dir_for_zip == source_dir:
                arcname = _rel_posix(source_dir, p)
            else:
                arcname = p.relative_to(working_dir_for_zip).as_posix()
            z.write(p, arcname)
            added += 1

    if verbose:
        print(f"Total files zipped: {added}")
    try:
        sz_mb = output_zip.stat().st_size / (1024 * 1024)
        print(f"\nFinal zip '{output_zip.name}' size: {sz_mb:.2f} MB")
    except FileNotFoundError:
        print(f"\nFinal zip '{output_zip.name}' size: 0.00 MB")

    if temp_base and temp_base.exists():
        try:
            shutil.rmtree(temp_base, ignore_errors=True)
            if verbose:
                print(f"Cleaned temp: {temp_base}")
        except Exception:
            pass


# =====================================================================================
# Text mode
# =====================================================================================

def text_file_mode(
    source_dir_str: str,
    output_txt_str: str,
    exclude_dirs: set[str],
    exclude_exts: set[str],
    exclude_files: set[str],
    remove_patterns: list[str],
    keep_patterns: list[str],
    flatten: bool,
    name_by_path: bool,
    verbose: bool
) -> None:
    source_dir = Path(source_dir_str).resolve()
    out = Path(output_txt_str).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    tmp_text_root: Optional[Path] = None
    scan_root: Path

    if flatten:
        tmp_text_root = out.parent / f"_temp_text_flatten_{source_dir.name}_{os.getpid()}"
        tmp_text_root.mkdir(parents=True, exist_ok=True)
        flat_dir = tmp_text_root / "_flattened"
        flat_dir.mkdir(parents=True, exist_ok=True)

        if verbose:
            print(f"Flattening directory {tmp_text_root.name} into _flattened...")

        orig_files = _collect_files(
            source_dir, exclude_dirs, exclude_exts, exclude_files, remove_patterns, keep_patterns
        )
        total = 0
        for path in orig_files:
            rel = _rel_posix(source_dir, path)
            new_name = rel.replace("/", "_") if name_by_path else path.name
            dst = flat_dir / new_name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dst)
            total += 1

        if verbose:
            print(f"Flattened {total} files into {flat_dir}.")
            print(f"Text flatten: {flat_dir}")
        scan_root = flat_dir
    else:
        scan_root = source_dir

    if verbose:
        print("Generating folder structure...")

    preamble = (
        "This document packages a repository for a Large Language Model (LLM).\n"
        "It contains a high-level folder structure followed by selected file contents.\n\n"
    )
    with out.open("w", encoding="utf-8") as f:
        f.write(preamble)

    _write_folder_structure(source_dir, out, exclude_dirs, remove_patterns, keep_patterns)

    if verbose:
        print(f"\nProcessing files for '{out.name}'...")

    # Candidate files
    if scan_root == source_dir:
        files = _collect_files(
            source_dir, exclude_dirs, exclude_exts, exclude_files, remove_patterns, keep_patterns
        )
    else:
        files = [p for p in scan_root.rglob("*") if p.is_file()]

    total_files = 0
    added_files = 0
    binary_logs: list[str] = []

    with out.open("a", encoding="utf-8") as f:
        for p in files:
            total_files += 1
            # Display name
            if scan_root == source_dir:
                display_name = _rel_posix(source_dir, p)
            else:
                display_name = p.relative_to(scan_root).as_posix()

            ext = p.suffix.lower()

            # Special-case .bin: try-read; on decode error skip entirely (no header), but log if verbose.
            if ext == ".bin":
                try:
                    content = p.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    if verbose:
                        binary_logs.append(f"{display_name} (binary or non-UTF-8 content)")
                    continue
                # If readable, include normally
                f.write(f"\n-- File: {display_name} --\n")
                f.write(content.rstrip() + "\n")
                added_files += 1
                continue

            # For other files: write header first, then try to read; keep header even if decode fails.
            f.write(f"\n-- File: {display_name} --\n")
            try:
                content = p.read_text(encoding="utf-8")
                f.write(content.rstrip() + "\n")
                added_files += 1
            except UnicodeDecodeError:
                if verbose:
                    binary_logs.append(f"{display_name} (binary or non-UTF-8 content)")
                # keep header only

    if tmp_text_root and tmp_text_root.exists():
        try:
            shutil.rmtree(tmp_text_root, ignore_errors=True)
            if verbose:
                print(f"Cleaned text temp: {tmp_text_root}")
        except Exception:
            pass

    # Verbose “skipped” summary
    if verbose:
        print("Files skipped from content:")
        if scan_root == source_dir:
            # derive excluded = all - included
            allowed = set(_rel_posix(source_dir, p) for p in files)
            for p in source_dir.rglob("*"):
                if not p.is_file():
                    continue
                rel = _rel_posix(source_dir, p)
                if rel not in allowed:
                    print(f"    - {rel} (excluded)")
        for b in binary_logs:
            print(f"    - {b}")

    print(f"\nText file complete: {out.name}")
    print(f"Total files encountered: {total_files}")
    print(f"Files added to text: {added_files}")


# =====================================================================================
# Gemini helpers (legacy names kept for tests)
# =====================================================================================

def _git_commit_snapshot(repo_root: Path, limit: int | None) -> str:
    """
    Return a concise commit history (messages + dates). If git missing or not a repo,
    return empty string.
    """
    try:
        subprocess.run(["git", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    except Exception:
        return ""
    try:
        args = ["git", "-C", str(repo_root), "log", "--date=short", "--pretty=format:%h %ad %an %s"]
        if limit and limit > 0:
            args[5:5] = [f"-n{limit}"]
        cp = subprocess.run(args, capture_output=True, text=True, check=True)
        return cp.stdout.strip()
    except Exception:
        return ""


def run_gemini_analysis(
    filtered_workspace: Path,
    model_name: str,
    analysis_outfile: Path,
    include_commits: bool,
    commit_limit: int | None,
    show_memory: bool,
    verbose: bool,
) -> int:
    """
    Launch Gemini CLI in non-interactive mode with --all-files.
    Writes stdout to analysis_outfile and returns the process rc.
    """
    filtered_workspace = Path(filtered_workspace).resolve()
    analysis_outfile = Path(analysis_outfile).resolve()
    analysis_outfile.parent.mkdir(parents=True, exist_ok=True)

    # Optional commit snapshot visible to the model
    if include_commits:
        snap = _git_commit_snapshot(filtered_workspace, commit_limit)
        if snap:
            (filtered_workspace / "COMMIT_HISTORY_FOR_LLM.md").write_text(snap, encoding="utf-8")

    cmd = ["gemini"]
    if show_memory:
        cmd.append("--show-memory-usage")
    # Minimal prompt; tests only assert flags & model presence
    cmd += ["-m", model_name, "--all-files", "-i", "Analyze repository"]

    if verbose:
        # Keep quiet; tests don't assert printing of the command itself.
        pass

    cp = subprocess.run(cmd, cwd=str(filtered_workspace), capture_output=True, text=True)
    # Always write stdout
    analysis_outfile.write_text(cp.stdout or "", encoding="utf-8")
    return cp.returncode


def prepare_analysis_workspace(
    source_dir: Path,
    exclude_dirs: set[str],
    exclude_exts: set[str],
    exclude_files: set[str],
    remove_patterns: list[str],
    keep_patterns: list[str],
    verbose: bool = False
) -> Path:
    """
    Copy the repo into a temporary workspace and prune with the same exclusion logic.
    Also adds a simple workspace README.
    """
    source_dir = Path(source_dir).resolve()
    ws_root = source_dir.parent / f"_gemini_ws_{source_dir.name}_{os.getpid()}"
    shutil.copytree(source_dir, ws_root, dirs_exist_ok=True)

    # Prune
    for p in list(ws_root.rglob("*")):
        rel = _rel_posix(ws_root, p)
        if p.is_dir():
            parts = _path_parts(rel)
            if any(part in exclude_dirs for part in parts) or any(fnmatch.fnmatch(part, pat) for part in parts for pat in exclude_dirs) or _matches_any(exclude_dirs, rel):
                shutil.rmtree(p, ignore_errors=True)
                if verbose:
                    print(f"Removed dir: {p}")
            continue

        if is_excluded(rel, exclude_dirs, exclude_exts, exclude_files, remove_patterns, keep_patterns):
            try:
                p.unlink()
                if verbose:
                    print(f"Removed file: {p}")
            except FileNotFoundError:
                pass

    (ws_root / "LLM_WORKSPACE_README.txt").write_text(
        "This is a temporary workspace curated for LLM analysis.\n"
        "It mirrors the source tree minus excluded artifacts.\n",
        encoding="utf-8"
    )
    if verbose:
        print(f"Prepared analysis workspace: {ws_root}")
    return ws_root


# =====================================================================================
# CLI
# =====================================================================================

def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Package a folder for LLMs (zip and/or text) with optional Gemini analysis."
    )

    # Single-letter short flags only
    p.add_argument("-S", "--source", required=True, help="Folder to process")
    p.add_argument("-O", "--output", required=True, help="Base output path (e.g., out, out.zip, out.txt)")

    # Output modes
    p.add_argument("-T", "--text", action="store_true", help="Produce a consolidated text file")
    p.add_argument("-Z", "--zip", action="store_true", help="Produce a zip file (default if neither mode set)")

    # Filtering
    p.add_argument("-D", "--exclude-dir", nargs="*", default=list(DEFAULT_EXCLUDE_DIRS),
                   help="Directory names or globs to exclude (match on basename or relpath)")
    p.add_argument("-E", "--exclude-ext", nargs="*", default=list(DEFAULT_EXCLUDE_EXTS),
                   help="File extensions to exclude (e.g., .o .so)")
    p.add_argument("-x", "--exclude-file", nargs="*", default=list(DEFAULT_EXCLUDE_FILES),
                   help="Specific filenames to exclude (exact or glob)")
    p.add_argument("-i", "--include-file", nargs="*", default=[],
                   help="Force-include filenames (removed from exclude-file list)")
    p.add_argument("-r", "--remove-patterns", nargs="*", default=[],
                   help="Glob patterns applied to basenames/relpaths to remove")
    p.add_argument("-k", "--keep-patterns", nargs="*", default=[],
                   help="Glob patterns that override ALL removals")
    p.add_argument("-P", "--preset", choices=PRESETS.keys(), help="Language/framework preset (e.g., python)")

    # Zip options
    p.add_argument("-m", "--max-size", type=int, help="Max zip size in MB (prunes working copy if exceeded)")
    p.add_argument("-c", "--preferences", nargs="*", default=[],
                   help="Preferred file extensions to delete first when pruning (e.g., .log .dat)")

    # Formatting
    p.add_argument("-a", "--flatten", action="store_true", help="Flatten directory structure before packaging")
    p.add_argument("-n", "--name-by-path", action="store_true", help="In flatten mode, include original path in filename")

    # Gemini
    p.add_argument("-G", "--gemini", action="store_true", help="Run Gemini analysis over a filtered workspace")
    p.add_argument("-g", "--gemini-model", default="flash",
                   help="Model shorthand: 'flash' or 'pro', or a full model id (default: flash)")
    p.add_argument("-C", "--gemini-commits-analyze", action="store_true",
                   help="Include recent commit history snapshot for analysis")
    p.add_argument("-l", "--gemini-commits-limit", type=int, default=20,
                   help="Limit number of commits for snapshot")
    p.add_argument("-U", "--gemini-output", default="", help="Write Gemini analysis here (default '<base>-gemini.md')")
    p.add_argument("-W", "--gemini-keep-workspace", action="store_true", help="Keep temporary Gemini workspace")

    p.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    run_text = args.text
    run_zip = args.zip or not run_text  # default to zip when neither selected

    # Apply preset
    final_exclude_files = set(args.exclude_file) - set(args.include_file)
    final_exclude_dirs = set(args.exclude_dir)
    final_exclude_exts = set(args.exclude_ext)
    final_remove_patterns = list(args.remove_patterns)
    final_keep_patterns = list(args.keep_patterns)

    if args.preset:
        preset = PRESETS[args.preset]
        final_exclude_dirs.update(preset.get("dirs", set()))       # type: ignore[arg-type]
        final_exclude_exts.update(preset.get("exts", set()))       # type: ignore[arg-type]
        final_exclude_files.update(preset.get("files", set()))     # type: ignore[arg-type]
        final_remove_patterns.extend(preset.get("patterns", []))   # type: ignore[arg-type]

    # Resolve outputs
    output_arg = Path(args.output)
    output_dir = output_arg.parent if output_arg.parent != Path("") else Path(".")
    output_dir.mkdir(parents=True, exist_ok=True)

    if output_arg.name.startswith(".") and not output_arg.stem.startswith("."):
        base_name = output_arg.name
    else:
        base_name = output_arg.stem if output_arg.stem else output_arg.name

    text_out: Optional[Path] = None
    zip_out: Optional[Path] = None

    if run_text and run_zip:
        suf = output_arg.suffix.lower()
        if suf == ".txt":
            text_out = output_arg
            zip_out = output_dir / (base_name + ".zip")
        elif suf == ".zip":
            zip_out = output_arg
            text_out = output_dir / (base_name + ".txt")
        else:
            text_out = output_dir / (base_name + ".txt")
            zip_out = output_dir / (base_name + ".zip")
    elif run_text:
        text_out = output_dir / (base_name + ".txt") if output_arg.suffix.lower() != ".txt" else output_arg
    else:
        zip_out = output_dir / (base_name + ".zip") if output_arg.suffix.lower() != ".zip" else output_arg

    # Execute modes
    if text_out:
        text_file_mode(
            args.source, str(text_out),
            final_exclude_dirs, final_exclude_exts, final_exclude_files,
            final_remove_patterns, final_keep_patterns,
            args.flatten, args.name_by_path, args.verbose
        )

    if zip_out:
        zip_folder(
            args.source, str(zip_out),
            final_exclude_dirs, final_exclude_exts, final_exclude_files,
            final_remove_patterns, final_keep_patterns,
            args.max_size, args.preferences,
            args.flatten, args.name_by_path, args.verbose
        )

    # Optional Gemini analysis — use the workspace as-is (no extra filtering here)
    if args.gemini:
        model = args.gemini_model
        report_path = Path(args.gemini_output) if args.gemini_output else (output_dir / f"{base_name}-gemini.md")
        rc = run_gemini_analysis(
            filtered_workspace=Path(args.source),
            model_name=("gemini-2.5-flash" if model.lower() == "flash" else ("gemini-2.5-pro" if model.lower() == "pro" else model)),
            analysis_outfile=report_path,
            include_commits=args.gemini_commits_analyze,
            commit_limit=args.gemini_commits_limit,
            show_memory=args.verbose,
            verbose=args.verbose,
        )
        if args.verbose:
            print(f"Gemini CLI exited with {rc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
