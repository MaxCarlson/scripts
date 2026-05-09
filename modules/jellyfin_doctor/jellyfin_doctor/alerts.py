"""User alerts for long-running monitor commands."""

from __future__ import annotations

import os


def beep() -> bool:
    """Emit an audible alert when possible."""
    if os.name == "nt":
        try:
            import winsound

            winsound.Beep(1000, 700)
            return True
        except Exception:
            pass
    print("\a", end="")
    return False


def popup(title: str, message: str) -> bool:
    """Show a Windows message box when available."""
    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, message, title, 0x40)
            return True
        except Exception:
            pass
    print(f"{title}: {message}")
    return False


def notify(title: str, message: str, *, beep_alert: bool = False, popup_alert: bool = False) -> dict[str, bool]:
    """Run requested alert channels."""
    result = {"beep": False, "popup": False}
    if beep_alert:
        result["beep"] = beep()
    if popup_alert:
        result["popup"] = popup(title, message)
    return result

