# modules/cross_platform/clipboard_utils.py

import os
import sys
import platform
import subprocess
import base64
from .system_utils import SystemUtils
from .debug_utils import write_debug

class ClipboardUtils(SystemUtils):
    """
    Provides cross-platform clipboard management.
    """

    def get_clipboard(self) -> str:
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
        Set clipboard contents and always send OSC 52 to update the local clipboard.
        """
        try:
            # Always attempt OSC 52 (for the local clipboard)
            try:
                write_debug("Sending OSC 52 sequence to update local clipboard.", channel="Information")
                encoded = base64.b64encode(text.encode("utf-8")).decode("utf-8")
                osc52_sequence = f"\033]52;c;{encoded}\a"
                # This prints the sequence to stdout. In most SSH clients with OSC 52 support, this should update the local clipboard.
                print(osc52_sequence, end="", flush=True)
            except Exception as osc_err:
                write_debug(f"Error sending OSC 52 sequence: {osc_err}", channel="Error")

            # Then, update the remote clipboard using the appropriate method
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

# Module-level functions that wrap the class methods
def get_clipboard() -> str:
    instance = ClipboardUtils()
    return instance.get_clipboard()

def set_clipboard(text: str) -> None:
    instance = ClipboardUtils()
    instance.set_clipboard(text)

