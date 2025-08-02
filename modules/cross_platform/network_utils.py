# cross_platform/network_utils.py
from .system_utils import SystemUtils
from .debug_utils import write_debug

class NetworkUtils(SystemUtils):
    """
    Provides cross-platform network utilities.
    Example: resetting network settings.
    """
    def reset_network(self) -> str:
        write_debug("Attempting to reset network...", channel="Information")
        
        # is_termux() check should be specific and not override os_name checks incorrectly
        # Typically, Termux runs on 'linux' os_name.
        if self.is_termux(): # Prioritize Termux if detected
            cmd = "svc wifi disable && svc wifi enable"
            write_debug("Detected Termux environment for network reset.", channel="Debug")
            return self.run_command(cmd, sudo=True) # Assuming sudo is appropriate for Termux root commands
        elif self.os_name == "windows":
            cmd = ("netsh winsock reset && netsh int ip reset && "
                   "ipconfig /release && ipconfig /renew && ipconfig /flushdns")
            write_debug("Detected Windows OS for network reset.", channel="Debug")
            return self.run_command(cmd, sudo=False) # Windows commands like netsh don't use 'sudo'
        elif self.os_name == "linux": # This will be non-Termux Linux
            cmd = "systemctl restart NetworkManager"
            write_debug("Detected Linux OS (non-Termux) for network reset.", channel="Debug")
            return self.run_command(cmd, sudo=True)
        elif self.os_name == "darwin":
            cmd = "ifconfig en0 down && ifconfig en0 up && killall -HUP mDNSResponder"
            write_debug("Detected macOS for network reset.", channel="Debug")
            return self.run_command(cmd, sudo=True)
        else:
            write_debug(f"Unsupported OS '{self.os_name}' for network reset.", channel="Error")
            return ""
