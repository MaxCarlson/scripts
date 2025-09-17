# System Tools - Cross-Platform System Utilities

`system_tools` is a comprehensive Python module designed to provide a unified, cross-platform interface for various operating system interactions. It encapsulates common system-level functionalities, making it easier to write scripts that behave consistently across Windows, Linux, macOS, and Termux environments.

## Features

*   **Cross-Platform Compatibility**: Automatically adapts to the underlying operating system (Windows, Linux, macOS, Termux).
*   **Core Utilities**: Includes fundamental helpers for OS detection, command execution, and debug logging.
*   **Clipboard Management**: Functions to get and set clipboard content across different OSes, including OSC 52 support for SSH sessions.
*   **File System Management**: Utilities for creating, deleting, and listing directories.
*   **Network Utilities**: Basic network operations, such as resetting network adapters.
*   **Process Management**: Capabilities to list and terminate running processes.
*   **Service Management**: Functions to query, start, and stop system services.
*   **Privilege Management**: Tools to check for and require administrative/root privileges.
*   **Detailed System Information**: Gathers and displays extensive hardware and software information, with OS-specific implementations for Windows, Linux, macOS, and Termux.
*   **Command-Line Interface (CLI)**: A dedicated CLI (`system_tools/cli.py`) for querying system information with various filtering options.
*   **Enhanced Output**: Integrates with `rich` for visually appealing and structured console output.

## Module Structure

The `system_tools` module is organized into several sub-packages, each focusing on a specific area of system interaction:

*   **`core/`**: Contains fundamental utilities like `SystemUtils` (OS detection, command execution), `debug_utils` (flexible logging and debugging), and `clipboard_utils`.
*   **`file_system/`**: Provides `FileSystemManager` for directory operations.
*   **`network/`**: Offers `NetworkUtils` for network-related tasks.
*   **`privileges/`**: Includes `PrivilegesManager` for privilege checks.
*   **`process/`**: Contains `ProcessManager` for process control and `ServiceManager` for service management.
*   **`system_info/`**: Houses OS-specific modules (`windows_info.py`, `linux_info.py`, `mac_info.py`, `termux_info.py`) for gathering detailed system data.

## Installation

(Assuming Python 3 is installed)

```bash
# Navigate to the module directory
cd /data/data/com.termux/files/home/scripts/modules/system_tools

# Install required libraries (if any, check requirements.txt)
# pip install rich # if not already installed
```

## Usage

### Command-Line Interface (CLI)

The primary way to interact with the system information gathering capabilities is through the CLI:

```bash
python -m system_tools.cli --help
```

Example: Get CPU and Memory information

```bash
python -m system_tools.cli --cpu --memory
```

### Programmatic Usage

You can import and use individual classes and functions from the submodules:

```python
from system_tools.core.system_utils import SystemUtils
from system_tools.file_system.file_system_manager import FileSystemManager
from system_tools.network.network_utils import NetworkUtils
from system_tools.privileges.privileges_manager import PrivilegesManager
from system_tools.process.process_manager import ProcessManager
from system_tools.process.service_manager import ServiceManager
from system_tools.core.clipboard_utils import get_clipboard, set_clipboard

# Example: Get OS name
sys_utils = SystemUtils()
print(f"Operating System: {sys_utils.os_name}")

# Example: Create a directory
fs_manager = FileSystemManager()
fs_manager.create_directory("/tmp/my_new_dir")

# Example: Get clipboard content
clipboard_content = get_clipboard()
print(f"Clipboard: {clipboard_content}")

# Example: Check for admin privileges
priv_manager = PrivilegesManager()
try:
    priv_manager.require_admin()
    print("Running with admin privileges.")
except PermissionError as e:
    print(f"Error: {e}")
```
