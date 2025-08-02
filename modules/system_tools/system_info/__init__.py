"""
Detailed system information modules.

Provides OS-specific functions:
  - Windows: get_windows_info
  - Linux:   get_linux_info
  - macOS:   get_mac_info
  - Termux:  get_termux_info
"""

from .windows_info import get_windows_info
from .linux_info import get_linux_info
from .mac_info import get_mac_info
from .termux_info import get_termux_info
