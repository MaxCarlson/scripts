# File: scripts/pyscripts/zip_for_llms.py
#!/usr/bin/env python3
"""
zip_for_llms.py
Package a repo for LLM consumption (zip and/or consolidated text), with optional
Gemini CLI analysis over a filtered workspace and (optional) recent commit history.

Key capabilities
---------------
- Smart, repo-agnostic default ignores (VCS, caches, build artifacts, lockfiles).
- Pattern-aware exclude-dir semantics:
  * exact name (e.g., __pycache__)
  * path fragment/glob (e.g., scripts/__pycache__, analysistmp*, **/__pycache__)
- `keep_patterns` is a hard override for ANY removal rule (defaults, remove, ext, etc.).
- Text mode writes a helpful LLM preamble + folder structure + file contents.
- Zip mode supports size caps with preference-based pruning.
- Optional Gemini analysis:
  * copies repo → prunes to filtered workspace → runs Gemini CLI (non-interactive)
  * can attach recent git history as a file the model sees (commit messages + stats)
  * supports model selection: "flash" / "pro" or full model id
  * writes analysis to a file and/or embeds into text output
- Cross-platform friendly (Windows/WSL/Termux/Linux/macOS).

Dependencies
------------
- Python 3.10+
- Optional: `rich` (pretty console)
- Optional: Gemini CLI on PATH if using -G/--gemini
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import shutil
import subprocess
import sys
import textwrap
import time
import zipfile
from pathlib import Path
from typing import Iterable

# --- Pretty printing (optional) ------------------------------------------------
try:
    from rich.console import Console
    RICH_AVAILABLE = True
    console = Console()
    def rprint(*args, **kwargs):  # noqa: N802
        return console.print(*args, **kwargs)
except Exception:
    RICH_AVAILABLE = False
    def rprint(*args, **kwargs):  # noqa: N802
        if "style" in kwargs:
            kwargs.pop("style")
        print(*args, **kwargs)

# --- Defaults & Presets --------------------------------------------------------
# Broad, repo-agnostic excludes (names or globs).
DEFAULT_EXCLUDE_DIRS: set[str] = {
    # VCS / tooling
    ".git", ".hg", ".svn", ".gitlab", ".circleci",
    # Caches / venvs / IDE
    "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".idea", ".vscode", ".venv", "venv", ".tox", ".cache",
    # Node/JS
    "node_modules", ".npm", ".pnpm-store",
    # Builds / artifacts
    "build", "dist", "out", "target", ".gradle", ".next",
    # Data/analysis scratch (keep as names; user can override)
    "wandb", "mlruns",
    # Globs for temp patterns
    "analysistmp*", "tmp*", "*.egg-info",
}

# NOTE: We purposely DO NOT exclude `.log` or `.bin` by default to allow:
#  - keep/remove tests to assert behavior
#  - text mode to trigger non-UTF-8 read errors (for some tests)
DEFAULT_EXCLUDE_EXTS: set[str] = {
    ".pyc", ".pyo", ".exe", ".dll", ".o", ".so",
    ".zip", ".tar", ".gz", ".7z", ".pyd",
}

DEFAULT_EXCLUDE_FILES: set[str] = {
    "package-lock.json", "yarn.lock", "Pipfile.lock",
}

PRESETS: dict[str, dict[str, Iterable[str]]] = {
    "python": {
        "dirs": {".venv", "build", "dist", "htmlcov", ".pytest_cache", "__pycache__"},
        "patterns": ["*.egg-info"],
        "exts": {".pyd"},
        "files": {".coverage", ".coverage.*"},
    }
}

# --- Helpers: matching / filtering --------------------------------------------
def relpath_str(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except Exception:
        return path.name

def any_fnmatch(candidate: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatch(candidate, pat) for pat in patterns)

def path_matches_patterns(path: Path, root: Path, patterns: Iterable[str]) -> bool:
    """
    True if either basename OR relative path matches any glob in `patterns`.
    """
    base = path.name
    rel = relpath_str(path, root)
    return any_fnmatch(base, patterns) or any_fnmatch(rel, patterns)

def keep_overrides(path: Path, root: Path, keep_patterns: Iterable[str]) -> bool:
    """
    Hard allow: if basename OR relative path matches keep_patterns, keep it
    regardless of any exclusion rules.
    """
    if not keep_patterns:
        return False
    return path_matches_patterns(path, root, keep_patterns)

def has_keep_descendant(directory: Path, root: Path, keep_patterns: Iterable[str], depth_limit: int = 2) -> bool:
    """
    Lightweight lookahead: if removing `directory` would hide any kept entries,
    avoid pruning it. `depth_limit` keeps it cheap.
    """
    if not keep_patterns:
        return False
    try:
        queue: list[tuple[Path, int]] = [(directory, 0)]
        while queue:
            current, d = queue.pop(0)
            if keep_overrides(current, root, keep_patterns):
                return True
            if d >= depth_limit:
                continue
            for child in current.iterdir():
                if keep_overrides(child, root, keep_patterns):
                    return True
                if child.is_dir():
                    queue.append((child, d + 1))
        return False
    except Exception:
        return False

def should_exclude_file(
    file_path: Path,
    root: Path,
    exclude_dirs: set[str],
    exclude_exts: set[str],
    exclude_files: set[str],
    remove_patterns: list[str],
    keep_patterns: list[str]
) -> bool:
    """
    Decide whether to exclude a file. `keep_patterns` wins over all rules.
    """
    if keep_overrides(file_path, root, keep_patterns):
        return False

    # Directory ancestors excluded? (path fragment or name)
    for parent in file_path.parents:
        # stop at FS root
        if str(parent) == parent.anchor:
            break
        if any_fnmatch(parent.name, exclude_dirs) or path_matches_patterns(parent, root, exclude_dirs):
            return True
        if path_matches_patterns(parent, root, remove_patterns):
            return True

    if file_path.suffix in exclude_exts:
        return True
    if file_path.name in exclude_files or any_fnmatch(file_path.name, exclude_files):
        return True
    if path_matches_patterns(file_path, root, remove_patterns):
        return True
    return False

def filter_dirs_inplace(
    root: Path,
    current_root: Path,
    dirnames: list[str],
    exclude_dirs: set[str],
    remove_patterns: list[str],
    keep_patterns: list[str],
) -> None:
    """
    Mutate `dirnames` so os.walk prunes excluded dirs. `keep_patterns` may rescue
    directories that would otherwise be pruned if they contain keeper descendants.
    """
    for d in list(dirnames):
        dpath = current_root / d
        # keep overrides on the dir itself
        if keep_overrides(dpath, root, keep_patterns):
            continue
        # default or remove-based pruning decisions:
        default_match = (d in exclude_dirs) or any_fnmatch(d, exclude_dirs) or path_matches_patterns(dpath, root, exclude_dirs)
        remove_match = path_matches_patterns(dpath, root, remove_patterns)

        if default_match or remove_match:
            if has_keep_descendant(dpath, root, keep_patterns):
                continue
            dirnames.remove(d)

# --- Utility ------------------------------------------------------------------
def get_directory_size(directory: Path) -> int:
    return sum(f.stat().st_size for f in directory.rglob("*") if f.is_file())

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
        # Don't recurse into the target dir
        if root_path == flat_dest_path:
            dirs[:] = []
            continue
        # always skip known defaults within flatten op
        dirs[:] = [d for d in dirs if d not in DEFAULT_EXCLUDE_DIRS and d != flat_dir_name]
        if root_path.name in DEFAULT_EXCLUDE_DIRS and root_path != source_dir:
            continue

        for fn in files:
            original = root_path / fn
            # honor default file-level excludes here
            if original.suffix in DEFAULT_EXCLUDE_EXTS or fn in DEFAULT_EXCLUDE_FILES:
                if verbose:
                    rprint(f"  [dim yellow]Skipping (default rule):[/dim yellow] {original.relative_to(source_dir)}")
                continue
            if original.parent == flat_dest_path:
                continue

            if name_by_path:
                try:
                    rel = original.relative_to(source_dir)
                    new_name = "_".join(rel.parts)
                except Exception:
                    new_name = fn
            else:
                new_name = fn

            dest = flat_dest_path / new_name
            if dest != original:
                shutil.move(str(original), str(dest))
                moved_count += 1

    rprint(f"[green]Flattened {moved_count} files into {flat_dest_path}.[/green]")
    return flat_dest_path

def delete_files_to_fit_size(
    directory_to_prune: Path,
    target_zip_size_mb: int,
    preferences: list[str],
    verbose: bool
) -> list[str]:
    target_bytes = target_zip_size_mb * 1024 * 1024
    current = get_directory_size(directory_to_prune)
    if current <= target_bytes:
        if verbose:
            rprint(
                f"Directory '{directory_to_prune}' size ({current/(1024*1024):.2f}MB) "
                f"is already below heuristic target ({target_zip_size_mb}MB).",
                style="dim"
            )
        return []

    if verbose:
        rprint(
            f"Attempting to reduce source directory [cyan]'{directory_to_prune.name}'[/cyan] size... "
            f"Current: {current/(1024*1024):.2f} MB. Target: {target_zip_size_mb} MB"
        )

    all_files = sorted(
        (f for f in directory_to_prune.rglob("*") if f.is_file()),
        key=lambda f: f.stat().st_size,
        reverse=True,
    )

    ordered: list[Path] = []
    for ext in preferences:
        ordered.extend([f for f in all_files if f.suffix == ext and f not in ordered])
    ordered.extend([f for f in all_files if f not in ordered])

    removed: list[str] = []
    if verbose and ordered:
        rprint("  [bold yellow]Pruning files:[/bold yellow]")

    for f in ordered:
        if current <= target_bytes:
            break
        try:
            size = f.stat().st_size
            f.unlink()
            removed.append(str(f))
            current -= size
            if verbose:
                rprint(
                    f"    - [red]Pruned:[/red] {f.name} ({size/(1024*1024):.2f}MB). "
                    f"Now: {current/(1024*1024):.2f}MB"
                )
        except OSError as e:
            rprint(f"  [yellow]Warning:[/yellow] Could not delete {f}: {e}")
    if verbose:
        if current <= target_bytes:
            rprint(f"  [green]Pruned {len(removed)} files.[/green]")
        else:
            rprint(
                f"  [yellow]Warning:[/yellow] After pruning {len(removed)} files, dir size "
                f"{current/(1024*1024):.2f}MB still above target."
            )
    return removed

# --- Core: zip mode -----------------------------------------------------------
def zip_folder(
    source_dir_str: str,
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
    verbose: bool
) -> None:
    src_path = Path(source_dir_str).resolve()
    output_zip_path = Path(output_zip_str).resolve()

    temp_prune_copy: Path | None = None
    temp_flatten_root: Path | None = None

    # Prepare working tree
    if flatten:
        temp_flatten_root = src_path.parent / f"_temp_flatten_{src_path.name}_{int(time.time())}"
        shutil.copytree(src_path, temp_flatten_root, dirs_exist_ok=True)
        working = flatten_directory(temp_flatten_root, name_by_path, verbose)
        if verbose:
            rprint(f"Flatten mode: zipping from [cyan]{working}[/cyan]")
    elif max_size is not None:
        temp_prune_copy = src_path.parent / f"_temp_zip_src_{src_path.name}_{int(time.time())}"
        shutil.copytree(src_path, temp_prune_copy, dirs_exist_ok=True)
        working = temp_prune_copy
        if verbose:
            rprint(f"Max-size pruning: working from [cyan]{working}[/cyan]")
    else:
        working = src_path

    if not working.exists():
        rprint(f"[red]Error:[/red] Working directory '{working}' does not exist. Aborting.")
        if temp_flatten_root and temp_flatten_root.exists():
            shutil.rmtree(temp_flatten_root)
        if temp_prune_copy and temp_prune_copy.exists():
            shutil.rmtree(temp_prune_copy)
        return

    # Helpful structure file for downstream LLMs
    structure_file = working / "folder_structure.txt"
    with structure_file.open("w", encoding="utf-8") as f:
        f.write(f"Folder Structure for: {src_path.name}\n")
        lines: list[str] = []
        for root, dirs, _ in os.walk(src_path, topdown=True):
            rootp = Path(root)
            filter_dirs_inplace(src_path, rootp, dirs, exclude_dirs, remove_patterns, keep_patterns)
            rel = rootp.relative_to(src_path)
            indent = "    " * len(rel.parts)
            name = rootp.name if rootp != src_path else src_path.name
            lines.append(f"{indent}{name}/\n")
        for line in lines:
            f.write(line)
    if verbose:
        rprint(f"Wrote [magenta]{structure_file.name}[/magenta] in [cyan]{structure_file.parent}[/cyan]")

    # Iterative prune if necessary
    while True:
        files_in_zip = 0
        output_zip_path.parent.mkdir(parents=True, exist_ok=True)
        if verbose:
            rprint(f"\n[bold blue]Creating zip '{output_zip_path.name}'[/bold blue]")
        with zipfile.ZipFile(output_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(working, topdown=True):
                rootp = Path(root)
                filter_dirs_inplace(working, rootp, dirs, exclude_dirs, remove_patterns, keep_patterns)

                for fn in files:
                    fp = rootp / fn
                    rel_display = fp.relative_to(working)

                    # keep overrides everything
                    if keep_overrides(fp, working, keep_patterns):
                        zf.write(fp, rel_display)
                        files_in_zip += 1
                        if verbose:
                            rprint(f"  + [green]Added (keep):[/green] {rel_display}")
                        continue

                    if should_exclude_file(fp, working, exclude_dirs, exclude_exts, exclude_files, remove_patterns, keep_patterns):
                        if verbose:
                            rprint(f"  - [yellow]Skipping:[/yellow] {rel_display}")
                        continue

                    zf.write(fp, rel_display)
                    files_in_zip += 1
                    if verbose:
                        rprint(f"  + [green]Added:[/green] {rel_display}")

        if verbose:
            rprint(f"Total files zipped: {files_in_zip}")

        size_mb = output_zip_path.stat().st_size / (1024 * 1024)
        if max_size is None or size_mb <= max_size:
            rprint(f"\n[bold green]Final zip '{output_zip_path.name}' size: {size_mb:.2f} MB[/bold green]")
            break

        if verbose:
            rprint(f"\n[bold yellow]Zip too large ({size_mb:.2f} > {max_size}). Pruning...[/bold yellow]")
        deleted = delete_files_to_fit_size(working, max_size, preferences, verbose)
        if not deleted:
            rprint(
                f"[yellow]Warning:[/yellow] No files deleted during pruning, but zip still too big. "
                "Check pruning preferences or max-size."
            )
            break

    # Cleanup
    for tmp in (temp_prune_copy, temp_flatten_root):
        if tmp and tmp.exists():
            try:
                shutil.rmtree(tmp)
                if verbose:
                    rprint(f"Cleaned temp: [cyan]{tmp}[/cyan]", style="dim")
            except OSError as e:
                rprint(f"[yellow]Warning:[/yellow] Could not remove temp '{tmp}': {e}")

# --- Core: text mode ----------------------------------------------------------
def preamble_for_llm(repo_name: str) -> str:
    return textwrap.dedent(f"""\
    This document packages a repository for a Large Language Model (LLM).
    It contains a high-level folder structure followed by selected file contents.
    Goal: give the model enough structure to understand intent, architecture,
    and primary workflows without overwhelming it with binary/output noise.

    Repo: {repo_name}

    Reading order:
    1) Folder structure to build a mental map.
    2) Key files and source content (omitting caches, builds, lockfiles, etc.).
    3) Optional sections: commit history summaries and Gemini analysis.

    Notes:
    - Paths are relative to the repository root.
    - Some large/generated files may be intentionally excluded.
    - If a file cannot be decoded as UTF-8, it is skipped.
    ---
    """)

def text_file_mode(
    source_dir_str: str,
    output_file_str: str,
    exclude_dirs: set[str],
    exclude_exts: set[str],
    exclude_files: set[str],
    remove_patterns: list[str],
    keep_patterns: list[str],
    flatten_mode: bool,
    name_by_path: bool,
    verbose: bool
) -> None:
    src_path = Path(source_dir_str).resolve()
    out_path = Path(output_file_str).resolve()

    temp_flatten_root: Path | None = None
    working = src_path

    if flatten_mode:
        temp_flatten_root = src_path.parent / f"_temp_text_flatten_{src_path.name}_{int(time.time())}"
        shutil.copytree(src_path, temp_flatten_root, dirs_exist_ok=True)
        working = flatten_directory(temp_flatten_root, name_by_path, verbose)
        if verbose:
            rprint(f"Text flatten: [cyan]{working}[/cyan]")

    files_processed = 0
    files_added = 0
    skipped: list[str] = []
    structure_lines: list[str] = []

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as out:
        out.write(preamble_for_llm(src_path.name))

        if verbose:
            rprint("[bold blue]Generating folder structure...[/bold blue]")
        out.write(f"Folder Structure for: {src_path.name}\n")
        for root, dirs, _ in os.walk(src_path, topdown=True):
            rootp = Path(root)
            filter_dirs_inplace(src_path, rootp, dirs, exclude_dirs, remove_patterns, keep_patterns)
            rel = rootp.relative_to(src_path)
            indent = "    " * len(rel.parts)
            name = rootp.name if rootp != src_path else src_path.name
            structure_lines.append(f"{indent}{name}/\n")
        out.writelines(structure_lines)
        out.write("\n--- End of Folder Structure ---\n")

        if verbose:
            rprint(f"\n[bold blue]Processing files for '{out_path.name}'...[/bold blue]")

        for root, dirs, files in os.walk(working, topdown=True):
            rootp = Path(root)
            filter_dirs_inplace(working, rootp, dirs, exclude_dirs, remove_patterns, keep_patterns)

            for fn in files:
                files_processed += 1
                fp = rootp / fn

                # Display path for flattened vs normal
                if flatten_mode:
                    display_rel = fn
                else:
                    try:
                        display_rel = str(fp.relative_to(src_path))
                    except Exception:
                        display_rel = fn

                # keep overrides everything
                if keep_overrides(fp, working, keep_patterns):
                    out.write(f"\n-- File: {display_rel} --\n")
                    try:
                        content = fp.read_text(encoding="utf-8")
                        out.write(content)
                        if not content.endswith("\n"):
                            out.write("\n")
                        files_added += 1
                        if verbose:
                            rprint(f"  + [green]Added (keep):[/green] {display_rel}")
                    except UnicodeDecodeError:
                        msg = f"{display_rel} (binary or non-UTF-8 content)"
                        skipped.append(msg)
                        if verbose:
                            rprint(f"  - [yellow]Skipping (read error):[/yellow] {msg}")
                    except Exception as e:
                        msg = f"{display_rel} (read error: {e})"
                        skipped.append(msg)
                        if verbose:
                            rprint(f"  - [yellow]Skipping (read error):[/yellow] {msg}")
                    continue

                if should_exclude_file(fp, working, exclude_dirs, exclude_exts, exclude_files, remove_patterns, keep_patterns):
                    msg = f"{display_rel} (excluded)"
                    skipped.append(msg)
                    if verbose:
                        rprint(f"  - [yellow]Skipping:[/yellow] {msg}")
                    continue

                out.write(f"\n-- File: {display_rel} --\n")
                try:
                    content = fp.read_text(encoding="utf-8")
                    out.write(content)
                    if not content.endswith("\n"):
                        out.write("\n")
                    files_added += 1
                    if verbose:
                        rprint(f"  + [green]Added:[/green] {display_rel}")
                except UnicodeDecodeError:
                    msg = f"{display_rel} (binary or non-UTF-8 content)"
                    skipped.append(msg)
                    if verbose:
                        rprint(f"  - [yellow]Skipping (read error):[/yellow] {msg}")
                except Exception as e:
                    msg = f"{display_rel} (read error: {e})"
                    skipped.append(msg)
                    if verbose:
                        rprint(f"  - [yellow]Skipping (read error):[/yellow] {msg}")

    if temp_flatten_root and temp_flatten_root.exists():
        try:
            shutil.rmtree(temp_flatten_root)
            if verbose:
                rprint(f"Cleaned text temp: [cyan]{temp_flatten_root}[/cyan]", style="dim")
        except OSError as e:
            rprint(f"[yellow]Warning:[/yellow] Could not clean temp {temp_flatten_root}: {e}")

    rprint(f"\n[bold green]Text file complete: {out_path.name}[/bold green]")
    rprint(f"Total files encountered: {files_processed}")
    rprint(f"Files added to text: {files_added}")
    if skipped:
        rprint(f"Files skipped from content: {len(skipped)}")
        if verbose:
            rprint("  [bold yellow]Skipped details:[/bold yellow]")
            for s in skipped:
                rprint(f"    - {s}")

# --- Gemini integration (non-interactive CLI) ---------------------------------
def _map_gemini_model(user_value: str | None) -> str:
    """
    Accepts 'flash' / 'pro' shortcuts or full model ids. Defaults to flash.
    """
    if not user_value:
        return "gemini-2.5-flash"
    v = user_value.strip().lower()
    if v in {"flash", "gemini-2.5-flash"}:
        return "gemini-2.5-flash"
    if v in {"pro", "gemini-2.5-pro"}:
        return "gemini-2.5-pro"
    return user_value  # allow future models

def _git_commit_snapshot(repo_root: Path, limit: int | None) -> str:
    """
    Return a concise commit history (messages + stats). If git is missing or
    not a repo, return empty string.
    """
    try:
        subprocess.run(["git", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    except Exception:
        return ""

    try:
        args = ["git", "-C", str(repo_root), "log", "--date=relative",
                "--pretty=format:%h %ad %an — %s", "--name-only", "--stat"]
        if limit and limit > 0:
            args.extend(["-n", str(limit)])
        cp = subprocess.run(args, capture_output=True, text=True, check=True)
        return cp.stdout.strip()
    except Exception:
        return ""

def prepare_analysis_workspace(  # <-- added for tests & reuse
    source_dir: str | Path,
    exclude_dirs: set[str],
    exclude_exts: set[str],
    exclude_files: set[str],
    remove_patterns: list[str],
    keep_patterns: list[str],
    verbose: bool = False
) -> Path:
    """
    Create a temporary filtered workspace by copying the repo and pruning according
    to the same rules used during packaging. `keep_patterns` overrides deletions.
    Returns the Path to the workspace directory.
    """
    src = Path(source_dir).resolve()
    ws = src.parent / f"_gemini_ws_{src.name}_{int(time.time())}"
    shutil.copytree(src, ws, dirs_exist_ok=True)

    # prune in-place
    for root, dirs, files in os.walk(ws, topdown=True):
        rootp = Path(root)
        # prune dirs
        to_remove: list[Path] = []
        for d in list(dirs):
            dpath = rootp / d
            if keep_overrides(dpath, ws, keep_patterns):
                continue
            default_match = (d in exclude_dirs) or any_fnmatch(d, exclude_dirs) or path_matches_patterns(dpath, ws, exclude_dirs)
            remove_match = path_matches_patterns(dpath, ws, remove_patterns)
            if default_match or remove_match:
                if not has_keep_descendant(dpath, ws, keep_patterns):
                    to_remove.append(dpath)
                    dirs.remove(d)
        for dpath in to_remove:
            try:
                shutil.rmtree(dpath, ignore_errors=True)
                if verbose:
                    rprint(f"[dim]Removed dir:[/dim] {dpath}")
            except Exception:
                pass

        # prune files
        for fn in list(files):
            fpath = rootp / fn
            if keep_overrides(fpath, ws, keep_patterns):
                continue
            if should_exclude_file(fpath, ws, exclude_dirs, exclude_exts, exclude_files, remove_patterns, keep_patterns):
                try:
                    fpath.unlink()
                    if verbose:
                        rprint(f"[dim]Removed file:[/dim] {fpath}")
                except Exception:
                    pass

    if verbose:
        rprint(f"[green]Prepared analysis workspace:[/green] [cyan]{ws}[/cyan]")
    return ws

def run_gemini_analysis(
    filtered_workspace: Path,
    model_name: str,
    analysis_outfile: Path,
    include_commits: bool,
    commit_limit: int | None,
    show_memory: bool,
    verbose: bool
) -> int:
    """
    Launch Gemini CLI in non-interactive mode (`-p`) with `--all-files`,
    capture stdout to `analysis_outfile`. Returns process return code.
    """
    prompt_intro = textwrap.dedent("""\
    You are analyzing a software repository snapshot. Produce a concise, high-signal brief:
    - Overall purpose and primary components
    - Build/test/run "golden path" commands
    - Key configs and env requirements
    - Notable risks (security, perf, correctness), large TODO clusters
    - If commit file is present, summarize recent changes (group by feature/fix/refactor/breaking)
    Keep it under ~800-1200 words. Use Markdown headings and bullet points.
    """)

    # Optionally add a commit snapshot file the model will see
    commit_file: Path | None = None
    if include_commits:
        snapshot = _git_commit_snapshot(filtered_workspace, commit_limit)
        if snapshot:
            commit_file = filtered_workspace / "COMMIT_HISTORY_FOR_LLM.md"
            commit_file.write_text(snapshot, encoding="utf-8")

    args = [
        "gemini",
        "-m", model_name,
        "-p", prompt_intro,         # non-interactive single prompt
        "--all-files",              # include workspace files in context
    ]
    if show_memory:
        args.append("--show-memory-usage")

    if verbose:
        rprint(f"[bold blue]Running Gemini CLI:[/bold blue] {' '.join(a if ' ' not in a else repr(a) for a in args)}")

    try:
        cp = subprocess.run(args, cwd=str(filtered_workspace), capture_output=True, text=True)
        analysis_outfile.parent.mkdir(parents=True, exist_ok=True)
        analysis_outfile.write_text(cp.stdout or "", encoding="utf-8")
        if cp.returncode != 0:
            rprint(f"[yellow]Gemini CLI exited with {cp.returncode}[/yellow]")
            if cp.stderr:
                rprint(cp.stderr)
        else:
            if verbose:
                rprint(f"[green]Gemini analysis saved to[/green] [cyan]{analysis_outfile}[/cyan]")
        return cp.returncode
    finally:
        pass

# --- CLI ----------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Package a folder for LLMs (zip and/or text) with optional Gemini analysis.")

    # NOTE: Every short option is a single letter (requirement).
    p.add_argument("-S", "--source", required=True, help="Folder to process")
    p.add_argument("-O", "--output", required=True, help="Base output path (e.g., 'out' or 'out.zip' or 'out.txt')")

    m = p.add_argument_group("Output Modes")
    m.add_argument("-T", "--text", action="store_true", help="Produce one consolidated text file")
    m.add_argument("-Z", "--zip", action="store_true", help="Produce a zip file (default if no mode specified)")

    f = p.add_argument_group("Filtering and Exclusion")
    f.add_argument("-D", "--exclude-dir", nargs="*", default=list(DEFAULT_EXCLUDE_DIRS),
                   help="Directory names/path globs to exclude. Matches basename OR relative path.")
    f.add_argument("-E", "--exclude-ext", nargs="*", default=list(DEFAULT_EXCLUDE_EXTS),
                   help="File extensions to exclude (e.g., .o .so)")
    f.add_argument("-x", "--exclude-file", nargs="*", default=list(DEFAULT_EXCLUDE_FILES),
                   help="Specific filenames to exclude (exact or glob)")
    f.add_argument("-i", "--include-file", nargs="*", default=[],
                   help="Force-include specific filenames (overrides exclude-file)")
    f.add_argument("-r", "--remove-patterns", nargs="*", default=[],
                   help="Glob patterns applied to file/dir basenames AND relative paths to remove")
    f.add_argument("-k", "--keep-patterns", nargs="*", default=[],
                   help="Glob patterns that override ALL removals (checked against basename and relative path)")
    f.add_argument("-P", "--preset", choices=PRESETS.keys(), help="Language/framework preset (e.g., python)")

    z = p.add_argument_group("Zip Options")
    z.add_argument("-m", "--max-size", type=int, help="Max zip size in MB; prunes working copy if exceeded")
    z.add_argument("-c", "--preferences", nargs="*", default=[],
                   help="Preferred file extensions to delete first when pruning (e.g., .log .dat)")

    fmt = p.add_argument_group("Formatting Options")
    fmt.add_argument("-a", "--flatten", action="store_true", help="Flatten directory structure before packaging")
    fmt.add_argument("-n", "--name-by-path", action="store_true", help="In flatten mode, include original path in filename")

    g = p.add_argument_group("Gemini Analysis (optional)")
    g.add_argument("-G", "--gemini", action="store_true", help="Run Gemini analysis over a filtered workspace")
    g.add_argument("-g", "--gemini-model", default="flash",
                   help="Model: 'flash' or 'pro' (or full model name, e.g., gemini-2.5-pro). Default: flash.")
    g.add_argument("-C", "--gemini-commits-analyze", action="store_true", help="Include recent commit history snapshot for analysis")
    g.add_argument("-l", "--gemini-commits-limit", type=int, default=0, help="Limit number of commits (0 = unlimited)")
    g.add_argument("-U", "--gemini-output", default="", help="Write Gemini analysis here (defaults to '<base>-gemini.md')")
    g.add_argument("-W", "--gemini-keep-workspace", action="store_true", help="Keep temporary filtered workspace (for debugging)")

    p.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    return p

def main(argv: list[str] | None = None) -> int:
    if not RICH_AVAILABLE:
        print("Warning: 'rich' not found. Output will be basic. Install with: pip install rich\n")

    parser = build_parser()
    args = parser.parse_args(argv)

    # Modes default: zip if neither specified
    run_text = args.text
    run_zip = args.zip or not run_text

    # --- Apply presets and finalize lists ---
    final_exclude_files = set(args.exclude_file) - set(args.include_file)
    final_exclude_dirs = set(args.exclude_dir)
    final_exclude_exts = set(args.exclude_ext)
    final_remove_patterns = list(args.remove_patterns)
    final_keep_patterns = list(args.keep_patterns)

    if args.preset:
        preset = PRESETS[args.preset]
        final_exclude_dirs.update(preset.get("dirs", set()))
        final_exclude_exts.update(preset.get("exts", set()))
        final_exclude_files.update(preset.get("files", set()))
        final_remove_patterns.extend(preset.get("patterns", []))
        if args.verbose:
            rprint(f"[bold cyan]Applied preset '{args.preset}'[/bold cyan]")

    # Resolve outputs
    output_path_arg = Path(args.output)
    output_dir = output_path_arg.parent if output_path_arg.parent != Path("") else Path(".")
    output_dir.mkdir(parents=True, exist_ok=True)

    if output_path_arg.name.startswith(".") and not output_path_arg.stem.startswith("."):
        base_name = output_path_arg.name
    else:
        base_name = output_path_arg.stem if output_path_arg.stem else output_path_arg.name

    text_out: Path | None = None
    zip_out: Path | None = None

    if run_text and run_zip:
        suf = output_path_arg.suffix.lower()
        if suf == ".txt":
            text_out = output_path_arg
            zip_out = output_dir / (base_name + ".zip")
        elif suf == ".zip":
            zip_out = output_path_arg
            text_out = output_dir / (base_name + ".txt")
        else:
            if suf and args.verbose:
                rprint(f"[yellow]Warning:[/yellow] Unrecognized extension '{suf}'. Using both .txt and .zip.")
            text_out = output_dir / (base_name + ".txt")
            zip_out = output_dir / (base_name + ".zip")
    elif run_text:
        if output_path_arg.suffix.lower() == ".txt":
            text_out = output_path_arg
        else:
            if output_path_arg.suffix and args.verbose:
                rprint(f"[yellow]Warning:[/yellow] '{output_path_arg.suffix}' ignored; using '.txt'.")
            text_out = output_dir / (base_name + ".txt")
    else:  # run_zip only
        if output_path_arg.suffix.lower() == ".zip":
            zip_out = output_path_arg
        else:
            if output_path_arg.suffix and args.verbose:
                rprint(f"[yellow]Warning:[/yellow] '{output_path_arg.suffix}' ignored; using '.zip'.")
            zip_out = output_dir / (base_name + ".zip")

    # Execute modes
    if text_out:
        rprint(f"[bold magenta]Starting text mode →[/bold magenta] [cyan]{text_out}[/cyan]")
        text_file_mode(
            args.source, str(text_out),
            final_exclude_dirs, final_exclude_exts, final_exclude_files,
            final_remove_patterns, final_keep_patterns,
            args.flatten, args.name_by_path, args.verbose
        )

    if zip_out:
        rprint(f"[bold magenta]Starting zip mode →[/bold magenta] [cyan]{zip_out}[/cyan]")
        zip_folder(
            args.source, str(zip_out),
            final_exclude_dirs, final_exclude_exts, final_exclude_files,
            final_remove_patterns, final_keep_patterns,
            args.max_size, args.preferences,
            args.flatten, args.name_by_path, args.verbose
        )

    # --- Optional Gemini analysis --------------------------------------------
    if args.gemini:
        # Build filtered workspace via exported helper used by tests as well
        ws = prepare_analysis_workspace(
            args.source,
            final_exclude_dirs, final_exclude_exts, final_exclude_files,
            final_remove_patterns, final_keep_patterns,
            verbose=args.verbose
        )

        # Commit snapshot & model selection
        model = _map_gemini_model(args.gemini_model)
        output_dir.mkdir(parents=True, exist_ok=True)
        out_md = Path(args.gemini_output) if args.gemini_output else (output_dir / f"{base_name}-gemini.md")
        rc = run_gemini_analysis(
            ws, model, out_md,
            include_commits=args.gemini_commits_analyze,
            commit_limit=(args.gemini_commits_limit or None),
            show_memory=args.verbose,
            verbose=args.verbose
        )

        # If we produced a text output, append Gemini analysis for convenience
        if text_out and out_md.exists():
            try:
                with text_out.open("a", encoding="utf-8") as ftxt, out_md.open("r", encoding="utf-8") as fan:
                    ftxt.write("\n\n---\n## Gemini Analysis\n\n")
                    ftxt.write(fan.read())
                if args.verbose:
                    rprint(f"[green]Appended Gemini analysis to[/green] [cyan]{text_out}[/cyan]")
            except Exception as e:
                rprint(f"[yellow]Warning:[/yellow] Could not append Gemini analysis to text output: {e}")

        # Cleanup workspace unless asked to keep
        if not args.gemini_keep_workspace:
            try:
                shutil.rmtree(ws)
            except Exception:
                pass

        # If Gemini printed help instead of running, rc may be non-zero or output empty.
        # We use '-p' non-interactive prompt and only pass supported flags to avoid the
        # earlier interactive/alias issues.
        if rc != 0:
            return rc

    return 0

# --- Entry --------------------------------------------------------------------
if __name__ == "__main__":
    raise SystemExit(main())
