"""Read-only Windows Terminal / conhost delegation and host-vs-client modeling."""

from __future__ import annotations

from dataclasses import dataclass

_WT_GUIDS = {
    "{2EACA947-7F5F-4CFA-BA87-8F7FBEEFBE69}",
    "{E12CFF52-A866-4C77-9A90-F570A7AA2C6B}",
}
_CONHOST_GUID = "{B23D10C0-E52E-411E-9D5B-C09FDF709C7D}"
_DECIDE_GUID = "{00000000-0000-0000-0000-000000000000}"

TERMINAL_HOST_IMAGES = frozenset({"windowsterminal.exe", "openconsole.exe", "conhost.exe"})


@dataclass(slots=True)
class TerminalDelegationStatus:
    """Read-only HKCU\\Console\\%%Startup delegation configuration."""

    delegation_console: str | None = None
    delegation_terminal: str | None = None
    default_host: str = "unknown"  # windows_terminal | conhost | windows_default | unknown


def read_console_delegation_status() -> TerminalDelegationStatus:
    """Inspect HKCU\\Console\\%%Startup without modifying any registry keys."""
    try:
        import winreg
    except ImportError:
        return TerminalDelegationStatus()

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Console\%%Startup", 0, winreg.KEY_READ) as key:
            console_val = _read_reg_str(winreg, key, "DelegationConsole")
            term_val = _read_reg_str(winreg, key, "DelegationTerminal")
    except OSError:
        return TerminalDelegationStatus(default_host="windows_default")

    probe = (term_val or console_val or "").upper()
    if probe in _WT_GUIDS:
        host = "windows_terminal"
    elif probe == _CONHOST_GUID:
        host = "conhost"
    elif probe == _DECIDE_GUID or not probe:
        host = "windows_default"
    else:
        host = "custom"

    return TerminalDelegationStatus(
        delegation_console=console_val,
        delegation_terminal=term_val,
        default_host=host,
    )


def _read_reg_str(winreg_mod: object, key: object, name: str) -> str | None:
    try:
        val, _ = winreg_mod.QueryValueEx(key, name)  # type: ignore[attr-defined]
        return str(val) if val is not None else None
    except OSError:
        return None


def is_terminal_host_image(image_name: str | None) -> bool:
    """Return True when image_name is a console host / terminal UI container process."""
    if not image_name:
        return False
    return image_name.strip().lower() in TERMINAL_HOST_IMAGES
