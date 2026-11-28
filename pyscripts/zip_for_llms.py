#!/usr/bin/env python3
"""
zip_for_llms.py
Package a repo for LLM consumption (zip and/or consolidated text), with optional
Gemini CLI analysis over a filtered workspace and (optional) recent commit history.

Key improvements in this release:
- Verbose skip output is now compact: if a directory is excluded, we DO NOT print
  any of its children. One line per excluded dir, period.
- Restored readable colored output for humans (auto-disables when not a TTY or NO_COLOR set).
- Gemini (-G) now shows a spinner/progress line while the CLI runs so you can
  tell it's working instead of "hanging".
- Presets expanded to mirror GitHub .gitignore templates for popular stacks
  (python, cpp, node, rust, go, java, dotnet, swift). Using a preset adjusts
  dirs/exts/files/remove-patterns by default.
- NEW: Size tree reporting at the end of the run. Use:
    -T / --size-tree [DEPTH]           (default 1 if value omitted)
    -A / --auto-size-tree [TOPN]       (default 25 if value omitted; wins if both given)

CLI style (single-letter + long-form, all programs must honor both):
  -f / --file-mode           -> emit consolidated .txt
  -z / --zip-mode            -> emit .zip
  -o / --output              -> output base name/path (extension inferred if needed)
  -x / --exclude-dir         -> exclude directory (repeatable)
  -e / --exclude-ext         -> exclude extension (repeatable, with dot)
  -X / --exclude-file        -> exclude filename (repeatable)
  -I / --include-file        -> force-include filename (removes from exclude set)
  -R / --remove-pattern      -> fnmatch to drop paths (repeatable)
  -K / --keep-pattern        -> fnmatch to rescue paths (repeatable)
  -m / --max-size            -> max zip size in MiB (best-effort culling)
  -p / --preferences         -> comma list of preferred extensions to drop when trimming
  -F / --flatten             -> copy files to a temp "_flattened" staging folder
  -N / --name-by-path        -> if flattening, rename files by path (a_b_c.ext)
  -v / --verbose             -> show progress & skip details
  -P / --preset              -> use language preset (python, cpp, node, rust, go, java, dotnet, swift)
  -G / --gemini              -> run Gemini CLI analysis on filtered workspace
  -M / --model               -> Gemini model (default: gemini-2.5-flash)
  -C / --include-commits     -> include a compact git commit snapshot in analysis workspace
  -L / --commit-limit        -> limit the number of commits if included (default 20)
  -S / --show-memory         -> add '--show-memory-usage' to Gemini CLI
  -T / --size-tree [DEPTH]   -> print size tree to given depth (default 1 if no value)
  -A / --auto-size-tree [N]  -> print "top N" largest folders (default 25). If deeper, parents included.

The module also exposes:
- zip_folder, text_file_mode, flatten_directory, delete_files_to_fit_size
- prepare_analysis_workspace, run_gemini_analysis
- compute_filtered_dir_sizes, render_size_tree
- DEFAULT_EXCLUDE_DIRS/EXTS/FILES, PRESETS
"""
from __future__ import annotations

__version__ = "0.3.0"

import argparse
import json
import fnmatch
import io
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Dict, Iterable, List, Optional, Set, Tuple



# =====================================================================================
# ANSI color helpers (auto-disable for non-TTY or NO_COLOR)
# =====================================================================================

def _supports_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    try:
        return sys.stdout.isatty()
    except Exception:
        return False

_COLOR = _supports_color()

def C(code: str) -> str:
    return f"\033[{code}m" if _COLOR else ""

COL = {
    "reset": C("0"),
    "bold": C("1"),
    "dim": C("2"),
    "green": C("32"),
    "yellow": C("33"),
    "red": C("31"),
    "cyan": C("36"),
    "magenta": C("35"),
    "blue": C("34"),
    "gray": C("90"),
}


def cfmt(s: str, color_key: str) -> str:
    return f"{COL.get(color_key,'')}{s}{COL['reset'] if _COLOR else ''}"


# =====================================================================================
# Defaults & Extended Presets
# =====================================================================================

DEFAULT_EXCLUDE_DIRS: Set[str] = {
    # VCS & IDE
    ".git", ".hg", ".svn", ".idea", ".vscode", ".DS_Store",
    # Python caches / envs
    "__pycache__", ".mypy_cache", ".pytest_cache", ".venv", "env", "venv", ".tox",
    # Node
    "node_modules",
    # Build / dist
    "dist", "build", "target", "out",
}

DEFAULT_EXCLUDE_EXTS: Set[str] = {
    # compiled
    ".pyc", ".pyo", ".pyd", ".o", ".obj", ".class",
    # archives & binaries
    ".zip", ".tar", ".gz", ".7z", ".rar", ".iso",
    ".dll", ".so", ".dylib", ".exe",
    # media-ish large odds
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".mp4", ".mov", ".mp3", ".wav",
    # package locks often noisy
    ".lock",
}

DEFAULT_EXCLUDE_FILES: Set[str] = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    ".coverage", "coverage.xml",
}

# Hefty, language-leaning presets inspired by github/gitignore contents.
# Note: these are static patterns; they don’t fetch from the web.
PRESETS = {
    "python": {
        "dirs": {
            ".venv", "venv", "env", "__pycache__", ".pytest_cache",
            ".pytest_tmp_root", ".pytest_tmp*", ".mypy_cache", ".tox",
            "build", "dist", "*.egg-info",
        },
        "exts": {".pyc", ".pyo", ".pyd", ".so"},
        "files": {".python-version", ".coverage", "coverage.xml"},
        "patterns": ["*.egg-info", ".ruff_cache", ".hypothesis", ".nox"],
    },
    "cpp": {
        "dirs": {"build", "cmake-build-*", "out", "bin", "obj", ".cache"},
        "exts": {".o", ".obj", ".a", ".lib", ".dll", ".so", ".dylib", ".exe", ".pdb"},
        "files": set(),
        "patterns": ["CMakeFiles", "CMakeCache.txt", "compile_commands.json"],
    },
    "node": {
        "dirs": {"node_modules", "dist", "coverage", ".next", ".nuxt", ".turbo"},
        "exts": {".log", ".map"},
        "files": {"package-lock.json", "yarn.lock", "pnpm-lock.yaml"},
        "patterns": [".vercel", ".cache", ".parcel-cache"],
    },
    "rust": {
        "dirs": {"target"},
        "exts": {".rlib", ".d", ".o"},
        "files": set(),
        "patterns": ["Cargo.lock"],
    },
    "go": {
        "dirs": {"bin"},
        "exts": {".test"},
        "files": {"go.sum"},
        "patterns": ["vendor", ".cache"],
    },
    "java": {
        "dirs": {"target", "out", ".gradle", ".idea"},
        "exts": {".class", ".jar", ".war", ".ear"},
        "files": {"pom.xml.tag"},
        "patterns": ["*.iml", "build"],
    },
    "dotnet": {
        "dirs": {"bin", "obj", ".vs"},
        "exts": {".dll", ".pdb", ".cache", ".mdb"},
        "files": {"project.lock.json"},
        "patterns": ["*.user", "*.suo"],
    },
    "swift": {
        "dirs": {".build", "DerivedData"},
        "exts": {".xcodeproj", ".xcworkspace"},
        "files": set(),
        "patterns": ["*.swiftpm"],
    },
}

