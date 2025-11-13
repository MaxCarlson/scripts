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


def _match_ext(name: str, exts: Optional[List[str]]) -> bool:
    if not exts:
        return True
    lowered = name.lower()
    norm_exts = [e.lower().lstrip(".") for e in exts]
    return any(lowered.endswith("." + e) for e in norm_exts)


def _match_globs(path: str, patterns: Optional[List[str]]) -> bool:
    if not patterns:
        return True
    from fnmatch import fnmatch

    return any(fnmatch(path, p) for p in patterns)


def summarize_total_size(files: Iterable[FileEntry]) -> int:
    return sum(f.size_bytes for f in files)


def scan_largest_files(
    sysu: SystemUtils,
    path: Optional[str],
    top_n: int,
    min_size: Optional[str],
    *,
    exts: Optional[List[str]] = None,
    globs: Optional[List[str]] = None,
) -> List[FileEntry]:
    """
    Return top-N largest files at or under `path` (platform-specific defaults if None).
    Uses platform-native tools for speed; falls back to Python if necessary.
    """
    root = _default_scan_root(sysu, path)
    min_bytes = parse_size_to_bytes(min_size) or 0

    logger.debug("scan_largest_files: root=%s top_n=%s min=%s", root, top_n, min_bytes)

    entries: List[FileEntry] = []
    if sysu.is_windows():
        # PowerShell via -EncodedCommand to avoid cmd.exe pipe parsing
        ps = shutil.which("pwsh") or shutil.which("powershell") or "pwsh"  # type: ignore
        script = (
            f"$root=\"{str(root)}\"; $min={min_bytes}; "
            "Get-ChildItem -LiteralPath $root -File -Recurse -ErrorAction SilentlyContinue | "
            "Where-Object { $_.Length -ge $min } | Sort-Object Length -Descending | "
            f"Select-Object -First {max(1, top_n)} @{{n='SizeBytes';e={{$_.Length}}}}, @{{n='FullName';e={{$_.FullName}}}} | ConvertTo-Json"
        )
        import base64 as _b64
        encoded = _b64.b64encode(script.encode("utf-16le")).decode("ascii")
        cmd = f"{ps} -NoProfile -EncodedCommand {encoded}"
        out = sysu.run_command(cmd)
        try:
            data = json.loads(out) if out else []
            if isinstance(data, dict):
                data = [data]
            for item in data:
                p = item.get("FullName", "")
                s = int(item.get("SizeBytes", 0))
                if not _match_ext(p, exts) or not _match_globs(p, globs):
                    continue
                entries.append(FileEntry(path=p, size_bytes=s))
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
            if not _match_ext(p, exts) or not _match_globs(p, globs):
                continue
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
        import shutil as _sh
        import base64 as _b64
        ps = _sh.which("pwsh") or _sh.which("powershell") or "pwsh"
        script = (
            f"$root=\"{str(root)}\"; "
            "Get-ChildItem -LiteralPath $root -File -Recurse -ErrorAction SilentlyContinue | "
            "Group-Object DirectoryName | ForEach-Object { [pscustomobject]@{ Path=$_.Name; SizeBytes=($_.Group | Measure-Object Length -Sum).Sum } } | "
            f"Sort-Object SizeBytes -Descending | Select-Object -First {max(1, top_n)} Path,SizeBytes | ConvertTo-Json"
        )
        enc = _b64.b64encode(script.encode("utf-16le")).decode("ascii")
        out = sysu.run_command(f"{ps} -NoProfile -EncodedCommand {enc}")
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


def _estimate_path_size_bytes(sysu: SystemUtils, p: str) -> int:
    """Best-effort estimate of path size in bytes without raising."""
    try:
        path = Path(p)
        if path.is_file():
            return path.stat().st_size
        if path.is_dir():
            total = 0
            # Prefer du -sb when available (Linux/Termux)
            if sysu.is_linux() or sysu.is_termux() or sysu.is_wsl2():
                out = sysu.run_command(f"du -sb '{p}' 2>/dev/null | awk '{{print $1}}'")
                if out.strip().isdigit():
                    return int(out.strip())
            # Fallback: Python walk
            for dp, _, files in os.walk(p, onerror=lambda e: None):
                for fn in files:
                    try:
                        total += (Path(dp) / fn).stat().st_size
                    except Exception:
                        pass
            return total
    except Exception:
        pass
    return 0


