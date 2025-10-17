
# SyncMux

A centralized, cross-device tmux session manager with a modern TUI built on Textual and AsyncSSH.

## Features

- ✅ **Multi-host tmux management** - List and manage sessions across multiple remote hosts
- ✅ **Full session lifecycle** - Create, attach, and kill tmux sessions
- ✅ **Keyboard-driven navigation** - Intuitive j/k navigation and tab switching
- ✅ **Visual connection status** - Real-time indicators (connecting/connected/error)
- ✅ **Concurrent operations** - All hosts refresh simultaneously for faster updates
- ✅ **Platform-specific SSH** - Automatic SSH binary detection on Windows/Unix/Termux
- ✅ **Input validation** - Session name sanitization and validation
- ✅ **Asynchronous architecture** - UI never blocks on network I/O
- ✅ **Cross-platform** - Windows 11, WSL2, Termux, Linux

## Installation

### From Source
```bash
cd modules/syncmux
pip install -e .
```

### Dependencies
- Python 3.9+
- textual >= 0.58.0
- asyncssh >= 2.14.2
- pyyaml >= 6.0.1
- pydantic >= 2.7.1

## Configuration

Create a configuration file at `~/.config/syncmux/config.yml`:

```yaml
hosts:
  - alias: "local"
    hostname: "localhost"
    user: "your_username"
    auth_method: "agent"  # Uses SSH agent

  - alias: "server"
    hostname: "192.168.1.100"
    port: 22
    user: "admin"
    auth_method: "key"
    key_path: "~/.ssh/id_rsa"
```

See `config.yml.example` for more examples.

## Usage

```bash
python main.py
# or if installed
syncmux
```

### Keyboard Shortcuts

- `j`/`k` - Navigate down/up in active list
- `Tab` - Switch focus between host and session lists
- `Enter` - Select host / Attach to session
- `n` - Create new session on selected host
- `d` - Kill selected session (with confirmation)
- `r` - Refresh current host's sessions
- `Ctrl+R` - Refresh all hosts concurrently
- `q` - Quit application

## Architecture

Built with:
- **Textual** - Modern TUI framework with async support
- **AsyncSSH** - Native asyncio SSH client
- **Pydantic** - Data validation and models

Key principles:
- **Async-first** - All network operations are non-blocking
- **State-as-truth** - Remote tmux servers are the source of truth
- **Cross-platform** - Works on Termux, WSL2, and Windows 11

## Testing

The project includes comprehensive test coverage with 28+ tests:

```bash
cd modules/syncmux
pytest tests/ -v
```

Test categories:
- **Models**: Data validation with Pydantic
- **Config**: Configuration file loading and error handling
- **TmuxController**: Remote tmux command execution and parsing
- **ConnectionManager**: SSH connection pooling and lifecycle
- **Widgets**: UI component creation and status updates
- **Platform**: Cross-platform SSH command generation
- **App**: Integration tests for session creation and deletion

## Platform-Specific Notes

### Termux (Android)
- SSH binary is automatically located via PATH
- Works with both local and remote tmux servers
- Ensure `openssh` package is installed: `pkg install openssh`

### Windows 11
- Automatically detects SSH in System32 OpenSSH or Git installation
- Falls back to PATH if neither location found
- Requires Windows OpenSSH client or Git for Windows

### WSL2 / Linux
- Uses standard `ssh` from PATH
- Supports SSH agent forwarding for passwordless authentication

## Authentication Methods

SyncMux supports three authentication methods:

1. **SSH Agent** (`auth_method: "agent"`)
   - Most secure and convenient
   - Works with ssh-agent (Unix) or Pageant (Windows)
   - No credentials stored in config file

2. **Public Key** (`auth_method: "key"`)
   - Specify path to private key file
   - Example: `key_path: "~/.ssh/id_rsa"`

3. **Password** (`auth_method: "password"`)
   - Store password in config (not recommended)
   - Ensure config file has strict permissions: `chmod 600 ~/.config/syncmux/config.yml`

## Session Name Validation

Session names are automatically validated and sanitized:
- Must not be empty
- Maximum 100 characters
- Cannot contain colons (`:`) or dots (`.`)
- Only letters, numbers, hyphens, underscores, and spaces allowed
- Spaces are automatically converted to underscores

## Development Status

Core features complete with comprehensive test coverage. Future enhancements:
- Session filtering and search
- Custom key bindings
- Theming support
- Session grouping and tags
- Connection retry logic
- Logging and debug mode