# =====================================================================================
# Tiny structured printing utilities
# =====================================================================================

def _print_header(title: str) -> None:
    print(f"{cfmt('==', 'magenta')} {cfmt(title, 'bold')}")

def _print_stat(label: str, value: str) -> None:
    print(f"  {cfmt(label+':', 'cyan')} {value}")

def _print_skip(path: str, why: str) -> None:
    print(f"  - {cfmt(path, 'gray')} {cfmt(f'({why})', 'yellow')}")

def _print_ok(path: str) -> None:
    print(f"  + {cfmt(path, 'green')}")

def _print_warn(msg: str) -> None:
    print(f"{cfmt('warn:', 'yellow')} {msg}")

def _print_err(msg: str) -> None:
    print(f"{cfmt('error:', 'red')} {msg}", file=sys.stderr)


# =====================================================================================
# Helpers
# =====================================================================================

def _relpath(p: Path, root: Path) -> str:
    try:
        return str(PurePosixPath(p.relative_to(root)))
    except Exception:
        return str(PurePosixPath(p))


def _match_any_fragment(path_rel: str, patterns: Iterable[str]) -> bool:
    # Consider any fragment match: exact dir name, partial path fragment, or glob
    for pat in patterns:
        if pat in path_rel:
            return True
        if fnmatch.fnmatch(path_rel, pat):
            return True
    return False


def flatten_directory(source_dir: Path, exclusion: Exclusion, name_by_path: bool, verbose: bool) -> Path:
    """
    Copy all files into a temp "_flattened" directory for packaging, respecting exclusions.
    """
    flat = source_dir / "_flattened"
    if flat.exists():
        shutil.rmtree(flat)
    flat.mkdir()

    for src in _selected_files(source_dir, exclusion):
        rel = _relpath(src, source_dir)
        target_name = rel.replace("/", "_") if name_by_path else src.name
        dst = flat / target_name
        if verbose:
            _print_ok(f"flatten: {rel} -> {_relpath(dst, source_dir)}")
        try:
            shutil.copy2(src, dst)
        except Exception as e:
            if verbose:
                _print_warn(f"failed to copy {rel}: {e}")

    # Add a plain structure marker file for zip output parity
    (flat / "folder_structure.txt").write_text("Flattened view artifacts (see text mode for full structure).")
    return flat


def delete_files_to_fit_size(folder: Path, max_mib: int, preference_exts: Iterable[str], verbose: bool) -> List[str]:
    """
    Best-effort removal: delete biggest preferred-extension files first, then any
    other largest files, until the folder fits under max_mib.
    """
    max_bytes = max_mib * 1024 * 1024
    removed: List[str] = []

    def get_all_files(p: Path) -> List[Path]:
        file_list = []
        for r, _, files in os.walk(p):
            for f in files:
                file_list.append(Path(r) / f)
        return file_list

    def size_of_tree(files: List[Path]) -> int:
        return sum(f.stat().st_size for f in files if f.exists()) 

    preference_exts = set(preference_exts or [])
    
    all_files = get_all_files(folder)
    
    while size_of_tree(all_files) > max_bytes:
        preferred_candidates = sorted(
            [f for f in all_files if f.suffix in preference_exts and f.exists()],
            key=lambda p: p.stat().st_size,
            reverse=True
        )
        
        other_candidates = sorted(
            [f for f in all_files if f.suffix not in preference_exts and f.exists()],
            key=lambda p: p.stat().st_size,
            reverse=True
        )

        victim = None
        if preferred_candidates:
            victim = preferred_candidates[0]
        elif other_candidates:
            victim = other_candidates[0]
        
        if not victim:
            break

        try:
            if verbose:
                _print_warn(f"trimming to fit: deleting {_relpath(victim, folder)}")
            removed.append(str(victim))
            victim.unlink(missing_ok=True)
            all_files.remove(victim)
        except Exception as e:
            if verbose:
                _print_warn(f"failed to delete {victim}: {e}")
            break # Stop if a file can't be deleted
            
    return removed


# =====================================================================================
# Exclusion logic
# =====================================================================================

@dataclass(frozen=True)
class Exclusion:
    exclude_dirs: Set[str]
    exclude_exts: Set[str]
    exclude_files: Set[str]
    remove_patterns: List[str]
    keep_patterns: List[str]

    def dir_is_excluded(self, rel_dir: str) -> bool:
        # If directory name itself or any fragment/glob matches, it's excluded
        name = Path(rel_dir).name
        if name in self.exclude_dirs:
            return True
        if rel_dir in self.exclude_dirs:
            return True
        if _match_any_fragment(rel_dir, self.exclude_dirs):
            return True
        # Also check remove_patterns for directories
        return _match_any_fragment(rel_dir, self.remove_patterns)

    def file_is_excluded(self, rel_path: str) -> bool:
        # Keep overrides remove
        base = Path(rel_path).name
        if base in self.keep_patterns or any(fnmatch.fnmatch(base, pat) for pat in self.keep_patterns):
            return False
        if base in self.exclude_files:
            return True
        if Path(rel_path).suffix in self.exclude_exts:
            return True
        if any(fnmatch.fnmatch(rel_path, pat) for pat in self.remove_patterns):
            return True
        # If any parent dir is excluded by pattern, treat as excluded (pruning handles this too)
        parts = Path(rel_path).parts
        agg = ""
        for part in parts[:-1]:
            agg = f"{agg}/{part}" if agg else part
            if self.dir_is_excluded(agg):
                return True
        return False

    def exclusion_reason(self, rel_path: str) -> str:
        """Return a readable reason for an excluded file, respecting keep precedence."""
        base = Path(rel_path).name
        if base in self.keep_patterns or any(fnmatch.fnmatch(base, pat) for pat in self.keep_patterns):
            return "included by keep pattern"
        if base in self.exclude_files:
            return "excluded filename"
        if Path(rel_path).suffix in self.exclude_exts:
            return "excluded extension"
        if any(fnmatch.fnmatch(rel_path, pat) for pat in self.remove_patterns):
            return "removed by pattern"
        parts = Path(rel_path).parts
        agg = ""
        for part in parts[:-1]:
            agg = f"{agg}/{part}" if agg else part
            if self.dir_is_excluded(agg):
                return "under excluded directory"
        return "excluded"


