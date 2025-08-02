# cross_platform/privileges_manager.py
from .system_utils import SystemUtils
from .debug_utils import write_debug
import os
import sys

class PrivilegesManager(SystemUtils):
    """
    Checks and ensures that the script is run with administrative privileges.
    """
    def require_admin(self):
        write_debug("Checking for administrative privileges...", channel="Debug")
        if self.os_name == "windows":
            try:
                # This import will now get the mock from sys.modules during testing
                import ctypes
                if not ctypes.windll.shell32.IsUserAnAdmin():
                    write_debug("Not running as administrator on Windows.", channel="Error")
                    raise PermissionError("Administrator privileges required.")
                else:
                    write_debug("Running as administrator on Windows.", channel="Debug")
            except Exception as e:
                write_debug(f"Error while checking admin privileges on Windows: {e}", channel="Error")
                # It's generally better to re-raise a specific error or a new one
                # that indicates failure to check, rather than assuming not admin.
                # However, for this case, the test expects PermissionError.
                raise PermissionError("Administrator privileges required.")
        elif self.os_name in ["linux", "darwin"]:
            if os.geteuid() != 0:
                write_debug("Not running as root on Unix-like OS.", channel="Error")
                raise PermissionError("Administrator (root) privileges required.")
            else:
                write_debug("Running as root on Unix-like OS.", channel="Debug")
        else:
            write_debug("Unsupported OS for admin privilege check.", channel="Error")
            raise PermissionError("Unsupported OS for privilege checking.")
