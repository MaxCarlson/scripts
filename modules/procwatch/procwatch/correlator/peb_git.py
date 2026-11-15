"""Live CWD, PE subsystem inspection, and Git repo/worktree/branch resolution."""

from __future__ import annotations

import os
import struct
from pathlib import Path

from procwatch.models import GitContext

_IMAGE_SUBSYSTEM_NATIVE = 1
_IMAGE_SUBSYSTEM_WINDOWS_GUI = 2
_IMAGE_SUBSYSTEM_WINDOWS_CUI = 3


def read_pe_subsystem(image_path: str | Path | None) -> str | None:
    """Read the PE OptionalHeader Subsystem ('CUI', 'GUI', 'NATIVE', ...) from an executable."""
    if not image_path:
        return None
    path = Path(image_path)
    try:
        with path.open("rb") as fh:
            dos_header = fh.read(64)
            if len(dos_header) < 64 or dos_header[:2] != b"MZ":
                return None
            e_lfanew = struct.unpack_from("<I", dos_header, 0x3C)[0]
            fh.seek(e_lfanew)
            pe_sig = fh.read(4)
            if pe_sig != b"PE\x00\x00":
                return None
            coff_header = fh.read(20)
            if len(coff_header) < 20:
                return None
            opt_size = struct.unpack_from("<H", coff_header, 16)[0]
            if opt_size < 70:
                return None
            opt_header = fh.read(min(opt_size, 96))
            if len(opt_header) < 70:
                return None
            magic = struct.unpack_from("<H", opt_header, 0)[0]
            if magic not in (0x10B, 0x20B):
                return None
            subsystem = struct.unpack_from("<H", opt_header, 68)[0]
    except (OSError, struct.error, ValueError):
        return None

    if subsystem == _IMAGE_SUBSYSTEM_WINDOWS_CUI:
        return "CUI"
    if subsystem == _IMAGE_SUBSYSTEM_WINDOWS_GUI:
        return "GUI"
    if subsystem == _IMAGE_SUBSYSTEM_NATIVE:
        return "NATIVE"
    return f"SUBSYSTEM_{subsystem}"


def read_process_cwd(pid: int) -> str | None:
    """Best-effort live CWD lookup for an active PID."""
    try:
        import psutil  # type: ignore[import-untyped]

        return psutil.Process(pid).cwd()
    except Exception:
        return None


def _parse_head_branch(git_dir: Path) -> tuple[str | None, str | None]:
    head_path = git_dir / "HEAD"
    try:
        head_text = head_path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None, None
    if head_text.startswith("ref: "):
        ref = head_text[5:].strip()
        if ref.startswith("refs/heads/"):
            return ref[len("refs/heads/") :], None
        return ref, None
    if head_text:
        return None, head_text[:12]
    return None, None


def resolve_git_context(
    path: str | Path | None,
    *,
    cache: dict[str, GitContext | None] | None = None,
) -> GitContext | None:
    """Resolve Git repository root, worktree path, and current branch purely from .git metadata."""
    if not path:
        return None
    try:
        start = Path(os.path.abspath(str(path)))
    except OSError:
        return None
    if start.is_file():
        start = start.parent

    cache_key = str(start).lower()
    if cache is not None and cache_key in cache:
        return cache[cache_key]

    current = start
    result: GitContext | None = None
    for _ in range(32):
        dot_git = current / ".git"
        if dot_git.is_dir() and (dot_git / "HEAD").is_file():
            branch, commit = _parse_head_branch(dot_git)
            result = GitContext(
                repo_root=str(current),
                worktree_path=str(current),
                branch=branch,
                commit=commit,
            )
            break
        if dot_git.is_file():
            try:
                content = dot_git.read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                content = ""
            if content.lower().startswith("gitdir:"):
                raw_gitdir = content.split(":", 1)[1].strip()
                git_dir = Path(raw_gitdir)
                if not git_dir.is_absolute():
                    git_dir = (current / git_dir).resolve()
                branch, commit = _parse_head_branch(git_dir)
                repo_root = str(current)
                commondir_file = git_dir / "commondir"
                if commondir_file.is_file():
                    try:
                        rel_common = commondir_file.read_text(encoding="utf-8").strip()
                        common_dir = (git_dir / rel_common).resolve()
                        if common_dir.name.lower() == ".git":
                            repo_root = str(common_dir.parent)
                    except OSError:
                        pass
                result = GitContext(
                    repo_root=repo_root,
                    worktree_path=str(current),
                    branch=branch,
                    commit=commit,
                )
                break
        parent = current.parent
        if parent == current:
            break
        current = parent

    if cache is not None:
        cache[cache_key] = result
    return result