def _selected_files(source_dir: Path, exclusion: Exclusion) -> Iterable[Path]:
    """Yield selected files deterministically while pruning excluded directories."""
    for root, dirs, files in os.walk(source_dir):
        root_path = Path(root)
        dirs[:] = sorted(
            (d for d in dirs if not exclusion.dir_is_excluded(_relpath(root_path / d, source_dir))),
            key=lambda name: (name.casefold(), name),
        )
        for name in sorted(files, key=lambda name: (name.casefold(), name)):
            path = root_path / name
            if not exclusion.file_is_excluded(_relpath(path, source_dir)):
                yield path


# =====================================================================================
# Text mode
# =====================================================================================

def _get_llm_introduction() -> str:
    """Returns a detailed introductory text for the packaged file."""
    return """
This document is a self-contained representation of a software repository, packaged for analysis by a Large Language Model (LLM).

It contains two main sections:

1.  **Folder Structure:** A hierarchical tree view of the repository's directories and files.
    - Directories marked with `(excluded)` were skipped based on the packaging rules.
    - The tree provides a map to understand the layout and organization of the code.

2.  **File Contents:** The full content of each included file.
    - Each file's content is preceded by a header like `-- File: path/to/file.ext --`.
    - Files that are binary, non-UTF-8, or could not be read are noted and their content is omitted.

The purpose is to provide all necessary context for code analysis, review, or documentation tasks without requiring the LLM to have direct access to a file system.
"""


def _emit_folder_structure(root: Path, exclusion: Exclusion, out: io.TextIOBase, verbose: bool) -> None:
    """
    Generates and writes a visual tree structure of the directory, respecting exclusions.
    """
    out.write(f"\nFolder Structure for: {root.name}\n")
    
    def walk(d: Path, prefix: str = "") -> None:
        rel_dir = _relpath(d, root)
        if rel_dir and exclusion.dir_is_excluded(rel_dir):
            if verbose:
                _print_skip(rel_dir, "excluded dir")
            return

        # Get children and sort them: dirs first, then files, all alphabetically
        try:
            all_children = sorted(list(d.iterdir()), key=lambda p: (not p.is_dir(), p.name.lower()))
        except OSError:
            all_children = []

        # Filter children that will be visible in the tree
        visible_children = [
            p for p in all_children
            if p.is_dir() or not exclusion.file_is_excluded(_relpath(p, root))
        ]

        for i, child in enumerate(visible_children):
            is_last = i == (len(visible_children) - 1)
            connector = "└── " if is_last else "├── "
            
            rel_child_path = _relpath(child, root)

            if child.is_dir():
                if exclusion.dir_is_excluded(rel_child_path):
                    out.write(f"{prefix}{connector}{child.name}/ (excluded)\n")
                    if verbose:
                        _print_skip(rel_child_path, "excluded dir")
                else:
                    out.write(f"{prefix}{connector}{child.name}/\n")
                    new_prefix = prefix + ("    " if is_last else "│   ")
                    walk(child, new_prefix)
            else:
                # This check is now redundant because we pre-filtered.
                out.write(f"{prefix}{connector}{child.name}\n")

    out.write(f"{root.name}/\n")
    walk(root)


def text_file_mode(
    source_dir_str: str,
    output_txt_str: str,
    exclude_dirs: Set[str],
    exclude_exts: Set[str],
    exclude_files: Set[str],
    remove_patterns: List[str],
    keep_patterns: List[str],
    flatten: bool,
    name_by_path: bool,
    verbose: bool,
) -> None:
    source_dir = Path(source_dir_str).resolve()
    output_txt = Path(output_txt_str)

    exclusion = Exclusion(set(exclude_dirs), set(exclude_exts), set(exclude_files), list(remove_patterns), list(keep_patterns))

    if verbose:
        _print_header("Generating folder structure...")
    with io.open(output_txt, "w", encoding="utf-8") as out:
        out.write(_get_llm_introduction())
        _emit_folder_structure(source_dir, exclusion, out, verbose)

        out.write("\nProcessing files for content...\n")

        skipped_once_dirs: Set[str] = set()  # remember which excluded dirs we already logged

        # Prepare flattening if requested (still prints structure from original tree)
        staging_root = source_dir
        if flatten:
            if verbose:
                _print_header("Flattening files...")
            staging_root = flatten_directory(source_dir, exclusion, name_by_path=name_by_path, verbose=verbose)

        # Walk staging root for file contents (prune excluded dirs entirely)
        for r, dirs, files in os.walk(staging_root):
            root_path = Path(r)
            # Prune excluded dirs BEFORE descent; print just once per dir.
            pruned: List[str] = []
            for d in list(dirs):
                rel_d = _relpath(root_path / d, staging_root)
                if exclusion.dir_is_excluded(rel_d):
                    pruned.append(d)
                    if verbose and rel_d not in skipped_once_dirs:
                        _print_skip(rel_d, "excluded dir")
                        skipped_once_dirs.add(rel_d)
            for d in pruned:
                dirs.remove(d)

            # Process files
            for f in files:
                p = root_path / f
                rel = _relpath(p, staging_root)
                if exclusion.file_is_excluded(rel):
                    # Only print skip if not under an already-excluded dir (we pruned, but be safe)
                    parent_rel = _relpath(p.parent, staging_root)
                    if verbose and not exclusion.dir_is_excluded(parent_rel):
                        reason = "excluded" if Path(rel).suffix in exclusion.exclude_exts or Path(rel).name in exclusion.exclude_files else "removed by pattern"
                        _print_skip(rel, reason)
                    continue

                # Emit header then try to read as UTF-8 text
                display_name = rel.replace("/", "_") if (flatten and name_by_path) else rel
                out.write(f"\n-- File: {display_name} --\n")
                try:
                    with io.open(p, "r", encoding="utf-8") as fin:
                        out.write(fin.read())
                except UnicodeDecodeError:
                    if verbose:
                        _print_skip(rel, "binary or non-UTF-8 content")
                except Exception as e:
                    if verbose:
                        _print_warn(f"read error {rel}: {e}")

        if flatten and staging_root != source_dir:
            shutil.rmtree(staging_root, ignore_errors=True)

    if verbose:
        _print_stat("Text file complete", str(output_txt))
        _print_stat("Source", str(source_dir))


