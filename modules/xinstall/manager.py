from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from tool_install_manager.tracker import make_record, upsert_record

try:
    from tool_install_manager.advisor import LLMAdvisor
except Exception:
    LLMAdvisor = None  # type: ignore

try:
    from cross_platform.package_manager import (
        InstallCandidate as CPInstallCandidate,
        detect_package_managers as cp_detect_package_managers,
        list_executable_paths as cp_list_executable_paths,
        probe_tool_installations as cp_probe_tool_installations,
    )
    from cross_platform.system_utils import SystemUtils
except Exception:
    CPInstallCandidate = None  # type: ignore
    SystemUtils = None  # type: ignore
    cp_detect_package_managers = None  # type: ignore
    cp_list_executable_paths = None  # type: ignore
    cp_probe_tool_installations = None  # type: ignore


@dataclass(frozen=True)
class OwnershipCandidate:
    manager: str
    confidence: float
    evidence: str
    package_id: Optional[str] = None
    upgrade_hint: Optional[str] = None
    reinstall_hint: Optional[str] = None
    uninstall_hint: Optional[str] = None


@dataclass(frozen=True)
class ToolStatus:
    command_name: str
    package_name: str
    executable_path: Optional[str]
    executable_paths: List[str]
    candidates: List[OwnershipCandidate]
    recommended: Optional[OwnershipCandidate]


@dataclass(frozen=True)
class PlannedAction:
    description: str
    command_argv: List[str]
    shell_hint: str


@dataclass(frozen=True)
class IsInReport:
    command_name: str
    package_name: str
    primary_path: Optional[str]
    all_paths: List[str]
    candidates: List[OwnershipCandidate]
    recommended: Optional[OwnershipCandidate]
    duplicate_paths: bool
    duplicate_managers: bool


def _is_windows() -> bool:
    return os.name == "nt"


def _is_termux() -> bool:
    return "com.termux" in os.environ.get("PREFIX", "").lower() or "TERMUX" in os.environ.get("PREFIX", "").upper()


def _is_wsl2() -> bool:
    if SystemUtils:
        try:
            return SystemUtils().is_wsl2()
        except Exception:
            pass
    try:
        return "microsoft" in Path("/proc/sys/kernel/osrelease").read_text(encoding="utf-8").lower()
    except Exception:
        return False


def _os_tag() -> str:
    if _is_termux():
        return "termux"
    if _is_windows():
        return "windows"
    if _is_wsl2():
        return "wsl2"
    return "linux"


