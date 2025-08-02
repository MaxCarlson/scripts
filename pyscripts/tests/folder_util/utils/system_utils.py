# folder_util/utils/system_utils.py

import platform
import subprocess
import os
from .debug_utils import write_debug

class SystemUtils:
    """Base class for cross-platform system utilities."""
    def __init__(self):
        self.os_name = platform.system().lower()
        write_debug(f"Initialized SystemUtils for OS: {self.os_name}", channel="Debug")
    def is_termux(self) -> bool:
        is_termux = "ANDROID_ROOT" in os.environ and "com.termux" in os.environ.get("SHELL", "")
        write_debug(f"is_termux: {is_termux}", channel="Debug")
        return is_termux
    def is_wsl2(self) -> bool:
        is_wsl = "microsoft" in platform.uname().release.lower()
        write_debug(f"is_wsl2: {is_wsl}", channel="Debug")
        return is_wsl
    def run_command(self, command: str, sudo: bool = False) -> str:
        try:
            if sudo and self.os_name in ["linux", "darwin"] and not self.is_termux():
                command = f"sudo {command}"
                write_debug(f"Prepended sudo: {command}", channel="Debug")
            write_debug(f"Running command: {command}", channel="Debug")
            result = subprocess.run(command, shell=True, text=True, capture_output=True)
            if result.returncode == 0:
                write_debug(f"Command succeeded: {command}", channel="Debug")
                return result.stdout.strip()
            else:
                write_debug(f"Command failed: {command}\nError: {result.stderr.strip()}", channel="Error")
                return ""
        except Exception as e:
            write_debug(f"Exception while running command '{command}': {e}", channel="Critical")
            return ""
    def source_file(self, filepath: str) -> bool:
        try:
            if self.os_name in ["linux", "darwin"] and not self.is_termux():
                command = f"source {filepath}"
                write_debug(f"Attempting to source file with command: {command}", channel="Debug")
                result = subprocess.run(["zsh", "-c", command], text=True, capture_output=True)
                if result.returncode == 0:
                    write_debug(f"Sourced file successfully: {filepath}", channel="Debug")
                    return True
                else:
                    write_debug(f"Failed to source file: {filepath}\nError: {result.stderr.strip()}", channel="Error")
                    return False
            else:
                write_debug(f"Automatic sourcing not supported on OS: {self.os_name} or under Termux.", channel="Debug")
                return False
        except Exception as e:
            write_debug(f"Exception while sourcing file {filepath}: {e}", channel="Critical")
            return False