# =====================================================================================
# Zip mode
# =====================================================================================

def zip_folder(
    source_dir_str: str,
    output_zip_str: str,
    exclude_dirs: Set[str],
    exclude_exts: Set[str],
    exclude_files: Set[str],
    remove_patterns: List[str],
    keep_patterns: List[str],
    max_size: Optional[int],
    preferences: List[str],
    flatten: bool,
    name_by_path: bool,
    verbose: bool,
) -> None:
    source_dir = Path(source_dir_str).resolve()
    output_zip = Path(output_zip_str)
    exclusion = Exclusion(set(exclude_dirs), set(exclude_exts), set(exclude_files), list(remove_patterns), list(keep_patterns))

    with tempfile.TemporaryDirectory() as td:
        staging_root = Path(td)

        if verbose:
            _print_header("Preparing files for zip...")

        for p in _selected_files(source_dir, exclusion):
            rel = _relpath(p, source_dir)
            (staging_root / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, staging_root / rel)

        if flatten:
            if verbose:
                _print_header("Flattening files...")
            flat_staging_root = flatten_directory(staging_root, exclusion, name_by_path=name_by_path, verbose=verbose)
            # Replace staging_root with the flattened one for zipping
            staging_root = flat_staging_root

        # Size trimming if requested
        if max_size is not None:
            removed = delete_files_to_fit_size(staging_root, max_size, preferences, verbose=verbose)
            if verbose and removed:
                _print_warn(f"trimmed {len(removed)} files to honor max size")

        # Create zip from the staging root
        if verbose:
            _print_header(f"Creating zip: {output_zip.name}")
        with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED) as z:
            # Add a structure marker (helps LLM context)
            structure_txt = "folder_structure.txt"
            z.writestr(structure_txt, "See text mode for detailed structure.")
            if verbose:
                _print_ok(f"added {structure_txt}")

            for r, _, files in os.walk(staging_root):
                root_path = Path(r)
                for f in files:
                    p = root_path / f
                    rel = _relpath(p, staging_root)
                    arcname = rel
                    try:
                        z.write(p, arcname)
                        if verbose:
                            _print_ok(f"+ {arcname}")
                    except Exception as e:
                        if verbose:
                            _print_warn(f"failed to add {rel}: {e}")

    if verbose:
        _print_stat("Zip complete", str(output_zip))


# =====================================================================================
# Gemini analysis
# =====================================================================================

def _spinner(stop_event: threading.Event, label: str = "Running Gemini") -> None:
    frames = "|/-\\"
    i = 0
    start = time.time()
    while not stop_event.is_set():
        elapsed = int(time.time() - start)
        msg = f"\r{cfmt(frames[i % len(frames)], 'cyan')} {label}… {elapsed}s"
        sys.stdout.write(msg)
        sys.stdout.flush()
        time.sleep(0.15)
        i += 1
    # clear line
    sys.stdout.write("\r" + " " * 60 + "\r")
    sys.stdout.flush()


def _git_commit_snapshot(repo_root: Path, limit: Optional[int]) -> str | None:
    try:
        cmd = ["git", "log", "--pretty=format:%h %ad %s", "--date=short"]
        if limit:
            cmd.extend(["-n", str(limit)])
        cp = subprocess.run(cmd, cwd=str(repo_root), capture_output=True, text=True)
        if cp.returncode == 0 and cp.stdout.strip():
            return cp.stdout.strip()
    except Exception:
        pass
    return None


def prepare_analysis_workspace(
    source_dir: Path,
    exclude_dirs: Set[str],
    exclude_exts: Set[str],
    exclude_files: Set[str],
    remove_patterns: List[str],
    keep_patterns: List[str],
    verbose: bool,
) -> Path:
    """
    Copy filtered tree into a temporary workspace for Gemini CLI to analyze.
    """
    exclusion = Exclusion(set(exclude_dirs), set(exclude_exts), set(exclude_files), list(remove_patterns), list(keep_patterns))
    ws = Path(tempfile.mkdtemp(prefix="llm_ws_"))

    if verbose:
        _print_header("Generating analysis workspace...")

    for r, dirs, files in os.walk(source_dir):
        root_path = Path(r)
        rel_dir = _relpath(root_path, source_dir)
        # Prune & mirror directories
        pruned: List[str] = []
        for d in list(dirs):
            rel_d = _relpath(root_path / d, source_dir)
            if exclusion.dir_is_excluded(rel_d):
                pruned.append(d)
                if verbose:
                    _print_skip(rel_d, "excluded dir")
        for d in pruned:
            dirs.remove(d)
        # Ensure mirrored directory exists in ws
        target_dir = ws / (rel_dir if rel_dir != "." else "")
        target_dir.mkdir(parents=True, exist_ok=True)
        # Copy files
        for f in files:
            src = root_path / f
            rel = _relpath(src, source_dir)
            if exclusion.file_is_excluded(rel):
                if verbose:
                    _print_skip(rel, "excluded")
                continue
            dst = target_dir / f
            try:
                shutil.copy2(src, dst)
            except Exception as e:
                if verbose:
                    _print_warn(f"copy failed {rel}: {e}")

    return ws