def estimate_caches_bytes(sysu: SystemUtils, caches: Dict[str, List[str]], *, max_paths_per_category: int = 200) -> Tuple[Dict[str, int], int]:
    """Estimate bytes per cache category and total. Limits per-category samples to avoid huge walks."""
    per_cat: Dict[str, int] = {}
    total = 0
    for cat, paths in caches.items():
        if not paths:
            per_cat[cat] = 0
            continue
        # Cap to avoid extremely expensive deep walks (e.g., thousands of build dirs)
        subset = paths[:max_paths_per_category]
        s = 0
        for p in subset:
            s += _estimate_path_size_bytes(sysu, p)
        per_cat[cat] = s
        total += s
    return per_cat, total


def clean_caches(
    sysu: SystemUtils,
    categories: Iterable[str],
    *,
    dry_run: bool = True,
) -> List[str]:
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
        run("APT clean", "apt-get clean && rm -rf /var/lib/apt/lists/* 2>/dev/null || true", sudo=True)
        run("Journal vacuum", "journalctl --vacuum-time=3d", sudo=True)

    # Build artifacts
    if any(c in cats for c in ("build", "all")):
        run(
            "Build artifacts",
            r'find "$HOME" -maxdepth 6 -type d \( -name build -o -name dist -o -name .pytest_cache -o -name __pycache__ -o -name node_modules \) -prune -print0 | xargs -0 -r rm -rf --',
        )

    # Git stores: aggressive gc
    if any(c in cats for c in ("git", "all")):
        run("Git GC", "find \"$HOME\" -type d -name .git -prune -print 2>/dev/null | sed 's|/\\.git$||' | xargs -r -I{} bash -lc 'cd \"{}\" && git gc --aggressive --prune=now || true'")

    # Windows browser/app caches
    if any(c in cats for c in ("browser", "all")) and sysu.is_windows():
        ps = (
            "pwsh -NoProfile -Command "
            "$paths=@(" 
            r"'$env:APPDATA\Microsoft\Teams\Cache',"
            r"'$env:APPDATA\Microsoft\Teams\GPUCache',"
            r"'$env:LOCALAPPDATA\Microsoft\Olk\EBWebView',"
            r"'$env:LOCALAPPDATA\Microsoft\Edge\User Data\*\Cache',"
            r"'$env:LOCALAPPDATA\Microsoft\Edge\User Data\*\Code Cache',"
            r"'$env:LOCALAPPDATA\Microsoft\Edge\User Data\*\GPUCache',"
            r"'$env:LOCALAPPDATA\Google\Chrome\User Data\*\Cache',"
            r"'$env:LOCALAPPDATA\Google\Chrome\User Data\*\Code Cache',"
            r"'$env:LOCALAPPDATA\Google\Chrome\User Data\*\GPUCache'"
            "); "
            "$paths | ForEach-Object { Get-ChildItem $_ -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue }"
        )
        run("Windows browser caches", ps)

    # fstrim free blocks to backing store (Linux/WSL)
    if any(c in cats for c in ("fstrim", "all")) and (sysu.is_linux() or sysu.is_wsl2()):
        run("FSTRIM", "fstrim -av", sudo=True)

    return actions


def containers_scan(sysu: SystemUtils, provider: str, *, list_items: bool = False) -> Dict[str, Any]:
    """Return container info: running, all containers, images, and system df summary."""
    prov = (provider or "auto").lower()
    result: Dict[str, Any] = {"provider": prov, "running": [], "all": [], "images": [], "system_df": ""}

    def _run(cmd: str) -> str:
        return sysu.run_command(cmd)

    if prov in ("docker", "auto"):
        if list_items:
            r = _run("docker ps --format '{{.ID}} {{.Image}} {{.Size}} {{.Names}}' || true")
            a = _run("docker ps -a --format '{{.ID}} {{.Image}} {{.Size}} {{.Names}}' || true")
            i = _run("docker images --format '{{.Repository}}:{{.Tag}} {{.Size}}' || true")
            result.update({
                "running": r.splitlines() if r else [],
                "all": a.splitlines() if a else [],
                "images": i.splitlines() if i else [],
            })
        df = _run("docker system df -v || true")
        result["system_df"] = df
        result["provider"] = "docker"
        return result

    if prov in ("podman", "auto"):
        if list_items:
            r = _run("podman ps --format '{{.ID}} {{.Image}} {{.Size}} {{.Names}}' || true")
            a = _run("podman ps -a --format '{{.ID}} {{.Image}} {{.Size}} {{.Names}}' || true")
            i = _run("podman images --format '{{.Repository}}:{{.Tag}} {{.Size}}' || true")
            result.update({
                "running": r.splitlines() if r else [],
                "all": a.splitlines() if a else [],
                "images": i.splitlines() if i else [],
            })
        df = _run("podman system df -v || true")
        result["system_df"] = df
        result["provider"] = "podman"
        return result

    return result


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


