from __future__ import annotations

"""
Disk space scanning and cleanup utilities for file_utils.

Implements cross-platform operations guided by modules/file_utils/todo-disk-space-task.md.
All system detection and command execution is routed through cross_platform.SystemUtils.

Public functions return plain data structures or raise ValueError for bad inputs.
Destructive operations support dry-run and require explicit confirmation from the caller.
"""

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from cross_platform.system_utils import SystemUtils
from cross_platform.size_utils import parse_size_to_bytes, format_bytes_binary


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FileEntry:
    path: str
    size_bytes: int


@dataclass(frozen=True)
class DirEntry:
    path: str
    size_human: str


def _default_scan_root(sysu: SystemUtils, requested: Optional[str]) -> Path:
    if requested:
        return Path(requested).expanduser().resolve()
    # Defaults per platform
    if sysu.is_windows():
        return Path(os.environ.get("USERPROFILE", str(Path.home())))
    if sysu.is_termux():
        return Path.home()  # avoid /sdcard by default
    if sysu.is_wsl2():
        return Path("/")  # WSL scans can include rootfs
    if sysu.is_linux():
        return Path("/")
    return Path.home()


def scan_largest_files(sysu: SystemUtils, path: Optional[str], top_n: int, min_size: Optional[str]) -> List[FileEntry]:
    """
    Return top-N largest files at or under `path` (platform-specific defaults if None).
    Uses platform-native tools for speed; falls back to Python if necessary.
    """
    root = _default_scan_root(sysu, path)
    min_bytes = parse_size_to_bytes(min_size) or 0

    logger.debug("scan_largest_files: root=%s top_n=%s min=%s", root, top_n, min_bytes)

    entries: List[FileEntry] = []
    if sysu.is_windows():
        # PowerShell pipeline for performance
        cmd = (
            "pwsh -NoProfile -Command "
            "Get-ChildItem -File -Recurse -ErrorAction SilentlyContinue '" + str(root) + "' | "
            "Where-Object { $_.Length -ge %d } | "
            "Sort-Object Length -Descending | Select-Object -First %d "
            "@{n='SizeBytes';e={$_.Length}}, @{n='FullName';e={$_.FullName}} | ConvertTo-Json"
        ) % (min_bytes, max(1, top_n))
        out = sysu.run_command(cmd)
        try:
            data = json.loads(out) if out else []
            if isinstance(data, dict):
                data = [data]
            for item in data:
                entries.append(FileEntry(path=item.get("FullName", ""), size_bytes=int(item.get("SizeBytes", 0))))
            return entries
        except Exception:
            logger.warning("PowerShell JSON parse failed; falling back to empty result.")
            return []

    # Linux / WSL / Termux: use find + sort for large files
    # Limit to a single filesystem by default (-xdev). In Termux, avoid sudo.
    size_arg = f"+{max(min_bytes, 1)}c" if min_bytes > 0 else "+1c"
    find_root = str(root)
    cmd = (
        f"find '{find_root}' -xdev -type f -size {size_arg} -printf '%s\t%p\\n' 2>/dev/null | "
        f"sort -nr | head -n {max(1, top_n)}"
    )
    out = sysu.run_command(cmd)
    for line in (out or "").splitlines():
        try:
            sz_s, p = line.split("\t", 1)
            entries.append(FileEntry(path=p, size_bytes=int(sz_s)))
        except Exception:
            continue
    return entries


def scan_heaviest_dirs(sysu: SystemUtils, path: Optional[str], top_n: int) -> List[DirEntry]:
    """
    Return heaviest top-level directories directly under the given path.
    """
    root = _default_scan_root(sysu, path)
    logger.debug("scan_heaviest_dirs: root=%s top_n=%s", root, top_n)

    if sysu.is_windows():
        cmd = (
            "pwsh -NoProfile -Command "
            "Get-ChildItem -File -Recurse -ErrorAction SilentlyContinue '" + str(root) + "' | "
            "Group-Object DirectoryName | ForEach-Object { [pscustomobject]@{ Path=$_.Name; SizeBytes=($_.Group | Measure-Object Length -Sum).Sum } } | "
            "Sort-Object SizeBytes -Descending | Select-Object -First %d Path,SizeBytes | ConvertTo-Json"
        ) % max(1, top_n)
        out = sysu.run_command(cmd)
        try:
            data = json.loads(out) if out else []
            if isinstance(data, dict):
                data = [data]
            return [DirEntry(path=i.get("Path", ""), size_human=format_bytes_binary(int(i.get("SizeBytes", 0)))) for i in data]
        except Exception:
            logger.warning("PowerShell JSON parse failed for heaviest dirs.")
            return []

    # Linux / WSL / Termux
    cmd = f"du -xhd1 '{root}' 2>/dev/null | sort -h | tail -n {max(1, top_n)}"
    out = sysu.run_command(cmd)
    results: List[DirEntry] = []
    for line in (out or "").splitlines():
        parts = line.split()
        if not parts:
            continue
        # Show the du human size as-is
        size_h = parts[0]
        p = parts[-1]
        results.append(DirEntry(path=p, size_human=size_h))
    return results