def run_gemini_analysis(
    filtered_workspace: Path,
    model_name: str,
    analysis_outfile: Path,
    include_commits: bool,
    commit_limit: Optional[int],
    show_memory: bool,
    verbose: bool,
) -> int:
    """
    Execute 'gemini' CLI with all-files flag and optional commit history.
    Shows a spinner while the subprocess runs so the UI isn't "frozen".
    """
    if include_commits:
        snap = _git_commit_snapshot(filtered_workspace, commit_limit)
        if snap:
            (filtered_workspace / "COMMIT_HISTORY_FOR_LLM.md").write_text(snap)

    cmd = [
        "gemini",
        "--all-files",
        "--model", model_name,
        "--output", str(analysis_outfile),
    ]
    if show_memory:
        cmd.append("--show-memory-usage")

    if verbose:
        _print_header("Starting Gemini CLI")
        _print_stat("CWD", str(filtered_workspace))
        _print_stat("Model", model_name)
        _print_stat("Output", str(analysis_outfile))

    stop = threading.Event()
    t = threading.Thread(target=_spinner, args=(stop, "Gemini analysis"), daemon=True)
    t.start()
    try:
        cp = subprocess.run(cmd, cwd=str(filtered_workspace), capture_output=True, text=True)
    finally:
        stop.set()
        t.join()

    # Always write whatever stdout produced; helpful for debugging
    try:
        if cp.stdout:
            Path(analysis_outfile).write_text(cp.stdout)
    except Exception as e:
        if verbose:
            _print_warn(f"could not write analysis output: {e}")

    if cp.returncode != 0:
        _print_err(f"Gemini exited with {cp.returncode}")
        if verbose and cp.stderr:
            _print_err(cp.stderr)
    else:
        if verbose:
            _print_ok("Gemini analysis complete")

    return cp.returncode


# =====================================================================================
# Size tree computation & rendering
# =====================================================================================

def _human_bytes(n: int) -> str:
    """Human-readable bytes, no colors; aligned later."""
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    x = float(n)
    for u in units:
        if x < 1024.0 or u == units[-1]:
            if u == "B":
                return f"{int(x)} {u}"
            return f"{x:.1f} {u}"
        x /= 1024.0
    return f"{int(n)} B"

def compute_filtered_dir_sizes(
    source_dir: Path,
    exclude_dirs: Set[str],
    exclude_exts: Set[str],
    exclude_files: Set[str],
    remove_patterns: List[str],
    keep_patterns: List[str],
) -> Dict[Path, int]:
    """
    Return a map of directory -> cumulative size (bytes), honoring exclusions.
    """
    exclusion = Exclusion(set(exclude_dirs), set(exclude_exts), set(exclude_files), list(remove_patterns), list(keep_patterns))
    sizes: Dict[Path, int] = {}

    def should_descend(rel: str) -> bool:
        return not (rel and exclusion.dir_is_excluded(rel))

    def add_size(p: Path, sz: int) -> None:
        # bubble up to root
        while True:
            sizes[p] = sizes.get(p, 0) + sz
            if p == source_dir:
                break
            p = p.parent

    for r, dirs, files in os.walk(source_dir):
        root_path = Path(r)
        rel_dir = _relpath(root_path, source_dir)
        # prune dirs
        for d in list(dirs):
            rel_d = _relpath(root_path / d, source_dir)
            if not should_descend(rel_d):
                dirs.remove(d)
        # files
        for f in files:
            p = root_path / f
            rel = _relpath(p, source_dir)
            if exclusion.file_is_excluded(rel):
                continue
            try:
                sz = p.stat().st_size
            except OSError:
                continue
            add_size(root_path, sz)

    # Ensure every traversed (non-excluded) dir at least appears (size 0)
    for r, dirs, _ in os.walk(source_dir):
        root_path = Path(r)
        rel_dir = _relpath(root_path, source_dir)
        if should_descend(rel_dir):
            sizes.setdefault(root_path, sizes.get(root_path, 0))

    return sizes

def _gather_tree_lines_by_depth(
    root: Path,
    dir_sizes: Dict[Path, int],
    max_depth: int,
) -> List[Tuple[int, Path]]:
    """
    Collect (depth, path) entries up to max_depth for dirs present in dir_sizes.
    """
    items: List[Tuple[int, Path]] = []
    root_prefix = str(root)

    for d in sorted(dir_sizes.keys(), key=lambda p: str(p)):
        if not str(d).startswith(root_prefix):
            continue
        depth = len(d.relative_to(root).parts) if d != root else 0
        if depth <= max_depth:
            items.append((depth, d))
    # Sort by (depth, name)
    items.sort(key=lambda t: (t[0], str(t[1]).lower()))
    return items

def render_size_tree(
    source_dir: Path,
    dir_sizes: Dict[Path, int],
    depth: Optional[int] = None,
    auto_top_n: Optional[int] = None,
) -> str:
    """
    Render a size tree. If auto_top_n is provided, we pick the top-N heaviest
    directories (excluding the root), include their ancestors, then render
    up to the deepest level among those selections. Otherwise, depth-limited
    from the root (default depth=1).
    """
    if auto_top_n is not None and auto_top_n <= 0:
        return ""

    # Build a set of dirs to include
    include_dirs: Set[Path] = set()

    if auto_top_n:
        # Sort children by size (exclude the root itself for ranking)
        ranked = [(p, sz) for p, sz in dir_sizes.items() if p != source_dir]
        ranked.sort(key=lambda t: t[1], reverse=True)
        top = [p for p, _ in ranked[:auto_top_n]]

        # include ancestors for visual continuity
        for p in top:
            while True:
                include_dirs.add(p)
                if p == source_dir:
                    break
                p = p.parent
        # compute max depth we need to render
        max_depth = 0
        for p in include_dirs:
            d = len(p.relative_to(source_dir).parts) if p != source_dir else 0
            if d > max_depth:
                max_depth = d
        items = []
        for p in sorted(include_dirs, key=lambda q: (len(q.relative_to(source_dir).parts) if q != source_dir else 0, str(q).lower())):
            depth_here = len(p.relative_to(source_dir).parts) if p != source_dir else 0
            items.append((depth_here, p))
    else:
        max_depth = 1 if depth is None else max(0, depth)
        items = _gather_tree_lines_by_depth(source_dir, dir_sizes, max_depth)

    # Size column width
    size_strings = {p: _human_bytes(dir_sizes.get(p, 0)) for _, p in items}
    width = max((len(s) for s in size_strings.values()), default=0)

    # Render lines
    lines: List[str] = []
    title = "Size Tree (auto top-N)" if auto_top_n else f"Size Tree (depth={max_depth})"
    lines.append("")
    lines.append(cfmt("==", "magenta") + " " + cfmt(title, "bold"))

    for depth_i, p in items:
        name = p.name if p != source_dir else p.name or str(source_dir)
        indent = "    " * depth_i
        size_s = size_strings[p].rjust(width)
        lines.append(f"{indent}{name}/  {size_s}")

    return "\n".join(lines)


