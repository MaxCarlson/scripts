from .system_utils import SystemUtils
from .debug_utils import write_debug

class ServiceManager(SystemUtils):
    """
    Provides cross-platform service management utilities.
    Supports querying status, starting, and stopping services.
    """

    def service_status(self, service_name: str) -> str:
        """
        Retrieve the status of a specified service.
        """
        if self.os_name == "windows":
            cmd = f"sc query {service_name}"
        elif self.os_name == "linux":
            cmd = f"systemctl status {service_name}"
        elif self.os_name == "darwin":
            # For macOS, we list services via launchctl and filter by service name.
            cmd = f"launchctl list | grep {service_name}"
        else:
            write_debug("Unsupported OS for querying service status.", channel="Error")
            return ""

        write_debug(f"Querying status of service '{service_name}' with command: {cmd}", channel="Debug")
        return self.run_command(cmd, sudo=True)

    def start_service(self, service_name: str) -> str:
        """
        Start the specified service.
        """
        if self.os_name == "windows":
            cmd = f"net start {service_name}"
        elif self.os_name == "linux":
            cmd = f"systemctl start {service_name}"
        elif self.os_name == "darwin":
            cmd = f"launchctl start {service_name}"
        else:
            write_debug("Unsupported OS for starting service.", channel="Error")
            return ""

        write_debug(f"Starting service '{service_name}' with command: {cmd}", channel="Debug")
        return self.run_command(cmd, sudo=True)

    def stop_service(self, service_name: str) -> str:
        """
        Stop the specified service.
        """
        if self.os_name == "windows":
            cmd = f"net stop {service_name}"
        elif self.os_name == "linux":
            cmd = f"systemctl stop {service_name}"
        elif self.os_name == "darwin":
            cmd = f"launchctl stop {service_name}"
        else:
            write_debug("Unsupported OS for stopping service.", channel="Error")
            return ""

        write_debug(f"Stopping service '{service_name}' with command: {cmd}", channel="Debug")
        return self.run_command(cmd, sudo=True)