def detect_common_caches(sysu: SystemUtils, root: Optional[str]) -> Dict[str, List[str]]:
    """
    Detect common cache directories by category and return a mapping of category -> found paths.
    """
    home = Path(root).expanduser().resolve() if root else Path.home().resolve()
    found: Dict[str, List[str]] = {
        "python": [],
        "conda": [],
        "node": [],
        "build": [],
        "git": [],
        "apt": [],
        "journals": [],
        "huggingface": [],
        "uv": [],
    }

    # Python/ML caches
    for p in (home/".cache"/"pip", home/".cache"/"pipenv", home/".cache"/"huggingface", home/".cache"/"uv"):
        if p.exists():
            found["python" if p.name in ("pip", "pipenv") else ("huggingface" if p.name == "huggingface" else "uv")].append(str(p))

    # Conda
    for base in (home/"miniconda3", home/"anaconda3"):
        if base.exists():
            pkgs = base/"pkgs"
            if pkgs.exists():
                found["conda"].append(str(pkgs))

    # Node
    npm_cache = home/".npm"
    if npm_cache.exists():
        found["node"].append(str(npm_cache))

    # Build artifacts and __pycache__ under home (shallow listing only)
    found_build: List[str] = []
    try:
        for d in home.rglob("*"):
            name = d.name
            if d.is_dir() and name in ("build", "dist", ".pytest_cache", "__pycache__"):
                found_build.append(str(d))
    except Exception:
        pass
    if found_build:
        found["build"] = found_build

    # Git repos: list .git directories (not sizes)
    git_roots: List[str] = []
    try:
        for d in home.rglob(".git"):
            if d.is_dir():
                git_roots.append(str(d.parent))
    except Exception:
        pass
    if git_roots:
        found["git"] = git_roots

    # APT and journals: only relevant for Linux/WSL (not Termux)
    if sysu.is_linux() and not sysu.is_termux():
        if Path("/var/cache/apt").exists():
            found["apt"].append("/var/cache/apt")
        if Path("/var/lib/apt/lists").exists():
            found["apt"].append("/var/lib/apt/lists")
        if Path("/var/log/journal").exists():
            found["journals"].append("/var/log/journal")

    return found


def clean_caches(sysu: SystemUtils, categories: Iterable[str], *, dry_run: bool = True) -> List[str]:
    """
    Execute cache cleanup operations for the selected categories.
    Returns a list of human-readable action lines performed (or that would be performed in dry-run).
    """
    cats = {c.lower() for c in categories}
    actions: List[str] = []

    def run(label: str, command: str, sudo: bool = False) -> None:
        if dry_run:
            actions.append(f"DRY-RUN: {label}: {command}")
            return
        out = sysu.run_command(command, sudo=sudo)
        actions.append(f"{label}: {command}\n{out}")

    # Python/ML caches
    if any(c in cats for c in ("python", "pip", "huggingface", "uv", "all")):
        run("Remove caches", "rm -rf ~/.cache/pip ~/.cache/pipenv ~/.cache/huggingface ~/.cache/uv 2>/dev/null || true")

    # Conda/Mamba
    if any(c in cats for c in ("conda", "mamba", "all")):
        run("Conda clean", "conda clean -a -y || mamba clean -a -y || true")
        run("Conda sizes", "du -sh ~/miniconda3/pkgs ~/miniconda3/envs/* 2>/dev/null | sort -h")

    # Node
    if any(c in cats for c in ("node", "npm", "all")):
        run("NPM cache", "npm cache clean --force 2>/dev/null || true")
        run("node_modules", "find . -maxdepth 6 -type d -name node_modules -prune -print0 | xargs -0 -r rm -rf --")

    # APT & journal
    if any(c in cats for c in ("apt", "journals", "all")) and sysu.is_linux() and not sysu.is_termux():
        run("APT clean", "apt-get clean && bash -lc 'rm -f /var/cache/apt/*pkgcache* || true' && rm -rf /var/lib/apt/lists/*", sudo=True)
        run("Journal vacuum", "journalctl --vacuum-time=7d", sudo=True)

    # Build artifacts
    if any(c in cats for c in ("build", "all")):
        run(
            "Build artifacts",
            r'find "$HOME" -maxdepth 6 -type d \( -name build -o -name dist -o -name .pytest_cache -o -name __pycache__ \) -prune -print0 | xargs -0 -r rm -rf --',
        )

    # Git stores: aggressive gc
    if any(c in cats for c in ("git", "all")):
        run("Git GC", "find \"$HOME\" -type d -name .git -prune -print 2>/dev/null | sed 's|/\\.git$||' | xargs -r -I{} bash -lc 'cd \"{}\" && git gc --aggressive --prune=now || true'")

    return actions


