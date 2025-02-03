import os
import sys
import platform
import subprocess
from .system_utils import SystemUtils
from .debug_utils import write_debug

class ClipboardUtils(SystemUtils):
    """
    Provides cross-platform clipboard management.
    Uses SystemUtils for OS detection (including Termux and WSL2)
    and debug utilities for logging.
    """

    def get_clipboard(self) -> str:
        """
        Retrieve clipboard contents, supporting:
          - Termux (Android)
          - WSL2 (using win32yank)
          - Linux (using xclip)
          - Windows (using PowerShell)
          - macOS (using pbpaste)
        """
        try:
            if self.is_termux():
                write_debug("Using Termux clipboard retrieval.", channel="Information")
                output = self.run_command("termux-clipboard-get")
                return output if output is not None else ""

            if self.is_wsl2():
                write_debug("Using WSL2 clipboard retrieval via win32yank.", channel="Information")
                output = self.run_command("win32yank -o")
                return output if output is not None else ""

            system = self.os_name
            write_debug(f"Detected system for clipboard retrieval: {system}", channel="Debug")

            if system == "windows":
                output = self.run_command("powershell -command \"Get-Clipboard\"")
                return output if output is not None else ""
            elif system == "linux":
                output = self.run_command("xclip -selection clipboard -o")
                return output if output is not None else ""
            elif system == "darwin":
                output = self.run_command("pbpaste")
                return output if output is not None else ""
            else:
                write_debug("Unsupported OS for clipboard retrieval.", channel="Error")
                sys.exit(1)
        except Exception as e:
            write_debug(f"Error fetching clipboard: {e}", channel="Error")
            sys.exit(1)

    def set_clipboard(self, text: str) -> None:
        """
        Set clipboard contents, supporting:
          - Termux (Android)
          - WSL2 (using win32yank)
          - Linux (using xclip)
          - Windows (using PowerShell)
          - macOS (using pbcopy)
        """
        try:
            if self.is_termux():
                write_debug("Using Termux clipboard setting.", channel="Information")
                subprocess.run(["termux-clipboard-set"], input=text, text=True, check=True)
                return

            if self.is_wsl2():
                write_debug("Using WSL2 clipboard setting via win32yank.", channel="Information")
                subprocess.run(["win32yank", "-i"], input=text, text=True, check=True)
                return

            system = self.os_name
            write_debug(f"Detected system for clipboard setting: {system}", channel="Debug")

            if system == "windows":
                subprocess.run(["powershell", "-command", f"Set-Clipboard -Value \"{text}\""], text=True, check=True)
            elif system == "linux":
                subprocess.run(["xclip", "-selection", "clipboard"], input=text, text=True, check=True)
            elif system == "darwin":
                subprocess.run(["pbcopy"], input=text, text=True, check=True)
            else:
                write_debug("Unsupported OS for setting clipboard.", channel="Error")
                sys.exit(1)
        except Exception as e:
            write_debug(f"Error setting clipboard: {e}", channel="Error")
            sys.exit(1)

# Module-level function that wraps the class method
def get_clipboard() -> str:
    instance = ClipboardUtils()
    return instance.get_clipboard()

def set_clipboard(text: str) -> None:
    instance = ClipboardUtils()
    instance.set_clipboard(text)