def build_preview(
    source_dir: Path,
    exclusion: Exclusion,
    *,
    flatten: bool = False,
    name_by_path: bool = False,
    max_size: Optional[int] = None,
    preferences: Optional[List[str]] = None,
    output_paths: Optional[Dict[str, str]] = None,
    preset: Optional[str] = None,
) -> Dict[str, object]:
    """Build a read-only packaging report using the packaging exclusion rules."""
    files: List[Dict[str, object]] = []
    excluded_files: List[Dict[str, str]] = []
    pruned_dirs: List[str] = []
    sizes: Dict[Path, int] = {}
    selected_dirs: List[str] = []
    source_root = source_dir.resolve()

    # Traverse explicitly so pruned subtrees are never enumerated for counts.
    stack = [source_root]
    while stack:
        folder = stack.pop()
        sizes.setdefault(folder, 0)
        if folder != source_root:
            selected_dirs.append(_relpath(folder, source_root))
        try:
            children = sorted(folder.iterdir(), key=lambda p: (not p.is_dir(), p.name.casefold(), p.name))
        except OSError:
            continue
        dirs = []
        for child in children:
            rel = _relpath(child, source_root)
            try:
                is_dir = child.is_dir()
            except OSError:
                continue
            if is_dir:
                if exclusion.dir_is_excluded(rel):
                    pruned_dirs.append(rel)
                elif child.is_symlink():
                    # os.walk's default does not recurse into directory symlinks.
                    continue
                else:
                    dirs.append(child)
            else:
                if exclusion.file_is_excluded(rel):
                    excluded_files.append({"path": rel, "reason": exclusion.exclusion_reason(rel)})
                    continue
                try:
                    size = child.stat().st_size
                except OSError as exc:
                    files.append({"path": rel, "size_bytes": None, "readable_text": False, "error": str(exc)})
                    continue
                try:
                    data = child.read_bytes()
                    data.decode("utf-8")
                    readable = True
                    error = None
                except UnicodeDecodeError:
                    readable = False
                    error = None
                except OSError as exc:
                    readable = False
                    error = str(exc)
                file_report = {"path": rel, "size_bytes": size, "readable_text": readable}
                if error:
                    file_report["error"] = error
                files.append(file_report)
                parent = child.parent
                while True:
                    sizes[parent] = sizes.get(parent, 0) + size
                    if parent == source_root:
                        break
                    parent = parent.parent
        stack.extend(reversed(dirs))

    files.sort(key=lambda item: (str(item["path"]).casefold(), str(item["path"])))
    excluded_files.sort(key=lambda item: (item["path"].casefold(), item["path"]))
    pruned_dirs.sort(key=lambda value: (value.casefold(), value))
    projected = []
    groups: Dict[str, List[str]] = {}
    for item in files:
        rel = str(item["path"])
        target = rel.replace("/", "_") if flatten and name_by_path else (Path(rel).name if flatten else rel)
        projected.append({"source": rel, "destination": target})
        if flatten:
            groups.setdefault(target.casefold(), []).append(rel)
    collisions = [
        {"destination": target, "sources": sorted(sources, key=lambda value: (value.casefold(), value))}
        for target, sources in sorted(groups.items()) if len(sources) > 1
    ]

    zip_files = list(files)
    trimmed: List[str] = []
    if max_size is not None:
        max_bytes = max_size * 1024 * 1024
        remaining = sum(int(item["size_bytes"] or 0) for item in zip_files)
        preferences_set = set(preferences or [])
        while remaining > max_bytes and zip_files:
            preferred = [item for item in zip_files if Path(str(item["path"])).suffix in preferences_set]
            candidates = preferred or zip_files
            victim = max(candidates, key=lambda item: (int(item["size_bytes"] or 0), str(item["path"]).casefold()))
            zip_files.remove(victim)
            remaining -= int(victim["size_bytes"] or 0)
            trimmed.append(str(victim["path"]))

    readable_bytes = sum(int(item["size_bytes"] or 0) for item in files if item["readable_text"])
    return {
        "version": __version__, "source": str(source_root), "preset": preset,
        "filters": {
            "exclude_dirs": sorted(exclusion.exclude_dirs, key=str.casefold),
            "exclude_extensions": sorted(exclusion.exclude_exts, key=str.casefold),
            "exclude_files": sorted(exclusion.exclude_files, key=str.casefold),
            "remove_patterns": list(exclusion.remove_patterns), "keep_patterns": list(exclusion.keep_patterns),
        },
        "modes": {"text": output_paths.get("text") if output_paths else None,
                  "zip": output_paths.get("zip") if output_paths else None,
                  "flatten": flatten, "name_by_path": name_by_path},
        "included_files": files, "included_directories": sorted(selected_dirs, key=str.casefold),
        "excluded_files": excluded_files, "pruned_directories": pruned_dirs,
        "projected_names": projected, "flatten_collisions": collisions,
        "largest_included_files": sorted(
            ({"path": str(item["path"]), "size_bytes": item["size_bytes"]} for item in files),
            key=lambda item: (-int(item["size_bytes"] or 0), str(item["path"]).casefold(), str(item["path"])),
        )[:10],
        "zip_trimmed_files": sorted(trimmed, key=lambda value: (value.casefold(), value)),
        "zip_files_after_size_trim_estimate": sorted(
            (str(item["path"]) for item in zip_files), key=lambda value: (value.casefold(), value)
        ),
        "zip_membership_stage": "selected source files before compression; size trimming is an estimate",
        "statistics": {
            "included_file_count": len(files),
            "included_source_bytes": sum(int(item["size_bytes"] or 0) for item in files),
            "excluded_file_count": len(excluded_files), "pruned_directory_count": len(pruned_dirs),
            "readable_text_file_count": sum(bool(item["readable_text"]) for item in files),
            "estimated_consolidated_text_tokens_approx": round(readable_bytes / 4),
        },
        "size_tree": sizes,
    }


def _preview_tree(source_dir: Path, report: Dict[str, object]) -> str:
    file_sizes = {str(item["path"]): item["size_bytes"] for item in report["included_files"]}
    files = set(file_sizes)
    pruned = set(report["pruned_directories"])
    directories = set(report["included_directories"])
    lines = [f"{source_dir.name}/"]
    def walk(folder: Path, prefix: str = "") -> None:
        try:
            children = sorted(folder.iterdir(), key=lambda p: (not p.is_dir(), p.name.casefold(), p.name))
        except OSError:
            return
        visible = [p for p in children if (
            _relpath(p, source_dir) in pruned or _relpath(p, source_dir) in files or
            _relpath(p, source_dir) in directories
        )]
        for index, child in enumerate(visible):
            rel = _relpath(child, source_dir)
            last = index == len(visible) - 1
            connector = "└── " if last else "├── "
            if rel in pruned:
                lines.append(f"{prefix}{connector}{child.name}/ (excluded)")
            elif child.is_dir():
                lines.append(f"{prefix}{connector}{child.name}/")
                walk(child, prefix + ("    " if last else "│   "))
            else:
                size = file_sizes.get(rel)
                lines.append(f"{prefix}{connector}{child.name} ({size if size is not None else 'unreadable'} bytes)")
    walk(source_dir)
    return "\n".join(lines)