def containers_maint(sysu: SystemUtils, provider: str, *, dry_run: bool = True) -> List[str]:
    """
    Show and clean Docker/Podman stores.
    provider: 'docker' | 'podman' | 'auto'
    """
    prov = (provider or "auto").lower()
    actions: List[str] = []

    def run(label: str, command: str, sudo: bool = False) -> None:
        if dry_run:
            actions.append(f"DRY-RUN: {label}: {command}")
            return
        out = sysu.run_command(command, sudo=sudo)
        actions.append(f"{label}: {command}\n{out}")

    if prov in ("docker", "auto"):
        run("Docker df", "docker system df -v || true")
        run("Docker prune", "docker system prune -a --volumes -f || true")
        run("Docker builder prune", "docker builder prune -a -f || true")
        run("Docker buildx prune", "docker buildx prune -a -f || true")
        run("Truncate logs", "find /var/lib/docker/containers -type f -name '*-json.log' -size +10M -exec truncate -s 0 {} +", sudo=True)

    if prov in ("podman", "auto"):
        run("Podman ps", "podman ps -a || true")
        run("Podman prune", "podman stop -a || true && podman pod rm -af || true && podman rm -af || true")
        run("Podman rmi", "podman rmi -af || true && podman volume prune -f || true && podman builder prune -af || true")
        run("Podman system prune", "podman system prune -a -f --volumes || true")

    return actions


def wsl_reclaim(sysu: SystemUtils, *, dry_run: bool = True) -> List[str]:
    """
    Reclaim disk space in WSL2 environments: run fstrim in WSL and provide guidance
    for Windows-side compaction. If running on Windows, attempt the LZX compaction.
    """
    actions: List[str] = []

    def run(label: str, command: str, sudo: bool = False) -> None:
        if dry_run:
            actions.append(f"DRY-RUN: {label}: {command}")
            return
        out = sysu.run_command(command, sudo=sudo)
        actions.append(f"{label}: {command}\n{out}")

    if sysu.is_wsl2() or (sysu.is_linux() and "WSL_DISTRO_NAME" in os.environ):
        run("WSL fstrim", "fstrim -av", sudo=True)
        actions.append(
            "To compact the VHDX from Windows, run PowerShell as your user: "
            "wsl --shutdown; $vhd=(Get-ChildItem \"$env:LOCALAPPDATA\\wsl\\*\\ext4.vhdx\").FullName; "
            "compact /c /a /f /i /exe:lzx \"$vhd\"; compact /q \"$vhd\""
        )
        return actions

    if sysu.is_windows():
        # Attempt to find a WSL VHDX and compact it using NTFS LZX.
        pwsh = (
            "pwsh -NoProfile -Command "
            "$v=(Get-ChildItem @(\"$env:LOCALAPPDATA\\wsl\\*\\ext4.vhdx\","
            "\"$env:LOCALAPPDATA\\Packages\\*\\LocalState\\ext4.vhdx\",\"$env:LOCALAPPDATA\\Docker\\wsl\\data\\ext4.vhdx\") "
            "-ErrorAction SilentlyContinue | Sort-Object Length -Descending | Select-Object -First 1).FullName;"
            " if ($v) { wsl --shutdown; compact /c /a /f /i /exe:lzx \"$v\"; compact /q \"$v\" } else { Write-Output 'No VHDX found.' }"
        )
        run("Windows VHDX LZX compact", pwsh)
        return actions

    # Non-WSL/Linux/Windows
    actions.append("WSL reclaim is only applicable to WSL2 on Windows/Linux hosts.")
    return actions


def build_report(
    largest_files: List[FileEntry],
    heaviest_dirs: List[DirEntry],
    caches: Dict[str, List[str]],
) -> Tuple[Dict[str, Any], str]:
    """
    Build a structured JSON object and a Markdown summary.
    """
    data: Dict[str, Any] = {
        "largest_files": [
            {"path": f.path, "size_bytes": f.size_bytes, "size_human": format_bytes_binary(f.size_bytes)}
            for f in largest_files
        ],
        "heaviest_dirs": [{"path": d.path, "size": d.size_human} for d in heaviest_dirs],
        "caches": caches,
    }

    lines: List[str] = [
        "# Disk Space Report",
        "",
        "## Largest Files",
    ]
    for f in largest_files:
        lines.append(f"- {format_bytes_binary(f.size_bytes)}  {f.path}")
    lines.append("")
    lines.append("## Heaviest Directories")
    for d in heaviest_dirs:
        lines.append(f"- {d.size_human}  {d.path}")
    lines.append("")
    lines.append("## Detected Caches")
    for k, v in sorted(caches.items()):
        if not v:
            continue
        lines.append(f"- {k}: {len(v)} paths")

    md = "\n".join(lines)
    return data, md
