"""
system_tools: A cross-platform system utilities package.

Provides:
  - Core utilities for OS detection and command execution.
  - File system, network, process/service, and privilege management.
  - Detailed system information gathering for Windows, Linux, macOS, and Termux.
"""

from .core.system_utils import SystemUtils
from .core.debug_utils import write_debug
from .core.clipboard_utils import *  # or select specific functions/classes

from .file_system.file_system_manager import FileSystemManager
from .network.network_utils import NetworkUtils
from .process.process_manager import ProcessManager
from .process.service_manager import ServiceManager
from .privileges.privileges_manager import PrivilegesManager

# Optionally, re-export system information functions:
from .system_info import *
