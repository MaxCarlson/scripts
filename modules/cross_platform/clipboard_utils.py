#!/usr/bin/env python3
# File: modules/cross_platform/clipboard_utils.py

import os
import sys
import platform
import subprocess
import base64
import shutil
from typing import Optional


def _log(level: str, msg: str):
    prefix = {
        "Debug": "[Debug]",
        "Information": "[Information]",
        "Warning": "[Warning]",
        "Error": "[Error]",
        "SUCCESS": "[SUCCESS]",
    }.get(level, "[Info]")
    print(f"{prefix} {msg}")


class ClipboardUtils:
    """
    Cross-platform clipboard helper.

    Public API kept stable for callers:
      - class ClipboardUtils
      - set_clipboard(text: str)
      - get_clipboard() -> str

    Also exposes module-level wrappers set_clipboard()/get_clipboard() below.
    """

    def __init__(self):
        self._os = platform.system().lower()
        _log("Debug", f"Initialized ClipboardUtils for OS: {self._os}")

    # ------------------------
    # Environment detection
    # ------------------------
    def is_tmux(self) -> bool:
        return bool(os.environ.get("TMUX"))

    def is_wsl2(self) -> bool:
        try:
            rel = platform.uname().release
            return "microsoft" in rel.lower()
        except Exception:
            return False

    def is_termux(self) -> bool:
        # Termux presence heuristic
        return "ANDROID_ROOT" in os.environ or os.path.exists("/data/data/com.termux")

    def os_name(self) -> str:
        return self._os

    # ------------------------
    # Helpers
    # ------------------------
    def _run(
        self,
        args: list[str],
        *,
        input_text: Optional[str] = None,
        check: bool = False,
    ) -> subprocess.CompletedProcess:
        return subprocess.run(
            args,
            input=input_text,
            text=True,
            capture_output=True,
            check=check,
        )

    # ------------------------
    # OSC 52 helpers
    # ------------------------
    def _emit_osc52(self, text: str):
        # Base64-encode per OSC 52 spec
        encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
        osc = f"\033]52;c;{encoded}\a"

        if self.is_tmux():
            # tmux passthrough: ESC P tmux; <OSC> BEL ESC \
            wrapped = f"\033Ptmux;{osc}\033\\"
            _log("Information", "Inside tmux: using OSC 52 with tmux passthrough.")
            try:
                sys.stdout.write(wrapped)
                sys.stdout.flush()
            except Exception as e:
                _log("Warning", f"Failed to write OSC 52 via tmux passthrough: {e}")
        else:
            _log("Information", "Emitting OSC 52 for local clipboard.")
            try:
                sys.stdout.write(osc)
                sys.stdout.flush()
            except Exception as e:
                _log("Warning", f"Failed to write OSC 52: {e}")

    # ------------------------
    # Clipboard (SET)
    # ------------------------
    def set_clipboard(self, text: str):
        """
        Strategy:
          1) Always try OSC 52 (updates local terminal clipboard)
          2) If tmux, also push to tmux buffer (stdin to avoid 'no data specified')
          3) Platform-native set:
             - Termux: termux-clipboard-set
             - macOS : pbcopy
             - Linux : wl-copy | xclip | xsel
             - Windows: pwsh/powershell Set-Clipboard (NoProfile) or clip.exe
        """
        # 1) OSC 52 for local terminal clipboard
        self._emit_osc52(text)

        # 2) tmux side buffer (best-effort)
        if self.is_tmux():
            try:
                # IMPORTANT: feed data via stdin so tmux doesn't complain
                self._run(["tmux", "set-buffer", "-w", "--"], input_text=text, check=True)
                _log("Information", "tmux set-buffer passthrough OK.")
            except Exception as e:
                _log("Warning", f"tmux set-buffer failed (continuing): {e}")

        # 3) Platform-native
        osname = self.os_name()

        # Termux (works even within tmux)
        if self.is_termux():
            try:
                self._run(["termux-clipboard-set"], input_text=text, check=True)
                _log("Information", "Using Termux clipboard setting.")
                return
            except Exception as e:
                _log("Warning", f"Termux clipboard set failed (continuing): {e}")
                # Fall through to OSC52-only behavior

        if osname == "darwin":
            try:
                self._run(["pbcopy"], input_text=text, check=True)
                return
            except Exception as e:
                _log("Warning", f"pbcopy failed (continuing): {e}")
                return  # OSC52 already done

        if osname == "linux":
            for prog in (["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]):
                if shutil.which(prog[0]):
                    try:
                        self._run(prog, input_text=text, check=True)
                        return
                    except Exception as e:
                        _log("Warning", f"{' '.join(prog)} failed (continuing): {e}")
            return  # OSC52 already done

        if osname == "windows":
            # Prefer PowerShell 7 first; never load profiles; read from stdin.
            if shutil.which("pwsh"):
                try:
                    self._run(
                        ["pwsh", "-NoProfile", "-NonInteractive", "-Command",
                         "Set-Clipboard -Value ([Console]::In.ReadToEnd())"],
                        input_text=text, check=True
                    )
                    return
                except Exception as e:
                    _log("Warning", f"pwsh Set-Clipboard failed: {e}")

            # clip.exe reads stdin and is usually present
            if shutil.which("clip"):
                try:
                    self._run(["clip"], input_text=text, check=True)
                    return
                except Exception as e:
                    _log("Warning", f"clip.exe failed: {e}")

            # Fallback to WindowsPowerShell, still no profile
            try:
                self._run(
                    ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                     "Set-Clipboard -Value ([Console]::In.ReadToEnd())"],
                    input_text=text, check=True
                )
                return
            except Exception as e:
                _log("Error", f"powershell Set-Clipboard failed: {e}")
                return

        # Unknown OS — OSC 52 likely already did the job
        _log("Warning", "No native clipboard method matched; relied on OSC 52.")

    # ------------------------
    # Clipboard (GET)
    # ------------------------
    def get_clipboard(self) -> str:
        osname = self.os_name()

        if self.is_termux():
            try:
                res = self._run(["termux-clipboard-get"], check=True)
                return res.stdout
            except Exception as e:
                _log("Warning", f"Termux clipboard get failed: {e}")
                return ""

        if osname == "darwin":
            try:
                res = self._run(["pbpaste"], check=True)
                return res.stdout
            except Exception as e:
                _log("Warning", f"pbpaste failed: {e}")
                return ""

        if osname == "linux":
            for prog in (["wl-paste"], ["xclip", "-selection", "clipboard", "-o"], ["xsel", "--clipboard", "--output"]):
                if shutil.which(prog[0]):
                    try:
                        res = self._run(prog, check=True)
                        return res.stdout
                    except Exception as e:
                        _log("Warning", f"{' '.join(prog)} failed: {e}")
            return ""

        if osname == "windows":
            ps = "pwsh" if shutil.which("pwsh") else "powershell"
            try:
                res = self._run([ps, "-NoProfile", "-NonInteractive", "-Command", "Get-Clipboard -Raw"], check=True)
                return res.stdout
            except Exception as e:
                _log("Warning", f"{ps} Get-Clipboard failed: {e}")
                return ""

        return ""


# ------------- Module-level convenience (preserve existing imports) -------------
_utils_singleton: Optional[ClipboardUtils] = None

def _U() -> ClipboardUtils:
    global _utils_singleton
    if _utils_singleton is None:
        _utils_singleton = ClipboardUtils()
    return _utils_singleton

def set_clipboard(text: str):
    _U().set_clipboard(text)

def get_clipboard() -> str:
    return _U().get_clipboard()

__all__ = ["ClipboardUtils", "set_clipboard", "get_clipboard"]
