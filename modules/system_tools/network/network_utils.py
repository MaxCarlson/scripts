from .system_utils import SystemUtils
from .debug_utils import write_debug

class NetworkUtils(SystemUtils):
    """
    Provides cross-platform network utilities.
    Example: resetting network settings.
    """
    def reset_network(self) -> str:
        write_debug("Attempting to reset network...", channel="Information")
        if self.os_name == "windows":
            cmd = ("netsh winsock reset && netsh int ip reset && "
                   "ipconfig /release && ipconfig /renew && ipconfig /flushdns")
            write_debug("Detected Windows OS for network reset.", channel="Debug")
            return self.run_command(cmd, sudo=True)
        elif self.is_termux():
            cmd = "svc wifi disable && svc wifi enable"
            write_debug("Detected Termux environment for network reset.", channel="Debug")
            return self.run_command(cmd, sudo=True)
        elif self.os_name == "linux":
            cmd = "systemctl restart NetworkManager"
            write_debug("Detected Linux OS for network reset.", channel="Debug")
            return self.run_command(cmd, sudo=True)
        elif self.os_name == "darwin":
            cmd = "ifconfig en0 down && ifconfig en0 up && killall -HUP mDNSResponder"
            write_debug("Detected macOS for network reset.", channel="Debug")
            return self.run_command(cmd, sudo=True)
        else:
            write_debug("Unsupported OS for network reset.", channel="Error")
            return ""

