
# SyncMux

A centralized, cross-device tmux session manager with a modern TUI built on Textual and AsyncSSH.

## Features (MVP)

- ✅ List and manage tmux sessions across multiple remote hosts
- ✅ Create new tmux sessions on any configured host
- ✅ Kill tmux sessions with confirmation
- ✅ Attach to remote tmux sessions (terminal handoff via SSH)
- ✅ Asynchronous operations - UI never blocks on network I/O
- ✅ Cross-platform: Windows 11, WSL2, Termux

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

- `j`/`k` or `↓`/`↑` - Navigate lists
- `Enter` - Select host / Attach to session
- `n` - Create new session
- `d` - Kill session (with confirmation)
- `r` - Refresh current host
- `Ctrl+R` - Refresh all hosts
- `q` - Quit

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

```bash
pytest tests/ -v
```

## Development Status

This is an MVP (Minimum Viable Product) implementation. Future enhancements:
- Connection status indicators in host list
- Session filtering and search
- Multi-host session operations
- Configuration validation and error recovery
- More comprehensive test coverage
