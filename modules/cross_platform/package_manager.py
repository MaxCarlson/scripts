#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cross-platform package manager detection and tool inspection utilities.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass(frozen=True)
class InstallCandidate:
    manager: str
    confidence: float
    evidence: str
    package_id: Optional[str] = None
    upgrade_cmd: Optional[str] = None
    install_cmd: Optional[str] = None


_KNOWN_MANAGERS = [
    "pip", "uv", "pipx", "conda", "mamba",
    "scoop", "choco", "winget",
    "brew", "apt", "apt-get", "dpkg",
    "pacman", "yay", "dnf", "rpm",
    "pkg",  # Termux
    "cargo", "npm", "yarn", "go",
]


def detect_package_managers() -> Dict[str, bool]:
    """Return a dict of package manager name -> available on this system."""
    return {mgr: shutil.which(mgr) is not None for mgr in _KNOWN_MANAGERS}


def list_executable_paths(command_name: str) -> List[str]:
    """Return all paths where *command_name* is found on PATH."""
    found = shutil.which(command_name)
    if not found:
        return []
    results = [found]
    # On Windows, where() may find multiple; on POSIX try `which -a`
    if sys.platform != "win32":
        try:
            out = subprocess.check_output(
                ["which", "-a", command_name],
                stderr=subprocess.DEVNULL,
                text=True,
            )
            results = list(dict.fromkeys(ln.strip() for ln in out.splitlines() if ln.strip()))
        except Exception:
            pass
    return results


def probe_tool_installations(
    command_name: str,
    package_names: Optional[List[str]] = None,
) -> List[InstallCandidate]:
    """
    Return a list of InstallCandidate describing which package manager(s)
    likely own *command_name* on this system.
    """
    candidates: List[InstallCandidate] = []
    exe = shutil.which(command_name)
    if not exe:
        return candidates

    exe_lower = exe.lower().replace("\\", "/")

    # Path-based heuristics
    if "/scoop/shims/" in exe_lower:
        candidates.append(InstallCandidate("scoop", 0.95, f"path in scoop shims: {exe}"))
    if "/programdata/chocolatey/" in exe_lower or "/chocolatey/bin/" in exe_lower:
        candidates.append(InstallCandidate("choco", 0.95, f"path in chocolatey: {exe}"))
    if "/appdata/local/microsoft/winget/" in exe_lower:
        candidates.append(InstallCandidate("winget", 0.70, f"path in winget links: {exe}"))
    if "/.cargo/bin/" in exe_lower:
        candidates.append(InstallCandidate("cargo", 0.90, f"path in cargo bin: {exe}"))
    if "/linuxbrew/" in exe_lower or "/homebrew/" in exe_lower:
        candidates.append(InstallCandidate("brew", 0.85, f"path in homebrew: {exe}"))
    if "/data/data/com.termux/" in exe_lower:
        candidates.append(InstallCandidate("pkg", 0.85, f"path in Termux: {exe}"))
    if "/pipx/" in exe_lower:
        candidates.append(InstallCandidate("pipx", 0.75, f"path suggests pipx: {exe}"))

    # pipx
    if shutil.which("pipx"):
        try:
            out = subprocess.check_output(
                ["pipx", "list", "--json"], stderr=subprocess.DEVNULL, text=True, timeout=15
            )
            import json
            data = json.loads(out)
            for pkg_name, pkg_info in (data.get("venvs") or {}).items():
                apps = (pkg_info.get("metadata") or {}).get("main_package", {}).get("apps", [])
                if any(str(a).strip().lower() == command_name.lower() for a in apps):
                    candidates.append(
                        InstallCandidate("pipx", 0.95, f"pipx package '{pkg_name}' provides '{command_name}'")
                    )
        except Exception:
            pass

    # uv tool
    if shutil.which("uv"):
        try:
            out = subprocess.check_output(
                ["uv", "tool", "list"], stderr=subprocess.DEVNULL, text=True, timeout=15
            )
            for ln in out.splitlines():
                tool = ln.strip().split()[0] if ln.strip() else ""
                if tool.lower() == command_name.lower():
                    candidates.append(
                        InstallCandidate("uv", 0.85, f"uv tool list contains '{command_name}'")
                    )
        except Exception:
            pass

    return candidates