def containers_store_size(sysu: SystemUtils, provider: str) -> int:
    """Estimate container store size in bytes for docker/podman."""
    prov = (provider or "auto").lower()
    cand_paths: List[str] = []
    # Docker default
    cand_paths.append("/var/lib/docker")
    # Podman rootless
    cand_paths.append(str(Path.home() / ".local/share/containers/storage"))
    # Try both on auto; otherwise prioritize provider
    if prov == "docker":
        paths = [cand_paths[0]]
    elif prov == "podman":
        paths = [cand_paths[1]]
    else:
        paths = cand_paths
    total = 0
    for p in paths:
        if Path(p).exists():
            total += _estimate_path_size_bytes(sysu, p)
    return total


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


def space_summary(sysu: SystemUtils) -> str:
    """Return human-readable summary of free space across drives."""
    if sysu.is_windows():
        cmd = (
            "pwsh -NoProfile -Command "
            "Get-PSDrive -PSProvider FileSystem | Select-Object Name,Used,Free,@{n='UsedGB';e={[math]::Round($_.Used/1GB,2)}},@{n='FreeGB';e={[math]::Round($_.Free/1GB,2)}} | Format-Table -AutoSize"
        )
        return sysu.run_command(cmd)
    # Linux/WSL/Termux
    return sysu.run_command("df -h")


def clean_largest(
    sysu: SystemUtils,
    path: Optional[str],
    top_n: int,
    min_size: Optional[str],
    *,
    exts: Optional[List[str]] = None,
    globs: Optional[List[str]] = None,
    dry_run: bool = True,
) -> Tuple[List[str], int, int]:
    """
    Find largest files (respecting filters) and delete them. Returns (actions, count, total_bytes).
    In dry_run mode, does not delete; still reports would-delete summary.
    """
    items = scan_largest_files(sysu, path, top_n, min_size, exts=exts, globs=globs)
    total = summarize_total_size(items)
    actions: List[str] = []
    if dry_run:
        for it in items:
            actions.append(f"DRY-RUN: rm '{it.path}' ({format_bytes_binary(it.size_bytes)})")
        return actions, len(items), total

    # delete
    deleted = 0
    for it in items:
        try:
            Path(it.path).unlink(missing_ok=True)
            actions.append(f"Deleted: {it.path} ({format_bytes_binary(it.size_bytes)})")
            deleted += 1
        except Exception as e:
            actions.append(f"Failed: {it.path} — {e}")
    return actions, deleted, total


