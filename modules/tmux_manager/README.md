# Tmux Manager

Advanced tmux session and window management toolkit with an intuitive CLI.

## Installation

```bash
cd ~/scripts/modules
pip install -e ./tmux_manager/
```

This installs the `tmx` command globally.

## Features

- 🪟 **Window Management**: Move, swap, and close windows with advanced specifications
- 🎯 **Smart Targeting**: Use ranges (`4..10`), comma-separated lists (`1,7,8`), or negative indices (`-1`)
- 🎨 **Window Spawning**: Create multiple windows with multiple panes in one command
- 🔀 **Cross-Session Operations**: Move and swap windows between different sessions
- 🎪 **FZF Integration**: Interactive selection for sessions and windows
- ⚡ **Quick Session Jumping**: Jump to any session with optional fuzzy finding

## Commands

### Window Operations

#### `closew` - Close Window(s)

Close one or more windows using flexible specifications.

```bash
# Close single window
tmx closew 5

# Close range of windows
tmx closew 4..10

# Close specific windows
tmx closew 1,7,8,11

# Close from index to last window
tmx closew 4..-1

# Close in specific session
tmx closew 5 -t my_session
```

**Options:**
- `-t, --session SESSION`: Target session (default: current session)

---

#### `mvw` - Move Window (Same Session)

Move a window to a different index within the same session.

```bash
# Interactive selection
tmx mvw

# Move to specific index
tmx mvw -i 0

# Move to last position
tmx mvw -i -1

# Move specific window to index
tmx mvw -w 3 -i 7

# Move in different session
tmx mvw -i 5 -t my_session
```

**Options:**
- `-i, --index INDEX`: Target index (supports negative like -1 for last)
- `-w, --window INDEX`: Source window (default: current window)
- `-t, --session SESSION`: Session name (default: current session)

---

#### `sww` - Swap Windows (Same Session)

Swap two windows within the same session.

```bash
# Interactive selection
tmx sww

# Swap with specific window
tmx sww -i 3

# Swap two specific windows
tmx sww -w 1 -i 5
```

**Options:**
- `-i, --index INDEX`: Target window to swap with (supports negative)
- `-w, --window INDEX`: Source window (default: current window)
- `-t, --session SESSION`: Session name (default: current session)

---

#### `mvws` - Move Window to Session

Move a window to a different session.

```bash
# Interactive session selection
tmx mvws

# Move to specific session (appends to end)
tmx mvws -s ai

# Move to session at specific index
tmx mvws -s ai -i 0

# Move to last position in session
tmx mvws -s ai -i -1

# Move specific window from specific session
tmx mvws -s target --from source -w 5 -i 2
```

**Options:**
- `-s, --target-session SESSION`: Target session (default: fzf select)
- `-i, --index INDEX`: Target index in destination (default: append to end)
- `-w, --window INDEX`: Source window (default: current window)
- `--from SESSION`: Source session (default: current session)

---

#### `swws` - Swap Windows Between Sessions

Swap windows between two different sessions.

```bash
# Interactive selection
tmx swws

# Swap with window in specific session
tmx swws -s ai

# Swap with specific window in session
tmx swws -s ai -i 3
```

**Options:**
- `-s, --target-session SESSION`: Target session (default: fzf select)
- `-i, --index INDEX`: Target window index (default: fzf select)
- `-w, --window INDEX`: Source window (default: current window)
- `--from SESSION`: Source session (default: current session)

---

### Window Creation

#### `spawn` - Create New Windows

Spawn one or more windows, optionally with multiple panes.

```bash
# Create single window
tmx spawn

# Create 3 windows
tmx spawn -c 3

# Create window with 4 panes
tmx spawn -p 4

# Create 3 windows, each with 2 panes
tmx spawn -c 3 -p 2

# Create named windows
tmx spawn -c 3 -n "workspace"

# Create at specific index
tmx spawn -i 0

# Create in specific session
tmx spawn -c 2 -t my_session
```

**Options:**
- `-c, --count COUNT`: Number of windows to create (default: 1)
- `-p, --panes PANES`: Number of panes per window (default: 1)
- `-i, --index INDEX`: Index where to insert (default: after current window)
- `-t, --session SESSION`: Target session (default: current session)
- `-n, --name NAME`: Name for the window(s)

