# modules/cross_platform/clipboard_utils.py
import os
import sys
import platform
import subprocess
import base64
import shutil

from .system_utils import SystemUtils
from .debug_utils import write_debug

class ClipboardUtils(SystemUtils):
    """
    Provides cross-platform clipboard management with SSH/tmux safe paths.
    """

    def _in_ssh(self) -> bool:
        return any(os.environ.get(k) for k in ("SSH_CLIENT", "SSH_CONNECTION", "SSH_TTY"))

    def _have(self, exe: str) -> bool:
        return shutil.which(exe) is not None

    def _linux_get(self) -> str:
        # Prefer Wayland, then X11
        if os.environ.get("WAYLAND_DISPLAY") and self._have("wl-paste"):
            return self.run_command("wl-paste")
        if os.environ.get("DISPLAY") and self._have("xclip"):
            return self.run_command("xclip -selection clipboard -o")
        if self._have("xsel"):
            return self.run_command("xsel --clipboard --output")
        write_debug("No clipboard backend found on Linux.", channel="Warning")
        return ""

    def _linux_set(self, text: str) -> None:
        if os.environ.get("WAYLAND_DISPLAY") and self._have("wl-copy"):
            subprocess.run(["wl-copy"], input=text, text=True, check=True)
            return
        if os.environ.get("DISPLAY") and self._have("xclip"):
            subprocess.run(["xclip", "-selection", "clipboard"], input=text, text=True, check=True)
            return
        if self._have("xsel"):
            subprocess.run(["xsel", "--clipboard", "--input"], input=text, text=True, check=True)
            return
        write_debug("No clipboard backend found on Linux for set.", channel="Warning")

    def get_clipboard(self) -> str:
        try:
            if self.is_termux():
                write_debug("Using Termux clipboard retrieval.", channel="Information")
                output = self.run_command("termux-clipboard-get")
                return output or ""

            if self.is_wsl2():
                write_debug("Using WSL2 via win32yank.", channel="Information")
                output = self.run_command("win32yank -o")
                return output or ""

            system = self.os_name
            write_debug(f"Detected system for clipboard retrieval: {system}", channel="Debug")

            if system == "windows":
                if self._in_ssh():
                    # Windows service session: GUI clipboard unavailable. Be explicit & safe.
                    write_debug("Windows over SSH: remote clipboard not accessible; returning empty.", channel="Warning")
                    return ""
                output = self.run_command('powershell -NoProfile -Command "Get-Clipboard"')
                return output or ""
            elif system == "linux":
                return self._linux_get()
            elif system == "darwin":
                output = self.run_command("pbpaste")
                return output or ""
            else:
                write_debug("Unsupported OS for clipboard retrieval.", channel="Error")
                sys.exit(1)
        except Exception as e:
            write_debug(f"Error fetching clipboard: {e}", channel="Error")
            sys.exit(1)

    def _osc52(self, text: str) -> None:
        try:
            write_debug("Emitting OSC 52 for local clipboard.", channel="Information")
            encoded = base64.b64encode(text.encode("utf-8")).decode("utf-8")
            seq = f"\033]52;c;{encoded}\a"
            print(seq, end="", flush=True)
        except Exception as e:
            write_debug(f"OSC 52 emission failed: {e}", channel="Warning")

    def _tmux_forward(self, text: str) -> None:
        # tmux 3.3+: set-buffer -w forwards OSC 52 to terminal (when allowed)
        if self.is_tmux() and self._have("tmux"):
            try:
                write_debug("Inside tmux: using 'tmux set-buffer -w' passthrough.", channel="Information")
                subprocess.run(["tmux", "set-buffer", "-w", "--"], input=text, text=True, check=True)
            except Exception as e:
                write_debug(f"tmux set-buffer failed (continuing): {e}", channel="Warning")

    def set_clipboard(self, text: str) -> None:
        """
        Set clipboard contents and always send OSC 52 to update the local clipboard.
        """
        try:
            # 1) Always try OSC 52 for the client
            self._osc52(text)

            # 2) tmux passthrough (helps when OSC 52 needs tmux involvement)
            self._tmux_forward(text)

            # 3) Also set the remote clipboard if it makes sense
            if self.is_termux():
                write_debug("Using Termux clipboard setting.", channel="Information")
                subprocess.run(["termux-clipboard-set"], input=text, text=True, check=True)
                return

            if self.is_wsl2():
                write_debug("Using WSL2 via win32yank.", channel="Information")
                subprocess.run(["win32yank", "-i"], input=text, text=True, check=True)
                return

            system = self.os_name
            write_debug(f"Detected system for clipboard setting: {system}", channel="Debug")

            if system == "windows":
                if self._in_ssh():
                    # Don’t try GUI clipboard in a service session
                    write_debug("Windows over SSH: skipping Set-Clipboard (service session).", channel="Information")
                    return
                subprocess.run(["powershell", "-NoProfile", "-Command", f"Set-Clipboard -Value @'\n{text}\n'@"], text=True, check=True)
            elif system == "linux":
                self._linux_set(text)
            elif system == "darwin":
                subprocess.run(["pbcopy"], input=text, text=True, check=True)
            else:
                write_debug("Unsupported OS for setting clipboard.", channel="Error")
                sys.exit(1)
        except Exception as e:
            write_debug(f"Error setting clipboard: {e}", channel="Error")
            sys.exit(1)

# Module-level wrappers unchanged
def get_clipboard() -> str:
    return ClipboardUtils().get_clipboard()

def set_clipboard(text: str) -> None:
    ClipboardUtils().set_clipboard(text)