def run_full_scan(
    sysu: SystemUtils,
    *,
    path: Optional[str] = None,
    top_n: int = 50,
    min_size: Optional[str] = None,
    exts: Optional[List[str]] = None,
    globs: Optional[List[str]] = None,
    provider: str = "auto",
    list_containers: bool = False,
) -> Dict[str, Any]:
    """Run largest, caches, and containers scans and return a structured summary."""
    largest = scan_largest_files(sysu, path, top_n, min_size, exts=exts, globs=globs)
    largest_total = summarize_total_size(largest)

    caches = detect_common_caches(sysu, path)
    caches_per_cat, caches_total = estimate_caches_bytes(sysu, caches)

    cont_info = containers_scan(sysu, provider, list_items=list_containers)
    cont_bytes = containers_store_size(sysu, provider)

    overall = largest_total + caches_total + cont_bytes
    extra: Dict[str, Any] = {}
    if sysu.is_windows():
        ps = shutil.which("pwsh") or shutil.which("powershell") or "pwsh"  # type: ignore
        import base64 as _b64
        def run_ps(script: str) -> str:
            enc = _b64.b64encode(script.encode("utf-16le")).decode("ascii")
            return sysu.run_command(f"{ps} -NoProfile -EncodedCommand {enc}")

        tri = {
            "top_files": run_ps("Get-ChildItem C:\\ -File -Recurse -Force -ErrorAction SilentlyContinue | Sort-Object Length -Descending | Select-Object -First 40 @{n='GB';e={[math]::Round($_.Length/1GB,2)}}, FullName"),
            "per_root": run_ps("$roots = 'C:\\Users','C:\\ProgramData','C:\\Program Files','C:\\Program Files (x86)','C:\\Windows'; foreach($r in $roots){ try{ $sum = (Get-ChildItem $r -Recurse -Force -ErrorAction SilentlyContinue -File | Measure-Object Length -Sum).Sum; '{0,-28}  {1,8:N2} GB' -f $r, ($sum/1GB) }catch{} }"),
            "per_user": run_ps("Get-ChildItem 'C:\\Users' -Directory -ErrorAction SilentlyContinue | ForEach-Object { $p=$_.FullName; try{ $sz=(Get-ChildItem $p -Recurse -Force -ErrorAction SilentlyContinue -File | Measure-Object Length -Sum).Sum; [pscustomobject]@{ GB=[math]::Round($sz/1GB,2); Path=$p } }catch{} } | Sort-Object GB -Descending | Select-Object -First 10"),
        }
        extra["windows_triage"] = tri
        extra["windows_drives"] = run_ps("Get-PSDrive -PSProvider FileSystem | Select Name,Used,Free,@{n='UsedGB';e={[math]::Round($_.Used/1GB,2)}},@{n='FreeGB';e={[math]::Round($_.Free/1GB,2)}} | Format-Table -AutoSize | Out-String")
    else:
        # Linux/WSL/Termux drive overview
        extra["linux_df"] = sysu.run_command("df -h")
    return {
        "largest": {
            "items": [{"path": i.path, "size_bytes": i.size_bytes, "size_human": format_bytes_binary(i.size_bytes)} for i in largest],
            "count": len(largest),
            "total_bytes": largest_total,
            "total_human": format_bytes_binary(largest_total),
        },
        "caches": {
            "detected": caches,
            "per_category_bytes": caches_per_cat,
            "per_category_human": {k: format_bytes_binary(v) for k, v in caches_per_cat.items()},
            "total_bytes": caches_total,
            "total_human": format_bytes_binary(caches_total),
        },
        "containers": {
            "provider": cont_info.get("provider"),
            "running": cont_info.get("running", []),
            "all": cont_info.get("all", []),
            "images": cont_info.get("images", []),
            "system_df": cont_info.get("system_df", ""),
            "store_bytes": cont_bytes,
            "store_human": format_bytes_binary(cont_bytes),
        },
        "overall": {
            "total_bytes": overall,
            "total_human": format_bytes_binary(overall),
        },
        **extra,
    }


def build_full_markdown(info: Dict[str, Any]) -> str:
    lines: List[str] = ["# Disk Space Report", ""]
    # Largest
    lg = info.get("largest", {})
    lines.append("## Largest Files")
    for it in lg.get("items", [])[:10]:
        lines.append(f"- {it.get('size_human','')}  {it.get('path','')}")
    if lg.get("count", 0) > 10:
        lines.append(f"... and {lg['count']-10} more")
    lines.append(f"\nTotal: {lg.get('total_human','0 B')} across {lg.get('count',0)} files\n")
    # Heaviest dirs not directly in info; rely on caches per-category
    ch = info.get("caches", {})
    lines.append("## Detected Caches")
    per_cat = ch.get("per_category_human", {})
    detected = ch.get("detected", {})
    for k in sorted(per_cat.keys()):
        v = per_cat[k]
        n = len(detected.get(k, []))
        if v != "0 B" or n:
            lines.append(f"- {k}: {v}  ({n} paths)")
    lines.append(f"\nCaches Total: {ch.get('total_human','0 B')}\n")
    # Containers
    ct = info.get("containers", {})
    lines.append("## Containers")
    lines.append(f"Estimated store size: {ct.get('store_human','0 B')}\n")
    # Drives overview
    if "windows_drives" in info:
        lines.append("## Drives Overview (Windows)")
        lines.append("```")
        lines.append(info["windows_drives"].strip())
        lines.append("``" + "`")
    if "linux_df" in info:
        lines.append("## Filesystems (df -h)")
        lines.append("```")
        lines.append(info["linux_df"].strip())
        lines.append("``" + "`")
    # Windows triage
    if "windows_triage" in info:
        tri = info["windows_triage"]
        lines.append("## Windows Host Triage")
        lines.append("### Top Files (C:)\n```")
        lines.append(tri.get("top_files", "").strip())
        lines.append("``" + "`")
        lines.append("### Size by Root\n```")
        lines.append(tri.get("per_root", "").strip())
        lines.append("``" + "`")
        lines.append("### Largest User Profiles\n```")
        lines.append(tri.get("per_user", "").strip())
        lines.append("``" + "`")
    # Overall
    ov = info.get("overall", {})
    lines.append(f"## Overall Total\n{ov.get('total_human','0 B')}")
    return "\n".join(lines)