# =====================================================================================
# CLI
# =====================================================================================

def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Preview and package a repo for LLMs; optionally run Gemini analysis.")
    p.add_argument("source", help="Source folder to package")
    p.add_argument("-o", "--output", "-O", help="Output base path (no extension needed)", default=None)

    p.add_argument("-f", "--file-mode", action="store_true", help="Write consolidated text file")
    p.add_argument("-z", "--zip-mode", action="store_true", help="Write zip file")
    p.add_argument("-d", "--dry-run", "--preview", action="store_true", help="Preview selection without creating outputs")
    p.add_argument("-l", "--list-files", action="store_true", help="List selected files and sizes in preview")
    p.add_argument("-E", "--list-excluded", action="store_true", help="List excluded files and reasons in preview")
    p.add_argument("-j", "--json", action="store_true", help="Print deterministic JSON preview")

    p.add_argument("-x", "--exclude-dir", action="append", default=[], help="Exclude directory (repeatable)")
    p.add_argument("-e", "--exclude-ext", action="append", default=[], help="Exclude extension with dot (repeatable)")
    p.add_argument("-X", "--exclude-file", action="append", default=[], help="Exclude filename (repeatable)")
    p.add_argument("-I", "--include-file", action="append", default=[], help="Force-include filename (repeatable)")
    p.add_argument("-R", "--remove-pattern", action="append", default=[], help="Remove pattern (fnmatch) (repeatable)")
    p.add_argument("-K", "--keep-pattern", action="append", default=[], help="Keep pattern (fnmatch) (repeatable)")

    p.add_argument("-m", "--max-size", type=int, default=None, help="Max zip size in MiB (best-effort)")
    p.add_argument("-p", "--preferences", default="", help="Comma list of preferred extensions to trim first")

    p.add_argument("-F", "--flatten", action="store_true", help="Flatten files into a staging dir before packaging")
    p.add_argument("-N", "--name-by-path", action="store_true", help="When flattening, rename files by path")
    p.add_argument("-v", "--verbose", action="store_true", help="Verbose progress output")

    p.add_argument("-P", "--preset", choices=sorted(PRESETS.keys()), help="Language preset (github-style)")

    p.add_argument("-G", "--gemini", action="store_true", help="Run Gemini CLI analysis on filtered workspace")
    p.add_argument("-M", "--model", default="gemini-2.5-flash", help="Gemini model")
    p.add_argument("-C", "--include-commits", action="store_true", help="Include a compact commit snapshot")
    p.add_argument("-L", "--commit-limit", type=int, default=20, help="Limit number of commits included")
    p.add_argument("-S", "--show-memory", action="store_true", help="Show memory usage in Gemini CLI")

    # New tree-size flags
    p.add_argument(
        "-T", "--size-tree",
        nargs="?", const=1, type=int, default=None,
        help="Print a directory size tree to depth (default 1 if value omitted)."
    )
    p.add_argument(
        "-A", "--auto-size-tree",
        nargs="?", const=25, type=int, default=None,
        help="Print top-N largest directories (default 25). If deeper, parents are included."
    )

    args = p.parse_args(argv)

    source_dir = Path(args.source).resolve()
    if not source_dir.is_dir():
        _print_err(f"Source is not a directory: {source_dir}")
        return 2

    # Determine what to produce
    run_file_mode = args.file_mode
    run_zip_mode = args.zip_mode
    if not run_file_mode and not run_zip_mode:
        run_zip_mode = True  # default

    # Output naming
    _raw_output = args.output
    _is_dir_target = _raw_output is not None and (
        _raw_output.endswith("/") or _raw_output.endswith("\\")
        or Path(_raw_output).is_dir()
    )
    if _raw_output is None:
        output_base = source_dir.name
    elif _is_dir_target:
        output_base = str(Path(_raw_output) / source_dir.name)
    else:
        output_base = _raw_output

    output_path = Path(output_base)
    output_dir = output_path.parent if output_path.parent != Path("") else Path.cwd()

    if output_path.name.startswith('.') and not output_path.stem.startswith('.'):
        base_name = output_path.name
    else:
        base_name = output_path.stem if output_path.stem else output_path.name

    # Build exclusion sets
    final_exclude_dirs = set(DEFAULT_EXCLUDE_DIRS)
    final_exclude_exts = set(DEFAULT_EXCLUDE_EXTS)
    final_exclude_files = set(DEFAULT_EXCLUDE_FILES)
    final_remove_patterns: List[str] = []

    if args.preset:
        ps = PRESETS[args.preset]
        final_exclude_dirs.update(ps.get("dirs", set()))
        final_exclude_exts.update(ps.get("exts", set()))
        final_exclude_files.update(ps.get("files", set()))
        final_remove_patterns.extend(ps.get("patterns", []))

    # Apply CLI excludes
    final_exclude_dirs.update(args.exclude_dir or [])
    final_exclude_exts.update(args.exclude_ext or [])
    final_exclude_files.update(args.exclude_file or [])
    final_remove_patterns.extend(args.remove_pattern or [])
    final_keep_patterns = list(args.keep_pattern or [])

    # Force-include files (remove from exclude set)
    final_exclude_files -= set(args.include_file or [])

    # Preferences list
    preferences = [s.strip() for s in (args.preferences or "").split(",") if s.strip()]

    # Create outputs
    actual_text = None
    actual_zip = None

    if run_file_mode and run_zip_mode:
        # two outputs, infer extensions if not provided
        suffix = output_path.suffix.lower()
        if suffix == ".txt":
            actual_text = output_dir / output_path.name
            actual_zip = output_dir / (base_name + ".zip")
        elif suffix == ".zip":
            actual_zip = output_dir / output_path.name
            actual_text = output_dir / (base_name + ".txt")
        else:
            actual_text = output_dir / (base_name + ".txt")
            actual_zip = output_dir / (base_name + ".zip")
    elif run_file_mode:
        actual_text = output_dir / (base_name + ".txt")
    elif run_zip_mode:
        actual_zip = output_dir / (base_name + ".zip")

    preview_mode = args.dry_run or args.list_files or args.list_excluded or args.json
    if preview_mode:
        exclusion = Exclusion(final_exclude_dirs, final_exclude_exts, final_exclude_files,
                              final_remove_patterns, final_keep_patterns)
        report = build_preview(
            source_dir, exclusion, flatten=args.flatten, name_by_path=args.name_by_path,
            max_size=args.max_size, preferences=preferences,
            output_paths={"text": str(actual_text) if actual_text else None,
                          "zip": str(actual_zip) if actual_zip else None}, preset=args.preset,
        )
        if args.size_tree is not None or args.auto_size_tree is not None:
            depth = None if args.auto_size_tree is not None else args.size_tree
            report["size_tree_report"] = render_size_tree(
                source_dir, report["size_tree"], depth=depth, auto_top_n=args.auto_size_tree
            )
        if args.json:
            report.pop("size_tree", None)
            print(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            return 0
        print(_preview_tree(source_dir, report))
        stats = report["statistics"]
        print("\nPreview statistics")
        for label, key in (
            ("Included files", "included_file_count"), ("Included source bytes", "included_source_bytes"),
            ("Excluded files", "excluded_file_count"), ("Pruned directories", "pruned_directory_count"),
            ("Readable text files", "readable_text_file_count"),
            ("Estimated consolidated-text tokens (approx.)", "estimated_consolidated_text_tokens_approx"),
        ):
            print(f"  {label}: {stats[key]}")
        print(f"  Preset: {args.preset or '(none)'}")
        print("  Effective filters:")
        print(f"    Exclude directories: {', '.join(sorted(final_exclude_dirs, key=str.casefold))}")
        print(f"    Exclude extensions: {', '.join(sorted(final_exclude_exts, key=str.casefold))}")
        print(f"    Exclude filenames: {', '.join(sorted(final_exclude_files, key=str.casefold))}")
        print(f"    Remove patterns: {', '.join(final_remove_patterns) or '(none)'}")
        print(f"    Keep patterns: {', '.join(final_keep_patterns) or '(none)'}")
        print(f"  Packaging: text={'yes' if actual_text else 'no'}, zip={'yes' if actual_zip else 'no'}, "
              f"flatten={'yes' if args.flatten else 'no'}")
        print(f"  Output paths: text={actual_text or '(none)'}, zip={actual_zip or '(none)'}")
        print(f"  Flatten name collisions: {len(report['flatten_collisions'])}")
        print("\nLargest included files")
        for item in report["largest_included_files"]:
            size = item["size_bytes"] if item["size_bytes"] is not None else "unreadable"
            print(f"  {item['path']} ({size} bytes)")
        if args.flatten:
            print("\nProjected destinations")
            for item in report["projected_names"]:
                print(f"  {item['source']} -> {item['destination']}")
            if report["flatten_collisions"]:
                print("Flatten collisions (Windows case-insensitive)")
                for collision in report["flatten_collisions"]:
                    print(f"  {collision['destination']}: {', '.join(collision['sources'])}")
        if args.max_size is not None and actual_zip:
            print(f"  ZIP files before compression: {len(report['included_files'])} selected; "
                  f"{len(report['zip_files_after_size_trim_estimate'])} estimated after size trimming")
        if args.list_files:
            print("\nIncluded files")
            for item in report["included_files"]:
                size = item["size_bytes"] if item["size_bytes"] is not None else "unreadable"
                text_state = "text" if item["readable_text"] else "binary/non-UTF-8 or unreadable"
                print(f"  {item['path']} ({size} bytes; {text_state})")
        if args.list_excluded:
            print("\nExcluded files")
            for item in report["excluded_files"]:
                print(f"  {item['path']} ({item['reason']})")
            print("Pruned directories")
            for item in report["pruned_directories"]:
                print(f"  {item}/ (directory exclusion)")
        if args.size_tree is not None or args.auto_size_tree is not None:
            print(report.get("size_tree_report", ""))
        return 0

    output_dir.mkdir(parents=True, exist_ok=True)

    if args.verbose:
        _print_header("Packaging parameters")
        _print_stat("Preset", args.preset or "(none)")
        _print_stat("Exclude dirs", str(len(final_exclude_dirs)))
        _print_stat("Exclude exts", str(len(final_exclude_exts)))
        _print_stat("Exclude files", str(len(final_exclude_files)))
        if final_remove_patterns:
            _print_stat("Remove patterns", ", ".join(final_remove_patterns))
        if final_keep_patterns:
            _print_stat("Keep patterns", ", ".join(final_keep_patterns))

    if actual_text:
        text_file_mode(
            str(source_dir), str(actual_text),
            final_exclude_dirs, final_exclude_exts, final_exclude_files,
            final_remove_patterns, final_keep_patterns,
            args.flatten, args.name_by_path, args.verbose
        )
    if actual_zip:
        zip_folder(
            str(source_dir), str(actual_zip),
            final_exclude_dirs, final_exclude_exts, final_exclude_files,
            final_remove_patterns, final_keep_patterns,
            args.max_size, preferences,
            args.flatten, args.name_by_path, args.verbose
        )

    # Gemini analysis (on a filtered workspace)
    if args.gemini:
        ws = None
        try:
            ws = prepare_analysis_workspace(
                source_dir,
                final_exclude_dirs, final_exclude_exts, final_exclude_files,
                final_remove_patterns, final_keep_patterns,
                verbose=args.verbose,
            )
            out_md = output_dir / (base_name + ".md")
            rc = run_gemini_analysis(
                filtered_workspace=ws,
                model_name=args.model,
                analysis_outfile=out_md,
                include_commits=args.include_commits,
                commit_limit=args.commit_limit,
                show_memory=args.show_memory,
                verbose=args.verbose,
            )
            if args.verbose:
                _print_stat("Gemini return code", str(rc))
        finally:
            if ws:
                shutil.rmtree(ws, ignore_errors=True)

    # --------------------------
    # Final: print size tree
    # --------------------------
    st_depth: Optional[int] = args.size_tree
    st_topn: Optional[int] = args.auto_size_tree
    if st_topn is not None:
        # auto wins if both present
        st_depth = None

    if st_depth is not None or st_topn is not None:
        sizes = compute_filtered_dir_sizes(
            source_dir,
            final_exclude_dirs, final_exclude_exts, final_exclude_files,
            final_remove_patterns, final_keep_patterns,
        )
        report = render_size_tree(source_dir, sizes, depth=st_depth, auto_top_n=st_topn)
        if report.strip():
            print(report)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
