# Tmux Manager

Advanced window management operations for tmux.

## Features

- Close windows by range or list (e.g., `4..10`, `1,7,8,11`)
- Move windows within the same session
- Swap windows within the same session
- Move windows between different sessions
- Swap windows between different sessions
- Support for negative indices (-1 for last, -2 for second-to-last, etc.)
- FZF integration for interactive selection
- Smart defaults (uses current window/session when not specified)

## Installation

The module is part of the scripts/modules collection. No additional installation needed.

## Usage

### As a Python module:
```bash
python -m tmux_manager <command> [options]
```

### Commands

#### `closew` - Close window(s)
```bash
python -m tmux_manager closew 5                    # Close window 5
python -m tmux_manager closew 4..10                # Close windows 4-10
python -m tmux_manager closew 1,7,8,11             # Close specific windows
python -m tmux_manager closew 4..-1                # Close from 4 to last
python -m tmux_manager closew 5 -t ai              # Close window 5 in session "ai"
```

#### `mvw` - Move window within same session
```bash
python -m tmux_manager mvw                         # Interactive fzf selection
python -m tmux_manager mvw -i 0                    # Move current window to index 0
python -m tmux_manager mvw -i -1                   # Move to last position
python -m tmux_manager mvw -w 3 -i 7               # Move window 3 to index 7
```

#### `sww` - Swap windows in same session
```bash
python -m tmux_manager sww                         # Interactive fzf selection
python -m tmux_manager sww -i 3                    # Swap current with window 3
python -m tmux_manager sww -w 1 -i 5               # Swap window 1 with 5
```

#### `mvws` - Move window to different session
```bash
python -m tmux_manager mvws                        # Interactive fzf
python -m tmux_manager mvws -s ai                  # Move to session "ai"
python -m tmux_manager mvws -s ai -i 0             # Move to session "ai" at index 0
python -m tmux_manager mvws -s ai -i -1            # Move to last position in "ai"
```

#### `swws` - Swap windows between sessions
```bash
python -m tmux_manager swws                        # Interactive fzf for both
python -m tmux_manager swws -s ai                  # Swap with fzf-selected window in "ai"
python -m tmux_manager swws -s ai -i 3             # Swap with window 3 in "ai"
```

## Requirements

- tmux
- fzf (for interactive selection)
- Python 3.6+

## ZSH Integration

Add wrapper functions to your `.zshrc` or tmux config:

```zsh
tmclosew() { python3 -m tmux_manager closew "$@"; }
tsmvw() { python3 -m tmux_manager mvw "$@"; }
tssww() { python3 -m tmux_manager sww "$@"; }
tsmvws() { python3 -m tmux_manager mvws "$@"; }
tsswws() { python3 -m tmux_manager swws "$@"; }
```