def _run_cmd(argv: Sequence[str], timeout_s: float = 30.0) -> Tuple[int, str, str]:
    try:
        cp = subprocess.run(
            list(argv),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
        return cp.returncode, cp.stdout or "", cp.stderr or ""
    except FileNotFoundError:
        return 127, "", f"missing: {argv[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except Exception as e:
        return 1, "", f"error: {e}"


def _which(command_name: str) -> Optional[str]:
    p = shutil.which(command_name)
    if not p:
        return None
    try:
        return str(Path(p).resolve())
    except Exception:
        return p


def _first_line(text: str) -> str:
    for ln in text.splitlines():
        s = ln.strip()
        if s:
            return s
    return ""


def get_command_version(command_name: str) -> str:
    exe = _which(command_name)
    if not exe:
        return ""
    # Best-effort: try common flags quickly.
    for flag in ("--version", "-V", "-v", "version"):
        rc, out, _ = _run_cmd([exe, flag], timeout_s=3.0)
        if rc == 0 and out.strip():
            return _first_line(out)
    return ""


def detect_installers() -> Dict[str, bool]:
    """
    Returns a map of installer/runtime tool availability on this machine.
    """
    if cp_detect_package_managers:
        try:
            return cp_detect_package_managers()
        except Exception:
            pass

    keys = [
        "winget",
        "choco",
        "scoop",
        "brew",
        "apt-get",
        "dnf",
        "yum",
        "pacman",
        "apk",
        "pkg",
        "dpkg-query",
        "pipx",
        "uv",
        "cargo",
        "rustup",
        "go",
        "asdf",
        "conda",
        "mamba",
        "micromamba",
        "npm",
        "pnpm",
    ]
    return {k: (shutil.which(k) is not None) for k in keys}


def _load_manager_policy() -> Dict[str, object]:
    policy_path = Path(__file__).with_name("manager_policy.json")
    if not policy_path.exists():
        return {}
    try:
        return json.loads(policy_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _policy_manager_list(
    policy: Dict[str, object],
    os_tag: str,
    command_name: str,
    package_name: str,
) -> List[str]:
    tool_key = command_name.lower()
    pkg_key = package_name.lower()
    tools = policy.get("tools", {})
    if isinstance(tools, dict):
        for key in (tool_key, pkg_key):
            entry = tools.get(key)
            if isinstance(entry, dict):
                lst = entry.get(os_tag)
                if isinstance(lst, list):
                    return [str(x) for x in lst]

    defaults = policy.get("defaults", {})
    if isinstance(defaults, dict):
        lst = defaults.get(os_tag)
        if isinstance(lst, list):
            return [str(x) for x in lst]

    return []


def _maybe_llm_recommendation(
    command_name: str,
    package_name: str,
    os_tag: str,
    installers: Dict[str, bool],
) -> Optional[str]:
    if os.environ.get("TOOL_INSTALL_USE_LLM") != "1":
        return None
    if LLMAdvisor is None:
        return None

    template_path = os.environ.get("TOOL_INSTALL_LLM_TEMPLATES", "")
    if template_path:
        path = Path(template_path).expanduser()
    else:
        path = Path.home() / ".config" / "tool-install-manager" / "llm_templates.json"

    templates: Dict[str, List[str]] = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                templates = {str(k): [str(x) for x in v] for k, v in data.items() if isinstance(v, list)}
        except Exception:
            templates = {}

    advisor = LLMAdvisor(cli_templates=templates)
    known = [k for k, v in installers.items() if v] + ["apt", "pkg"]
    prompt = (
        "Select the best package manager for installing a tool.\n"
        f"Tool command: {command_name}\n"
        f"Package name: {package_name}\n"
        f"OS: {os_tag}\n"
        f"Available managers: {', '.join(sorted(set(known)))}\n"
        "Answer with a single manager name."
    )
    decision = advisor.recommend_manager(prompt, known_managers=known)
    if decision:
        return decision.manager
    return None


def _convert_cp_candidate(cand: "CPInstallCandidate") -> OwnershipCandidate:
    return OwnershipCandidate(
        manager=cand.manager,
        confidence=cand.confidence,
        evidence=cand.evidence,
        package_id=cand.package_id,
        upgrade_hint=cand.upgrade_hint,
        reinstall_hint=cand.reinstall_hint,
        uninstall_hint=cand.uninstall_hint,
    )


def installer_install_commands(installer_name: str) -> List[PlannedAction]:
    """
    Returns commands to install the installer itself (best-effort).
    Default is to suggest commands; you control execution via --apply.
    """
    name = installer_name.lower()

    actions: List[PlannedAction] = []

    if name == "pipx":
        if _is_windows():
            actions.append(
                PlannedAction(
                    description="Install pipx (user scope) and ensure PATH",
                    command_argv=["python", "-m", "pip", "install", "--user", "pipx"],
                    shell_hint="powershell",
                )
            )
            actions.append(
                PlannedAction(
                    description="Ensure pipx paths are added (may require new shell)",
                    command_argv=["python", "-m", "pipx", "ensurepath"],
                    shell_hint="powershell",
                )
            )
        else:
            py = shutil.which("python3") or shutil.which("python") or "python3"
            actions.append(
                PlannedAction(
                    description="Install pipx (user scope) and ensure PATH",
                    command_argv=[py, "-m", "pip", "install", "--user", "pipx"],
                    shell_hint="bash",
                )
            )
            actions.append(
                PlannedAction(
                    description="Ensure pipx paths are added (may require new shell)",
                    command_argv=[py, "-m", "pipx", "ensurepath"],
                    shell_hint="bash",
                )
            )
        return actions

    if name == "uv":
        if _is_windows():
            actions.append(
                PlannedAction(
                    description="Install uv (user scope) via pip",
                    command_argv=["python", "-m", "pip", "install", "--user", "uv"],
                    shell_hint="powershell",
                )
            )
        else:
            py = shutil.which("python3") or shutil.which("python") or "python3"
            actions.append(
                PlannedAction(
                    description="Install uv (user scope) via pip",
                    command_argv=[py, "-m", "pip", "install", "--user", "uv"],
                    shell_hint="bash",
                )
            )
        return actions

    if name == "cargo" or name == "rustup":
        if _is_windows():
            actions.append(
                PlannedAction(
                    description="Install Rust toolchain via rustup (manual step usually required on Windows)",
                    command_argv=["rustup-init.exe"],
                    shell_hint="powershell",
                )
            )
        else:
            actions.append(
                PlannedAction(
                    description="Install rustup (interactive installer)",
                    command_argv=["sh", "-c", "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh"],
                    shell_hint="bash",
                )
            )
        return actions

    if name == "brew":
        actions.append(
            PlannedAction(
                description="Install Homebrew (interactive installer)",
                command_argv=["bash", "-c", "curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh | bash"],
                shell_hint="bash",
            )
        )
        return actions

    if name == "scoop":
        actions.append(
            PlannedAction(
                description="Install Scoop (CurrentUser)",
                command_argv=[
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser; iwr -useb get.scoop.sh | iex",
                ],
                shell_hint="powershell",
            )
        )
        return actions

    if name == "choco":
        actions.append(
            PlannedAction(
                description="Install Chocolatey (requires admin typically)",
                command_argv=[
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    "[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072; iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))",
                ],
                shell_hint="powershell",
            )
        )
        return actions

    if name in ("apt-get", "dnf", "yum", "pacman", "apk", "pkg"):
        # System package manager: "installing it" is OS-specific; generally preinstalled.
        return []

    return []


def _path_heuristics(exe_path: Optional[str]) -> List[OwnershipCandidate]:
    if not exe_path:
        return []
    p = exe_path.lower().replace("/", "\\") if _is_windows() else exe_path.lower()

    cands: List[OwnershipCandidate] = []

    if _is_windows():
        if "\\scoop\\shims\\" in p:
            cands.append(OwnershipCandidate("scoop", 0.95, f"path contains scoop shims: {exe_path}"))
        if "\\programdata\\chocolatey\\" in p or "\\chocolatey\\bin\\" in p:
            cands.append(OwnershipCandidate("choco", 0.95, f"path contains chocolatey: {exe_path}"))
        if "\\.cargo\\bin\\" in p:
            cands.append(OwnershipCandidate("cargo", 0.90, f"path contains cargo bin: {exe_path}"))
        if "\\go\\bin\\" in p:
            cands.append(OwnershipCandidate("go", 0.75, f"path contains go bin: {exe_path}"))
        if "\\pipx\\" in p:
            cands.append(OwnershipCandidate("pipx", 0.70, f"path suggests pipx: {exe_path}"))
        if "\\appdata\\local\\microsoft\\winget\\links\\" in p:
            cands.append(OwnershipCandidate("winget", 0.70, f"path is WinGet Links shim: {exe_path}"))
    else:
        if "/.cargo/bin/" in p:
            cands.append(OwnershipCandidate("cargo", 0.90, f"path contains cargo bin: {exe_path}"))
        if "/home/linuxbrew/" in p or "/opt/homebrew/" in p:
            cands.append(OwnershipCandidate("brew", 0.85, f"path contains homebrew: {exe_path}"))
        if p.startswith("/data/data/com.termux/files/usr/bin/"):
            cands.append(OwnershipCandidate("pkg", 0.70, f"path suggests termux pkg: {exe_path}"))

    return cands


def _parse_winget_table(text: str) -> List[Dict[str, str]]:
    lines = [ln.rstrip("\r\n") for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        return []

    header_idx = None
    for i, ln in enumerate(lines[:12]):
        if "Name" in ln and "Id" in ln and "Version" in ln:
            header_idx = i
            break
    if header_idx is None or header_idx + 1 >= len(lines):
        return []

    header = lines[header_idx]
    cols = ["Name", "Id", "Version"]
    starts: Dict[str, int] = {}
    for col in cols:
        m = re.search(rf"\b{re.escape(col)}\b", header)
        if m:
            starts[col] = m.start()

    if "Name" not in starts or "Id" not in starts:
        return []

    ordered = sorted(starts.items(), key=lambda kv: kv[1])
    slices: List[Tuple[str, int, Optional[int]]] = []
    for idx, (col, start) in enumerate(ordered):
        end = ordered[idx + 1][1] if idx + 1 < len(ordered) else None
        slices.append((col, start, end))

    rows: List[Dict[str, str]] = []
    for ln in lines[header_idx + 2:]:
        if set(ln.strip()) == {"-"}:
            continue
        row: Dict[str, str] = {}
        for col, start, end in slices:
            cell = ln[start:end].strip() if end is not None else ln[start:].strip()
            row[col] = cell
        if row.get("Name") or row.get("Id"):
            rows.append(row)
    return rows


def _probe_winget_status(command_name: str, package_name: str) -> List[OwnershipCandidate]:
    if shutil.which("winget") is None:
        return []

    cands: List[OwnershipCandidate] = []

    # If executable is a winget "Links" shim, winget list/upgrade is very likely the manager.
    rc_l, out_l, _ = _run_cmd(["winget", "list", "--name", package_name], timeout_s=25.0)
    if rc_l == 0 and out_l.strip():
        rows = _parse_winget_table(out_l)
        for r in rows[:5]:
            pkg_id = r.get("Id") or None
            name = r.get("Name") or package_name
            upgrade = f'winget upgrade --id "{pkg_id}"' if pkg_id else f'winget upgrade --name "{package_name}"'
            reinstall = f'winget install --id "{pkg_id}" -e --force' if pkg_id else f'winget install --name "{package_name}" --force'
            cands.append(
                OwnershipCandidate(
                    manager="winget",
                    confidence=0.55,
                    evidence=f"winget list matches: {name} ({pkg_id or 'unknown id'})",
                    package_id=pkg_id,
                    upgrade_hint=upgrade,
                    reinstall_hint=reinstall,
                    uninstall_hint=f'winget uninstall --id "{pkg_id}"' if pkg_id else f'winget uninstall --name "{package_name}"',
                )
            )

    rc_u, out_u, _ = _run_cmd(["winget", "upgrade", "--name", package_name], timeout_s=25.0)
    if rc_u == 0 and out_u.strip():
        rows = _parse_winget_table(out_u)
        for r in rows[:5]:
            pkg_id = r.get("Id") or None
            name = r.get("Name") or package_name
            upgrade = f'winget upgrade --id "{pkg_id}"' if pkg_id else f'winget upgrade --name "{package_name}"'
            cands.append(
                OwnershipCandidate(
                    manager="winget",
                    confidence=0.70,
                    evidence=f"winget upgrade matches: {name} ({pkg_id or 'unknown id'})",
                    package_id=pkg_id,
                    upgrade_hint=upgrade,
                )
            )

    return cands


def _probe_pipx_status(command_name: str) -> List[OwnershipCandidate]:
    if shutil.which("pipx") is None:
        return []
    rc, out, _ = _run_cmd(["pipx", "list", "--json"], timeout_s=25.0)
    if rc != 0 or not out.strip():
        return []
    try:
        import json

        data = json.loads(out)
    except Exception:
        return []
    venvs = data.get("venvs", {}) if isinstance(data, dict) else {}
    matches: List[OwnershipCandidate] = []
    for pkg_name, pkg_info in venvs.items():
        if not isinstance(pkg_info, dict):
            continue
        apps = pkg_info.get("apps", [])
        if not isinstance(apps, list):
            continue
        for app in apps:
            if str(app).strip().lower() == command_name.lower():
                matches.append(
                    OwnershipCandidate(
                        manager="pipx",
                        confidence=0.95,
                        evidence=f"pipx reports app '{command_name}' from package '{pkg_name}'",
                        package_id=pkg_name,
                        upgrade_hint=f"pipx upgrade {pkg_name}",
                        reinstall_hint=f"pipx reinstall {pkg_name}",
                        uninstall_hint=f"pipx uninstall {pkg_name}",
                    )
                )
    return matches


def _probe_uv_status(command_name: str) -> List[OwnershipCandidate]:
    if shutil.which("uv") is None:
        return []
    rc, out, _ = _run_cmd(["uv", "tool", "list"], timeout_s=25.0)
    if rc != 0 or not out.strip():
        return []
    matches: List[OwnershipCandidate] = []
    for ln in out.splitlines():
        s = ln.strip()
        if not s:
            continue
        tool = s.split()[0]
        if tool.lower() == command_name.lower():
            matches.append(
                OwnershipCandidate(
                    manager="uv",
                    confidence=0.85,
                    evidence=f"uv tool list contains '{command_name}'",
                    package_id=tool,
                    upgrade_hint=f"uv tool upgrade {tool}",
                    reinstall_hint=f"uv tool install {tool} --force",
                    uninstall_hint=f"uv tool uninstall {tool}",
                )
            )
    return matches


def _probe_dpkg_owner(exe_path: Optional[str]) -> List[OwnershipCandidate]:
    if not exe_path:
        return []
    if shutil.which("dpkg-query") is None and shutil.which("dpkg") is None:
        return []
    dpkg = shutil.which("dpkg-query") or "dpkg-query"
    rc, out, _ = _run_cmd([dpkg, "-S", exe_path], timeout_s=10.0)
    if rc != 0 or ":" not in out:
        return []
    pkg = out.split(":", 1)[0].strip()
    if not pkg:
        return []
    return [
        OwnershipCandidate(
            manager="dpkg",
            confidence=0.90,
            evidence=f"dpkg owns path: {pkg}",
            package_id=pkg,
            upgrade_hint=f"sudo apt-get update && sudo apt-get install -y {pkg}",
            reinstall_hint=f"sudo apt-get install -y --reinstall {pkg}",
            uninstall_hint=f"sudo apt-get remove -y {pkg}",
        )
    ]


def _probe_pacman_owner(exe_path: Optional[str]) -> List[OwnershipCandidate]:
    if not exe_path:
        return []
    if shutil.which("pacman") is None:
        return []
    rc, out, _ = _run_cmd(["pacman", "-Qo", exe_path], timeout_s=10.0)
    if rc != 0 or " is owned by " not in out:
        return []
    # Example: "/usr/bin/rg is owned by ripgrep 13.0.0-2"
    m = re.search(r"is owned by\s+([^\s]+)\s+", out)
    if not m:
        return []
    pkg = m.group(1).strip()
    return [
        OwnershipCandidate(
            manager="pacman",
            confidence=0.90,
            evidence=f"pacman owns path: {pkg}",
            package_id=pkg,
            upgrade_hint="sudo pacman -Syu",
            reinstall_hint=f"sudo pacman -S --noconfirm {pkg}",
            uninstall_hint=f"sudo pacman -Rns --noconfirm {pkg}",
        )
    ]


def _probe_brew_owner(exe_path: Optional[str]) -> List[OwnershipCandidate]:
    if not exe_path:
        return []
    if shutil.which("brew") is None:
        return []
    rc, out, _ = _run_cmd(["brew", "which", Path(exe_path).name], timeout_s=10.0)
    if rc != 0:
        return []
    brewed = _first_line(out).strip()
    if brewed and brewed == exe_path:
        return [
            OwnershipCandidate(
                manager="brew",
                confidence=0.85,
                evidence=f"brew which matches path: {exe_path}",
                upgrade_hint="brew update && brew upgrade",
            )
        ]
    return []


def tool_status(command_name: str, package_name: Optional[str] = None) -> ToolStatus:
    pkg = package_name or command_name
    exe_paths: List[str] = []
    if cp_list_executable_paths:
        try:
            exe_paths = cp_list_executable_paths(command_name)
        except Exception:
            exe_paths = []
    if not exe_paths:
        exe = _which(command_name)
        exe_paths = [exe] if exe else []
    exe = exe_paths[0] if exe_paths else None

    cands: List[OwnershipCandidate] = []
    cands.extend(_path_heuristics(exe))
    cands.extend(_probe_pipx_status(command_name))
    cands.extend(_probe_uv_status(command_name))
    cands.extend(_probe_winget_status(command_name, pkg))
    cands.extend(_probe_dpkg_owner(exe))
    cands.extend(_probe_pacman_owner(exe))
    cands.extend(_probe_brew_owner(exe))
    if cp_probe_tool_installations:
        try:
            extra = cp_probe_tool_installations(command_name, package_names=[pkg])
            if extra and CPInstallCandidate:
                cands.extend([_convert_cp_candidate(c) for c in extra])
        except Exception:
            pass

    seen = set()
    unique: List[OwnershipCandidate] = []
    for c in cands:
        key = (c.manager, c.package_id or "", c.evidence)
        if key in seen:
            continue
        seen.add(key)
        unique.append(c)

    unique_sorted = sorted(unique, key=lambda x: x.confidence, reverse=True)
    recommended = unique_sorted[0] if unique_sorted else None

    return ToolStatus(
        command_name=command_name,
        package_name=pkg,
        executable_path=exe,
        executable_paths=exe_paths,
        candidates=unique_sorted,
        recommended=recommended,
    )


def _prompt_yes_no(question: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    while True:
        resp = input(f"{question} [y/n]: ").strip().lower()
        if resp in ("y", "yes"):
            return True
        if resp in ("n", "no"):
            return False


def guard_against_shadow_install(
    command_name: str,
    install_method: str,
    assume_yes: bool,
) -> int:
    st = tool_status(command_name=command_name, package_name=None)
    installers = detect_installers()
    recommended_list = _recommended_manager_list(
        command_name=command_name,
        package_name=st.package_name,
        installers=installers,
    )
    if recommended_list and install_method.lower() not in [m.lower() for m in recommended_list]:
        msg = (
            f"\nWARNING: '{command_name}' is usually best installed via: {', '.join(recommended_list)}\n"
            f"You are trying to install via: {install_method}\n"
        )
        print(msg)
        ok = _prompt_yes_no("Proceed anyway with this installer?", assume_yes=assume_yes)
        if not ok:
            return 2

    strong = [c for c in st.candidates if c.confidence >= 0.80]
    if not strong:
        return 0
    if any(c.manager.lower() == install_method.lower() for c in strong):
        return 0

    best = strong[0]
    msg = (
        f"\nBLOCK: '{command_name}' appears installed by another manager.\n"
        f"Likely managed by: {best.manager} (confidence {best.confidence:.2f})\n"
        f"Evidence: {best.evidence}\n"
    )
    if st.executable_path:
        msg += f"\nPath: {st.executable_path}\n"
    if best.upgrade_hint:
        msg += f"\nRecommended upgrade:\n  {best.upgrade_hint}\n"
    msg += f"\nYou are trying to install via: {install_method}\n"
    print(msg)

    ok = _prompt_yes_no("Proceed anyway (may shadow/conflict)?", assume_yes=assume_yes)
    return 0 if ok else 2


def _map_common_packages(package_name: str, manager: str) -> str:
    """
    Helpful mappings where command != package.
    """
    p = package_name
    if manager in ("apt", "dpkg"):
        # Examples on Ubuntu:
        if package_name.lower() == "fd":
            return "fd-find"
        if package_name.lower() == "rg":
            return "ripgrep"
    return p


def _choose_best_manager_for_install(
    command_name: str,
    package_name: str,
    installers: Dict[str, bool],
) -> str:
    os_tag = _os_tag()
    llm_mgr = _maybe_llm_recommendation(command_name, package_name, os_tag, installers)
    if llm_mgr:
        return llm_mgr

    policy = _load_manager_policy()
    candidates = _policy_manager_list(policy, os_tag, command_name, package_name)
    for candidate in candidates:
        if candidate in ("apt", "pkg"):
            return candidate
        if installers.get(candidate, False):
            return candidate

    # Conservative fallback ranking if policy missing.
    if _is_termux():
        return "pkg"
    if _is_windows():
        for candidate in ("winget", "scoop", "choco", "uv", "pipx", "cargo"):
            if installers.get(candidate, False):
                return candidate
        return "winget"

    if installers.get("apt-get", False) or installers.get("dpkg-query", False):
        return "apt"
    if installers.get("brew", False):
        return "brew"
    if installers.get("uv", False):
        return "uv"
    if installers.get("pipx", False):
        return "pipx"
    if installers.get("cargo", False):
        return "cargo"

    return "apt"


def _recommended_manager_list(
    command_name: str,
    package_name: str,
    installers: Dict[str, bool],
) -> List[str]:
    policy = _load_manager_policy()
    os_tag = _os_tag()
    preferred = _policy_manager_list(policy, os_tag, command_name, package_name)
    if preferred:
        return preferred

    # Fallback ordering mirrors _choose_best_manager_for_install.
    if _is_termux():
        return ["pkg", "apt", "uv", "pipx", "cargo"]
    if _is_windows():
        return ["winget", "scoop", "choco", "uv", "pipx", "cargo"]
    if installers.get("apt-get", False) or installers.get("dpkg-query", False):
        return ["apt", "brew", "uv", "pipx", "cargo"]
    return ["brew", "uv", "pipx", "cargo", "apt"]


def plan_install_tool(
    command_name: str,
    package_name: str,
    manager: str,
) -> List[PlannedAction]:
    pkg = _map_common_packages(package_name, manager)
    actions: List[PlannedAction] = []

    if manager == "pkg":
        actions.append(
            PlannedAction(
                description=f"Install '{pkg}' via Termux pkg",
                command_argv=["sh", "-c", f"pkg update -y && pkg install -y {pkg}"],
                shell_hint="bash",
            )
        )
        return actions

    if manager == "apt":
        actions.append(
            PlannedAction(
                description=f"Install '{pkg}' via apt-get",
                command_argv=["sh", "-c", f"sudo apt-get update && sudo apt-get install -y {pkg}"],
                shell_hint="bash",
            )
        )
        return actions

    if manager == "brew":
        actions.append(
            PlannedAction(
                description=f"Install '{pkg}' via brew",
                command_argv=["sh", "-c", f"brew install {pkg}"],
                shell_hint="bash",
            )
        )
        return actions

    if manager == "winget":
        # Prefer exact ID if user passed it as package_name (common pattern)
        if "." in pkg:
            actions.append(
                PlannedAction(
                    description=f"Install '{pkg}' via winget (exact id)",
                    command_argv=["winget", "install", "--id", pkg, "-e"],
                    shell_hint="powershell",
                )
            )
        else:
            actions.append(
                PlannedAction(
                    description=f"Install '{pkg}' via winget (by name)",
                    command_argv=["winget", "install", "--name", pkg],
                    shell_hint="powershell",
                )
            )
        return actions

    if manager == "scoop":
        actions.append(
            PlannedAction(
                description=f"Install '{pkg}' via scoop",
                command_argv=["powershell", "-NoProfile", "-Command", f"scoop install {pkg}"],
                shell_hint="powershell",
            )
        )
        return actions

    if manager == "choco":
        actions.append(
            PlannedAction(
                description=f"Install '{pkg}' via chocolatey",
                command_argv=["choco", "install", pkg, "-y"],
                shell_hint="powershell",
            )
        )
        return actions

    if manager == "pipx":
        actions.append(
            PlannedAction(
                description=f"Install '{pkg}' via pipx",
                command_argv=["pipx", "install", pkg],
                shell_hint="powershell" if _is_windows() else "bash",
            )
        )
        return actions

    if manager == "uv":
        actions.append(
            PlannedAction(
                description=f"Install '{pkg}' via uv tool",
                command_argv=["uv", "tool", "install", pkg],
                shell_hint="powershell" if _is_windows() else "bash",
            )
        )
        return actions

    if manager == "cargo":
        actions.append(
            PlannedAction(
                description=f"Install '{pkg}' via cargo",
                command_argv=["cargo", "install", pkg],
                shell_hint="powershell" if _is_windows() else "bash",
            )
        )
        return actions

    actions.append(
        PlannedAction(
            description=f"Unknown manager '{manager}'. No plan available.",
            command_argv=[],
            shell_hint="",
        )
    )
    return actions


def _format_argv_for_display(argv: List[str], shell_hint: str) -> str:
    if not argv:
        return ""
    if shell_hint in ("bash", "zsh"):
        return " ".join(shlex_quote(a) for a in argv)
    return " ".join(powershell_quote(a) for a in argv)


def shlex_quote(s: str) -> str:
    # Minimal POSIX shell quoting.
    if s == "":
        return "''"
    if re.fullmatch(r"[A-Za-z0-9_@%+=:,./-]+", s):
        return s
    return "'" + s.replace("'", "'\"'\"'") + "'"


def powershell_quote(s: str) -> str:
    # Minimal PowerShell quoting.
    if s == "":
        return "''"
    if re.fullmatch(r"[A-Za-z0-9_@%+=:,./-]+", s):
        return s
    return "'" + s.replace("'", "''") + "'"


def _primary_path(paths: List[str]) -> Optional[str]:
    return paths[0] if paths else None


def build_isin_report(command_name: str, package_name: Optional[str] = None) -> IsInReport:
    pkg = package_name or command_name
    st = tool_status(command_name=command_name, package_name=pkg)

    managers = {c.manager.lower() for c in st.candidates}
    return IsInReport(
        command_name=command_name,
        package_name=pkg,
        primary_path=_primary_path(st.executable_paths),
        all_paths=st.executable_paths,
        candidates=st.candidates,
        recommended=st.recommended,
        duplicate_paths=len(st.executable_paths) > 1,
        duplicate_managers=len(managers) > 1,
    )


def plan_uninstall_duplicates(
    report: IsInReport,
    keep_manager: Optional[str] = None,
) -> List[PlannedAction]:
    keep = (keep_manager or (report.recommended.manager if report.recommended else "")).lower()
    actions: List[PlannedAction] = []

    seen = set()
    for cand in report.candidates:
        mgr = cand.manager.lower()
        if mgr == keep:
            continue
        if not cand.uninstall_hint:
            continue
        key = (mgr, cand.package_id or "", cand.uninstall_hint)
        if key in seen:
            continue
        seen.add(key)
        shell_hint = "powershell" if _is_windows() else "bash"
        actions.append(
            PlannedAction(
                description=f"Uninstall {report.command_name} via {cand.manager}",
                command_argv=["sh", "-c", cand.uninstall_hint] if shell_hint == "bash" else ["powershell", "-Command", cand.uninstall_hint],
                shell_hint=shell_hint,
            )
        )
    return actions


def apply_actions(
    actions: List[PlannedAction],
    apply: bool,
    assume_yes: bool,
    verbose: bool,
) -> int:
    for act in actions:
        display = _format_argv_for_display(act.command_argv, act.shell_hint)
        if act.command_argv:
            print(f"- {act.description}\n  -> {display}\n")
        else:
            print(f"- {act.description}\n")

        if not apply or not act.command_argv:
            continue

        ok = _prompt_yes_no(f"Run this command now? ({act.shell_hint})", assume_yes=assume_yes)
        if not ok:
            return 2

        if verbose:
            print(f"EXEC: {display}")

        rc, out, err = _run_cmd(act.command_argv, timeout_s=900.0)
        if out.strip():
            print(out.rstrip())
        if err.strip():
            print(err.rstrip())
        if rc != 0:
            print(f"ERROR: command failed with exit code {rc}")
            return rc

    return 0


def ensure_tool_installed(
    command_name: str,
    package_name: Optional[str],
    preferred_manager: Optional[str],
    apply: bool,
    assume_yes: bool,
    verbose: bool,
    notebook_root_dir: Optional[Path],
) -> int:
    pkg = package_name or command_name

    st = tool_status(command_name=command_name, package_name=pkg)
    if st.executable_path:
        print(f"FOUND: {command_name} -> {st.executable_path}")
        if st.recommended and st.recommended.upgrade_hint:
            print(f"Recommended upgrade:\n  {st.recommended.upgrade_hint}")
        else:
            print("No confident upgrade path detected. (May be manual install.)")
        return 0

    installers = detect_installers()
    recommended_list = _recommended_manager_list(
        command_name=command_name,
        package_name=pkg,
        installers=installers,
    )

    strong = [c for c in st.candidates if c.confidence >= 0.80]
    if strong:
        best = strong[0]
        msg = (
            f"\nWARNING: '{command_name}' appears installed via {best.manager}, "
            "but it is not currently on PATH.\n"
            f"Evidence: {best.evidence}\n"
        )
        if best.upgrade_hint:
            msg += f"\nRecommended upgrade:\n  {best.upgrade_hint}\n"
        print(msg)
        ok = _prompt_yes_no("Install another copy anyway?", assume_yes=assume_yes)
        if not ok:
            return 2

    mgr = (preferred_manager or "").strip().lower() or _choose_best_manager_for_install(command_name, pkg, installers)
    if preferred_manager and recommended_list and mgr not in recommended_list:
        msg = (
            f"\nWARNING: '{command_name}' is usually best installed via: {', '.join(recommended_list)}\n"
            f"You requested: {mgr}\n"
        )
        print(msg)
        ok = _prompt_yes_no("Proceed with this installer?", assume_yes=assume_yes)
        if not ok:
            return 2

    # If the chosen manager is missing, propose installing it first.
    if mgr in ("pipx", "uv", "brew", "scoop", "choco", "cargo", "rustup") and not installers.get(mgr, False):
        print(f"Installer '{mgr}' not found. Planning to install it first.\n")
        pre = installer_install_commands(mgr)
        rc = apply_actions(pre, apply=apply, assume_yes=assume_yes, verbose=verbose)
        if rc != 0:
            return rc

    # Refresh after possible installer install.
    installers = detect_installers()

    # If still missing, stop.
    if mgr in ("winget", "pipx", "uv", "brew", "apt", "pkg", "scoop", "choco", "cargo") and mgr not in installers and mgr not in ("apt", "pkg"):
        print(f"ERROR: installer '{mgr}' still not available on PATH.")
        return 2

    actions = plan_install_tool(command_name=command_name, package_name=pkg, manager=mgr)
    rc = apply_actions(actions, apply=apply, assume_yes=assume_yes, verbose=verbose)
    if rc != 0:
        return rc

    # Verify installed
    exe = _which(command_name)
    if not exe:
        print(f"WARNING: install completed, but '{command_name}' is not on PATH yet.")
        print("If this is a user-scope install (pipx/uv/cargo), you may need to start a new shell or update PATH.")
        return 0

    ver = get_command_version(command_name)
    upsert_record(
        make_record(
            command_name=command_name,
            package_name=pkg,
            manager=mgr,
            executable_path=exe,
            version=ver,
        ),
        root_dir=notebook_root_dir,
    )

    print(f"OK: {command_name} -> {exe}")
    if ver:
        print(f"Version: {ver}")
    return 0
