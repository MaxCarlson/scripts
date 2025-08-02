from .system_utils import SystemUtils
from .debug_utils import write_debug

class ProcessManager(SystemUtils):
    """
    Manages processes across operating systems.
    Provides methods to list and terminate processes.
    """
    def list_processes(self) -> str:
        write_debug("Listing processes...", channel="Information")
        if self.os_name == "windows":
            cmd = "tasklist"
        elif self.os_name in ["linux", "darwin"]:
            cmd = "ps aux"
        else:
            write_debug("Unsupported OS for listing processes.", channel="Error")
            return ""
        
        output = self.run_command(cmd)
        write_debug("Process list retrieved.", channel="Debug")
        return output

    def kill_process(self, process_name: str) -> str:
        write_debug(f"Attempting to kill process: {process_name}", channel="Warning")
        if self.os_name == "windows":
            cmd = f"taskkill /IM {process_name} /F"
        elif self.os_name in ["linux", "darwin"]:
            cmd = f"pkill {process_name}"
        else:
            write_debug("Unsupported OS for killing processes.", channel="Error")
            return ""
        
        output = self.run_command(cmd, sudo=True)
        write_debug(f"Kill process command issued for: {process_name}", channel="Debug")
        return output

