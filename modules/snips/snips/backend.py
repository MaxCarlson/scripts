"""Windows AutoHotkey v2 discovery, installation, and login startup."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

OFFICIAL_DOWNLOADS = "https://www.autohotkey.com/download/2.0/"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "Snips"


def is_windows() -> bool:
    return os.name == "nt"


def _version(path: Path) -> str:
    if not is_windows():
        return "unknown"
    import ctypes
    from ctypes import wintypes

    size = ctypes.windll.version.GetFileVersionInfoSizeW(str(path), None)
    if not size:
        return "unknown"
    buffer = ctypes.create_string_buffer(size)
    if not ctypes.windll.version.GetFileVersionInfoW(str(path), 0, size, buffer):
        return "unknown"
    pointer = ctypes.c_void_p()
    length = wintypes.UINT()
    if not ctypes.windll.version.VerQueryValueW(buffer, "\\", ctypes.byref(pointer), ctypes.byref(length)):
        return "unknown"

    class VS_FIXEDFILEINFO(ctypes.Structure):
        _fields_ = [
            ("dwSignature", wintypes.DWORD),
            ("dwStrucVersion", wintypes.DWORD),
            ("dwFileVersionMS", wintypes.DWORD),
            ("dwFileVersionLS", wintypes.DWORD),
            ("dwProductVersionMS", wintypes.DWORD),
            ("dwProductVersionLS", wintypes.DWORD),
        ]

    info = ctypes.cast(pointer, ctypes.POINTER(VS_FIXEDFILEINFO)).contents
    return ".".join(
        str(value)
        for value in (
            info.dwFileVersionMS >> 16,
            info.dwFileVersionMS & 0xFFFF,
            info.dwFileVersionLS >> 16,
            info.dwFileVersionLS & 0xFFFF,
        )
    )


def find_autohotkey() -> tuple[Path | None, str | None]:
    candidates: list[Path] = []
    for root in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if root:
            candidates.extend(
                [
                    Path(root) / "AutoHotkey" / "v2" / "AutoHotkey64.exe",
                    Path(root) / "AutoHotkey" / "v2" / "AutoHotkey.exe",
                ]
            )
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.extend(
            [
                Path(local) / "Programs" / "AutoHotkey" / "v2" / "AutoHotkey64.exe",
                Path(local) / "Programs" / "AutoHotkey" / "v2" / "AutoHotkey.exe",
            ]
        )
    scoop_roots = [os.environ.get("SCOOP"), os.environ.get("SCOOP_GLOBAL")]
    if os.environ.get("ProgramData"):
        scoop_roots.append(str(Path(os.environ["ProgramData"]) / "scoop"))
    scoop_roots.append(str(Path.home() / "scoop"))
    for root in scoop_roots:
        if root:
            version_dir = Path(root) / "apps" / "autohotkey" / "current" / "v2"
            candidates.extend([version_dir / "AutoHotkey64.exe", version_dir / "AutoHotkey.exe"])
    for command in ("AutoHotkey64.exe", "AutoHotkey.exe"):
        located = shutil.which(command)
        if located:
            candidates.append(Path(located))
    seen: set[str] = set()
    for path in candidates:
        key = str(path).casefold()
        if key in seen:
            continue
        seen.add(key)
        if path.is_file():
            version = _version(path)
            if version != "unknown" and int(version.split(".")[0]) == 2:
                return path.resolve(), version
    return None, None


def _run_install(command: list[str]) -> None:
    result = subprocess.run(command, check=False, text=True, capture_output=True, timeout=900)
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
        raise RuntimeError(f"Backend installer failed: {detail}")


def _official_installer() -> None:
    with urllib.request.urlopen(OFFICIAL_DOWNLOADS, timeout=20) as response:
        html = response.read().decode("utf-8", errors="replace")
    versions = re.findall(r"AutoHotkey_(2\.0\.(\d+))_setup\.exe", html, re.IGNORECASE)
    if not versions:
        raise RuntimeError(f"Could not locate a stable v2 installer at {OFFICIAL_DOWNLOADS}")
    version, _patch = max(versions, key=lambda item: tuple(int(part) for part in item[0].split(".")))
    name = f"AutoHotkey_{version}_setup.exe"
    url = urllib.parse.urljoin(OFFICIAL_DOWNLOADS, name)
    fd, path = tempfile.mkstemp(prefix="snips-autohotkey-", suffix=".exe")
    os.close(fd)
    try:
        urllib.request.urlretrieve(url, path)
        _run_install([path, "/silent"])
        Path(path).unlink(missing_ok=True)
    except Exception:
        Path(path).unlink(missing_ok=True)
        raise


def ensure_autohotkey(*, apply: bool) -> tuple[Path | None, str | None, str]:
    executable, version = find_autohotkey()
    if executable:
        return executable, version, f"Found AutoHotkey v{version} at {executable}"
    if not is_windows():
        raise RuntimeError("AutoHotkey setup is supported on Windows only")
    if not apply:
        available = []
        if shutil.which("winget"):
            available.append("WinGet (AutoHotkey.AutoHotkey)")
        if shutil.which("scoop"):
            available.append("Scoop Extras (autohotkey)")
        available.append("the official AutoHotkey v2 installer")
        return None, None, "Would install using " + ", then ".join(available)
    failures: list[str] = []
    installers: list[list[str]] = []
    if shutil.which("winget"):
        installers.append(
            [
                "winget",
                "install",
                "--id",
                "AutoHotkey.AutoHotkey",
                "--exact",
                "--silent",
                "--accept-package-agreements",
                "--accept-source-agreements",
            ]
        )
    if shutil.which("scoop"):
        installers.append(["scoop", "install", "extras/autohotkey"])
    for command in installers:
        try:
            _run_install(command)
        except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
            failures.append(str(exc))
            continue
        executable, version = find_autohotkey()
        if executable:
            return executable, version, f"Installed AutoHotkey v{version} at {executable}"
    try:
        _official_installer()
    except Exception as exc:
        failures.append(str(exc))
    executable, version = find_autohotkey()
    if not executable:
        detail = "; ".join(failures) if failures else "installer completed without a verifiable executable"
        raise RuntimeError(f"AutoHotkey installation could not be verified: {detail}")
    return executable, version, f"Installed AutoHotkey v{version} at {executable}"


def startup_command(executable: Path, script: Path) -> str:
    return f'"{executable}" "{script}"'


def register_startup(executable: Path, script: Path) -> tuple[bool, str]:
    import winreg

    if not is_windows():
        raise RuntimeError("Per-user startup registration is supported on Windows only")
    command = startup_command(executable, script)
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE) as key:
        try:
            existing, _ = winreg.QueryValueEx(key, RUN_VALUE)
        except FileNotFoundError:
            existing = None
        if existing == command:
            return False, "Per-user startup is already configured"
        if existing is not None:
            raise RuntimeError(
                f"HKCU Run value {RUN_VALUE!r} already exists with a different command; refusing to overwrite it"
            )
        winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, command)
        return True, "Registered snips for automatic per-user startup"


def startup_status(executable: Path, script: Path) -> dict[str, str | bool]:
    import winreg

    expected = startup_command(executable, script)
    if not is_windows():
        return {"configured": False, "command": expected}
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_QUERY_VALUE) as key:
            value, _ = winreg.QueryValueEx(key, RUN_VALUE)
    except FileNotFoundError:
        value = None
    return {"configured": value == expected, "command": str(value) if value else ""}
