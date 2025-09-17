# clipboard_utils Module

The `clipboard_utils` module provides a set of functions for interacting with the system clipboard in a cross-platform manner. It serves as an abstraction layer, primarily forwarding clipboard operations to a more centralized `cross_platform.clipboard_utils` implementation. The `old.clipboard_utils.py` file within this module contains the direct platform-specific logic, which is useful for understanding the underlying mechanisms or as a fallback.

## Purpose

To offer a consistent Python interface for clipboard operations across various operating systems and environments, including:
*   Termux
*   Windows Subsystem for Linux (WSL)
*   Standard Linux distributions (e.g., Ubuntu with `xclip`)
*   Windows (via PowerShell)

## Key Files

*   **`__init__.py`**: The package initializer, which exposes `get_clipboard` and `set_clipboard` functions from `clipboard_utils.py` for direct import.
*   **`clipboard_utils.py`**: This is the main entry point for the module's clipboard functionality. It acts as a thin wrapper, importing and utilizing the `ClipboardUtils` class from the `cross_platform` package. This design promotes modularity and allows for a single, updated source of truth for clipboard logic across the project.
*   **`old.clipboard_utils.py`**: Contains the original, direct implementations of `get_clipboard` and `set_clipboard`. These functions directly invoke external command-line tools (`termux-clipboard-get/set`, `win32yank`, `xclip`, `powershell`) based on the detected operating system. This file serves as a reference for platform-specific clipboard handling.

## Functionality

*   **`get_clipboard() -> str`**: Retrieves the current text content from the system clipboard.
*   **`set_clipboard(text: str) -> None`**: Sets the provided `text` string as the new content of the system clipboard.

## Usage

To use the clipboard utilities, simply import the functions from the module:

```python
from modules.clipboard_utils import get_clipboard, set_clipboard

# Get clipboard content
content = get_clipboard()
print(f"Clipboard content: {content}")

# Set clipboard content
set_clipboard("Hello from Python!")
print("Clipboard content set.")
```

**Note**: The `clipboard_utils.py` file relies on the `cross_platform` package being correctly installed and accessible. If you encounter `ImportError` related to `cross_platform`, ensure that package is properly set up in your environment.