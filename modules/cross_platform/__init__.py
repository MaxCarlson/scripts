# __init__.py

# Import and expose core system utility classes and functions

# System utility base classes
from .system_utils import SystemUtils

# Clipboard utilities
from .clipboard_utils import ClipboardUtils

# Network utilities
from .network_utils import NetworkUtils

# Process and file system management
from .process_manager import ProcessManager
from .file_system_manager import FileSystemManager

# Service and privileges management
from .service_manager import ServiceManager
from .privileges_manager import PrivilegesManager

# History utilities
from .history_utils import HistoryUtils # New Import

from .tmux_utils import TmuxManager
from .path_utils import expand_path, to_posix_path, to_native_path

# Package manager inspection
from .package_manager import detect_package_managers, list_executable_paths, probe_tool_installations

# Debugging and logging utilities
from . import debug_utils

# File system utilities including link creation
from .fs_utils import create_link, LinkType, LinkResult

# Optionally, you could expose a unified namespace:
__all__ = [
    "SystemUtils",
    "ClipboardUtils",
    "NetworkUtils",
    "ProcessManager",
    "FileSystemManager",
    "ServiceManager",
    "PrivilegesManager",
    "HistoryUtils", # Added to __all__
    "TmuxManager",
    "debug_utils",
    "create_link",
    "LinkType",
    "LinkResult",
    "expand_path",
    "to_posix_path",
    "to_native_path",
    "detect_package_managers",
    "list_executable_paths",
    "probe_tool_installations",
]
