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

    Behavior overview:
      • Always emit OSC 52 (to TTY only) so the *local* terminal/Termux can receive a copy over SSH/tmux.
      • On tmux, also try to push to the tmux buffer (stdin-based) as a best-effort.
      • Platform-native set/get:
          - Termux: termux-clipboard-set / termux-clipboard-get
          - macOS : pbcopy / pbpaste
          - Linux : wl-copy|xclip|xsel / wl-paste|xclip|xsel
          - Windows: robust PowerShell -EncodedCommand (UTF-8 payload) + clip.exe (UTF-16LE) fallback
          - WSL   : prefer win32yank (-i / -o) bridging to Windows clipboard, then clip.exe / PowerShell Get-Clipboard
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
        """Detect WSL (v1 or v2); both report 'Microsoft' in kernel release."""
        try:
            return "microsoft" in platform.uname().release.lower()
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
        text: bool = True,
    ) -> subprocess.CompletedProcess:
        return subprocess.run(
            args,
            input=input_text,
            text=text,
            capture_output=True,
            check=check,
        )

    # ------------------------
    # OSC 52 helpers
    # ------------------------
    def _emit_osc52(self, text: str):
        """
        Emit OSC 52 so the *local* terminal receives the clipboard
        (works over SSH if terminal/tmux allows OSC 52). Only emit
        to a TTY to avoid contaminating piped output.
        """
        if not sys.stdout.isatty():
            return

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
    # Windows robust setters
    # ------------------------
    def _pwsh_exe(self) -> Optional[str]:
        for exe in ("pwsh", "powershell", "powershell.exe"):
            p = shutil.which(exe)
            if p:
                return p
        return None

    def _set_clipboard_windows_robust(self, text: str) -> bool:
        """
        Use PowerShell -EncodedCommand (UTF-16LE) to decode a UTF-8
        payload *inside* PowerShell and Set-Clipboard. Ignores console codepages.
        """
        pwsh = self._pwsh_exe()
        if not pwsh:
            _log("Warning", "pwsh/powershell not found for robust Set-Clipboard.")
            return False

        payload_b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
        # Feed payload via stdin (base64) so we never hit Windows' ~8k command-line limit.
        ps_script = (
            "$b=[Console]::In.ReadToEnd();"
            "$bytes=[Convert]::FromBase64String($b);"
            "$str=[Text.Encoding]::UTF8.GetString($bytes);"
            "Set-Clipboard -Value $str"
        )
        encoded = base64.b64encode(ps_script.encode("utf-16le")).decode("ascii")
        try:
            cp = self._run(
                [pwsh, "-NoProfile", "-EncodedCommand", encoded],
                input_text=payload_b64,
                check=True,
            )
            _log("Information", "Windows Set-Clipboard via -EncodedCommand OK.")
            if cp.stdout.strip():
                _log("Debug", cp.stdout.strip())
            if cp.stderr.strip():
                _log("Debug", cp.stderr.strip())
            return True
        except subprocess.CalledProcessError as e:
            _log("Warning", f"Windows Set-Clipboard (-EncodedCommand) failed: rc={e.returncode} {e.stderr or e.stdout}")
            return False
        except Exception as e:
            _log("Warning", f"Windows Set-Clipboard (-EncodedCommand) exception: {e}")
            return False

    def _set_clipboard_windows_clip(self, text: str) -> bool:
        """
        Fallback to clip.exe; feed UTF-16LE bytes.
        """
        clip = shutil.which("clip") or shutil.which("clip.exe")
        if not clip:
            _log("Warning", "clip.exe not found.")
            return False
        try:
            # Send bytes, not text, so we control encoding precisely.
            proc = subprocess.run([clip], input=text.encode("utf-16le"))
            if proc.returncode == 0:
                _log("Information", "Windows clip.exe OK.")
                return True
            _log("Warning", f"clip.exe failed rc={proc.returncode}")
            return False
        except Exception as e:
            _log("Warning", f"clip.exe exception: {e}")
            return False

    # ------------------------
    # Clipboard (SET)
    # ------------------------
    def set_clipboard(self, text: str):
        """
        Strategy (dual-target):
          1) Always try OSC 52 (updates local terminal/Termux clipboard over SSH/tmux) — TTY only.
          2) If tmux, also push to tmux buffer (stdin to avoid 'no data specified').
          3) Platform-native set, including WSL bridges to Windows clipboard.
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

        # WSL prefers bridging to Windows clipboard (only when Linux kernel is active)
        if osname == "linux" and self.is_wsl2():
            # Best: win32yank bridges WSL <-> Windows clipboard
            if shutil.which("win32yank"):
                try:
                    self._run(["win32yank", "-i"], input_text=text, check=True)
                    return
                except Exception as e:
                    _log("Warning", f"win32yank -i failed (continuing): {e}")
            # Fallback: Windows clip.exe via interop (UTF-16LE)
            try:
                proc = subprocess.run(["clip.exe"], input=text.encode("utf-16le"))
                if proc.returncode == 0:
                    return
            except Exception as e:
                _log("Warning", f"clip.exe failed (continuing): {e}")
            # Last resort: treat like Linux (may be headless); OSC52 already emitted
            for prog in (["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]):
                if shutil.which(prog[0]):
                    try:
                        self._run(prog, input_text=text, check=True)
                        return
                    except Exception as e:
                        _log("Warning", f"{' '.join(prog)} failed (continuing): {e}")
            return

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
            # Robust path first (codepage-proof)
            if self._set_clipboard_windows_robust(text):
                return
            # Fallback: clip.exe with UTF-16LE
            if self._set_clipboard_windows_clip(text):
                return

            # Last chance: classic console stdin route (may fail on non-UTF-8 consoles)
            try:
                ps = "pwsh" if shutil.which("pwsh") else "powershell"
                self._run(
                    [ps, "-NoProfile", "-NonInteractive", "-Command",
                     "Set-Clipboard -Value ([Console]::In.ReadToEnd())"],
                    input_text=text, check=True
                )
                _log("Information", "Windows Set-Clipboard via stdin path OK.")
                return
            except Exception as e:
                _log("Error", f"{ps} Set-Clipboard (stdin path) failed: {e}")
                return

        # Unknown OS — OSC 52 likely already did the job
        _log("Warning", "No native clipboard method matched; relied on OSC 52.")

    # ------------------------
    # Clipboard (GET)
    # ------------------------
    def get_clipboard(self) -> str:
        osname = self.os_name()

        # Termux first
        if self.is_termux():
            try:
                res = self._run(["termux-clipboard-get"], check=True)
                return res.stdout
            except Exception as e:
                _log("Warning", f"Termux clipboard get failed: {e}")
                return ""

        # WSL prefers Windows clipboard (only when Linux kernel is active)
        if osname == "linux" and self.is_wsl2():
            # Prefer win32yank output (Windows clipboard)
            if shutil.which("win32yank"):
                try:
                    res = self._run(["win32yank", "-o"], check=True)
                    return res.stdout
                except Exception as e:
                    _log("Warning", f"win32yank -o failed: {e}")
            # Fallback: PowerShell Get-Clipboard (works from WSL via interop)
            pwsh = shutil.which("pwsh") or shutil.which("powershell.exe") or shutil.which("powershell")
            if pwsh:
                try:
                    # Use -Raw to preserve newlines
                    res = self._run([pwsh, "-NoProfile", "-Command", "Get-Clipboard -Raw"], check=True)
                    return res.stdout
                except Exception as e:
                    _log("Warning", f"{pwsh} Get-Clipboard failed: {e}")
            # Last resort: Linux tools (or empty)
            for prog in (["wl-paste"], ["xclip", "-selection", "clipboard", "-o"], ["xsel", "--clipboard", "--output"]):
                if shutil.which(prog[0]):
                    try:
                        res = self._run(prog, check=True)
                        return res.stdout
                    except Exception as e:
                        _log("Warning", f"{' '.join(prog)} failed: {e}")
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
            # Use -EncodedCommand so we are independent of console encodings
            ps = self._pwsh_exe()
            if ps:
                try:
                    script = "Get-Clipboard -Raw"
                    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
                    res = self._run([ps, "-NoProfile", "-EncodedCommand", encoded], check=True)
                    return res.stdout
                except Exception as e:
                    _log("Warning", f"{ps} Get-Clipboard failed: {e}")
                    return ""
            else:
                _log("Warning", "No PowerShell available for Get-Clipboard.")
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