**Notes:**
- Panes are created with horizontal splits and evenly balanced
- When creating multiple windows with names, they're numbered (e.g., workspace-1, workspace-2)
- Default insertion point is after the current window

---

### Session Operations

#### `jump` - Jump to Session

Quickly switch to or attach to a session.

```bash
# Interactive session selection (fzf)
tmx jump

# Jump to specific session
tmx jump ai
```

**Behavior:**
- If inside tmux: Switches to the target session
- If outside tmux: Attaches to the target session
- Uses fzf for interactive selection when no session specified

---

## Window Specifications

The `closew` command supports flexible window specifications:

### Single Index
```bash
tmx closew 5
```

### Range (inclusive)
```bash
tmx closew 4..10     # Windows 4, 5, 6, 7, 8, 9, 10
tmx closew 4:10      # Same as above (alternative syntax)
```

### Comma-Separated
```bash
tmx closew 1,7,8,11  # Windows 1, 7, 8, and 11
```

### Negative Indices
```bash
tmx closew -1        # Last window
tmx closew -2        # Second to last
tmx closew 4..-1     # From window 4 to last window
tmx closew 1,-2,-1   # Window 1, second to last, and last
```

## Usage Examples

### Quick Workspace Setup

Create a development workspace with multiple windows:

```bash
# Create 4 windows, each with 2 panes
tmx spawn -c 4 -p 2 -n dev

# Result:
# - dev-1 (2 panes)
# - dev-2 (2 panes)
# - dev-3 (2 panes)
# - dev-4 (2 panes)
```

### Session Cleanup

Close all but the first few windows:

```bash
# Close windows 5 through the last
tmx closew 5..-1
```

### Window Reorganization

```bash
# Move current window to first position
tmx mvw -i 0

# Swap first and last windows
tmx sww -w 0 -i -1

# Move window to different session at the beginning
tmx mvws -s ai -i 0
```

### Multi-Pane Development

```bash
# Create window with 4 panes for monitoring
tmx spawn -p 4 -n monitoring

# Create 2 editor windows with 2 panes each
tmx spawn -c 2 -p 2 -n editor
```

## Requirements

- **tmux**: Terminal multiplexer (required)
- **fzf**: Fuzzy finder for interactive selection (recommended)
- **Python**: 3.7 or higher

## Testing

Comprehensive test suite with 53+ tests:

```bash
cd ~/scripts/modules/tmux_manager

# Run all tests
pytest

# Run with verbose output
pytest -v

# Run specific test file
pytest tests/test_window_manager.py

# Run with coverage
pytest --cov=tmux_manager --cov-report=html
```

## Architecture

```
tmux_manager/
├── __init__.py          # Module exports
├── __main__.py          # Entry point for `python -m tmux_manager`
├── window_manager.py    # Core TmuxWindowManager class
├── cli.py               # Command-line interface
├── pyproject.toml       # Package configuration
├── pytest.ini           # Test configuration
└── tests/
    ├── test_window_manager.py  # Core functionality tests
    ├── test_cli.py             # CLI interface tests
    └── conftest.py             # Shared test fixtures
```

## Development

The module is designed for:
- **Isolation**: No dependencies on other custom modules
- **Testability**: Comprehensive mocking for unit tests
- **Extensibility**: Easy to add new commands and operations
- **Cross-platform**: Works on Linux, macOS, and Windows (with tmux)

## Tips & Tricks

1. **Batch Operations**: Use ranges to operate on multiple windows at once
2. **Negative Indices**: Use `-1` to always target the last window
3. **FZF Selection**: Press Ctrl+C in fzf to cancel selection
4. **Window Names**: Use `-n` with `spawn` to create organized workspaces
5. **Session Jumping**: `tmx jump` without arguments for quick session switching

## Troubleshooting

**Command not found: tmx**
```bash
# Reinstall the module
cd ~/scripts/modules
pip install -e ./tmux_manager/
```

**FZF selection not working**
```bash
# Install fzf
pkg install fzf  # Termux
brew install fzf  # macOS
apt install fzf   # Debian/Ubuntu
```

**Permission errors**
```bash
# Ensure you have write access to the session
tmux list-windows -t <session>
```

## License

Part of the personal scripts collection. Use freely.

## Contributing

This is a personal utility module, but improvements are welcome:
1. Add tests for new features
2. Follow the existing code style
3. Update documentation
4. Ensure all tests pass

## Version

**1.0.0** - Full-featured tmux manager with window and session operations
