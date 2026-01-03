# cross_platform Module

The `cross_platform` module is a comprehensive collection of Python utilities designed to abstract and standardize interactions with the underlying operating system. Its primary goal is to provide a unified API for common system-level tasks, allowing higher-level scripts to function consistently across different environments like Windows, Linux, macOS, Termux, and WSL2, without needing to implement OS-specific logic for each operation.

## Purpose

To offer a robust and consistent set of tools for:
*   Managing clipboard content.
*   Handling debugging and logging.
*   Performing file system operations.
*   Accessing and parsing shell history.
*   Executing network-related tasks.
*   Checking and requiring administrative privileges.
*   Managing system processes and services.
*   Controlling `tmux` sessions and capturing pane content.

## Key Files and Classes

*   **`__init__.py`**: The package initializer, which imports and exposes the main utility classes and the `debug_utils` module, making them directly accessible when `cross_platform` is imported.

*   **`system_utils.py` (Class: `SystemUtils`)**: This is the foundational base class for the module. It provides core functionalities such as detecting the operating system (Windows, Linux, macOS, Termux, WSL2), executing shell commands, and sourcing files. Most other utility classes in this module inherit from `SystemUtils`.

*   **`clipboard_utils.py` (Class: `ClipboardUtils`)**: Offers robust cross-platform capabilities for getting and setting clipboard content. It employs a multi-tiered approach, prioritizing modern methods like OSC 52 for local terminal clipboard updates, then `tmux` buffer integration, and finally falling back to various platform-native tools (`pbcopy`, `xclip`, `xsel`, `termux-clipboard-set`, PowerShell, `clip.exe`).

*   **`debug_utils.py` (Module: `debug_utils`)**: Provides a flexible and configurable framework for logging and debugging. It supports different verbosity levels for console and file output, includes features for log rotation, and ensures proper cleanup of old log files.

*   **`file_system_manager.py` (Class: `FileSystemManager`)**: Extends `SystemUtils` to provide common file system operations, including creating directories, deleting directories, and listing files within a specified path.

*   **`fs_utils.py`**: Offers more granular, cross-platform filesystem utilities. This includes safe methods for formatting relative paths, performing exact (case-insensitive) file extension matching, and walking directories with options for excluding specific directories and limiting recursion depth.

*   **`history_utils.py` (Class: `HistoryUtils`)**: Designed to access and parse shell history from various environments (PowerShell, Bash, Zsh) to extract recently used commands and file paths.

*   **`network_utils.py` (Class: `NetworkUtils`)**: Provides cross-platform functionalities for network management, such as resetting network settings using OS-specific commands.

*   **`privileges_manager.py` (Class: `PrivilegesManager`)**: Contains methods to check for and, if necessary, enforce administrative or root privileges for script execution, ensuring that operations requiring elevated permissions can proceed safely.

*   **`process_manager.py` (Class: `ProcessManager`)**: Manages system processes, offering methods to list currently running processes and to terminate specific processes by name.

*   **`service_manager.py` (Class: `ServiceManager`)**: Provides cross-platform capabilities for managing system services, including querying their status, starting them, and stopping them.

*   **`tmux_utils.py` (Class: `TmuxManager`)**: Specializes in `tmux` session management. It allows listing, attaching to, creating, switching between, renaming, and detaching `tmux` sessions. It also includes functionality to fuzzy-find sessions (requiring `fzf`) and capture pane content. Requires `tmux` to be installed.

## Overall Functionality

The `cross_platform` module aims to create a robust and reliable layer for Python scripts to interact with the operating system's core functionalities. By encapsulating OS-specific logic, it significantly reduces code duplication and improves the maintainability and portability of scripts that need to perform system-level tasks.

## Dependencies

This module relies on standard Python libraries (`platform`, `subprocess`, `os`, `sys`, `shutil`, `pathlib`). For its full functionality, it may also depend on various external command-line tools and utilities, depending on the operating system and the specific feature being used. These include, but are not limited to:

*   `tmux` (for `TmuxManager`)
*   `fzf` (for fuzzy-finding in `TmuxManager`)
*   `xclip` or `xsel` (for Linux clipboard on X11)
*   `wl-copy` or `wl-paste` (for Linux clipboard on Wayland)
*   `pbcopy` or `pbpaste` (for macOS clipboard)
*   `termux-clipboard-set` or `termux-clipboard-get` (for Termux clipboard)
*   PowerShell or `clip.exe` (for Windows clipboard)
*   `sudo` (for privilege escalation on Unix-like systems)
*   `git` (for `debug_utils` to determine log file prefixes based on repository name)

Ensure that the necessary external tools are installed and available in your system's PATH for the respective functionalities to work correctly.
## Related Modules

The `cross_platform` module serves as a foundation for other specialized modules in the scripts repository:

### networks Module

The [`networks`](../networks/README.md) module builds on `cross_platform` to provide advanced networking utilities with automatic platform detection and configuration:

- **WSL2 Port Forwarding**: Automatically configures Windows → WSL2 port forwarding
- **Firewall Management**: Manages firewall rules on Windows, Linux (ufw/firewalld)
- **LAN Accessibility**: Makes applications accessible on local networks
- **Network Information**: Cross-platform IP detection and network details

**Example using cross_platform for OS detection:**
```python
from networks import ensure_port_accessible, get_lan_ip

# Automatically detects WSL2/Windows/Linux and configures accordingly
success, msg = ensure_port_accessible(3000, name='webapp')

# Get LAN IP (uses cross_platform's OS detection)
ip = get_lan_ip()
print(f"Access at: http://{ip}:3000")
```

The `networks` module uses `cross_platform.SystemUtils` for:
- Detecting WSL2 environment (`is_wsl2()`)
- Detecting Windows (`is_windows()`)
- Detecting Linux (`is_linux()`)
- Detecting Android/Termux (`is_android()`)

This allows the networks module to route to the appropriate platform-specific implementation without reimplementing OS detection logic.

### Other Modules

Other modules in the scripts repository that build on `cross_platform`:

- **standard_ui**: Terminal UI components using cross-platform clipboard and system utilities
- **python_setup**: Python environment setup using cross-platform process and service management
- **scripts_setup**: Setup utilities leveraging cross-platform file system operations

## Installation

```bash
cd ~/scripts
pip install -e modules/cross_platform/
```

## Testing

The module includes comprehensive tests covering all platforms:

```bash
cd ~/scripts/modules/cross_platform
pytest tests/ -v
```

**Test coverage:** 98 tests across all utility classes and platforms.

## See Also

- [networks module](../networks/README.md) - Network utilities with WSL2 support
- [standard_ui module](../standard_ui/README.md) - Terminal UI components
