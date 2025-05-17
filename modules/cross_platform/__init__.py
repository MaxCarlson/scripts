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

# Debugging and logging utilities
from . import debug_utils

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
    "debug_utils",
]
