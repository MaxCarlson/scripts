<!-- version: 0.3.0 -->
# system_manager Module

A comprehensive cross-platform system management CLI that exposes and extends the functionality of the `cross_platform` module.

## Features

- **Nested CLI**: Organized by categories like `net`, `proc`, `sys`, `clipboard`, etc.
- **25+ Custom Commands**: Useful, non-intuitive utilities for daily development.
- **Cross-Platform**: Full support for Windows 11, WSL2, and Termux.
- **Rich Output**: Pretty tables and colorized terminal output.

## Installation

Standard repository setup (`setup.py` / `modules/setup.py`) installs `system_manager[tui]` automatically on Python 3.9+, providing both the CLI and the interactive Textual `proc-stats` / `sm proc watch` interface.

For standalone installations:

```bash
# Full installation with interactive Textual TUI (Python 3.9+)
pip install -e "modules/system_manager[tui]"

# Minimal / headless / Python 3.8+ installation (noninteractive Rich/JSON/CSV modes)
pip install -e modules/system_manager
```

## Usage

```bash
sm --help
sys-mgr net public-ip
sys-mgr proc top
```

## Process Debugging

Find wrapper processes by command line, path, or Windows CIM:

```bash
sm proc find -q gemini -C --cmdline
sm proc find -q split.ps1 -C --cmdline
sm proc find -q node -P "C:\Program Files\nodejs" --path
sm proc find -q gemini -M --cim
```

Inspect and control process trees:

```bash
sm proc tree -p 76028
sm proc parents -p 77828
sm proc children -p 76028 -R --recursive
sm proc stop-tree -p 76028 -n --dry-run
sm proc stop-tree -p 76028 -y --confirm
sm proc pause -q gemini -C --cmdline
sm proc resume -q gemini -C --cmdline
sm proc restart -p 34944 -n --dry-run
```

Sample resource usage:

```bash
sm proc stats -p 34944 -i 1 --interval 1 -S 60 --samples 60
sm proc stats-tree -p 76028 -i 1 --interval 1 -S 60 --samples 60
```

Search command descriptions:

```bash
sm help-search -q pause
sm help-search -q process -z --fuzzy
```

## Interactive Process Explorer (`proc-stats` / `sm proc watch`)

`proc-stats` (and `sm proc watch`) provides a read-only interactive Textual TUI and one-shot Rich/JSON/CSV reporter.

```bash
proc-stats
proc-stats -g '*python*' -g 'node*' -n 20 -i 1 -s cpu
proc-stats -p 12345 -R -a
proc-stats -1 -f json
sm proc watch -g '*codex*'
```

### Controls

- `Up`/`Down` or `j`/`k`: select process
- `Enter`: open Process Inspector (details, ancestry, history, sanitized copy)
- `Space`: pin/unpin process
- `/`: live filter (`Esc` clears)
- `s` / `S`: sort chooser / reverse sort
- `a`: toggle individual vs subtree aggregation
- `c`: column presets (`default`, `compact`, `cpu`, `memory`, `io`, `gpu`, `comprehensive`)
- `g`: grouping (`none`, `name`, `exe`, `parent`, `root`)
- `h`: History tab | `d`: descendants | `p`: parent | `f`: freeze | `+`/`-`/`r`: visible rows | `?`: help | `q`: quit

### Limitations

- Read-only: no key terminates, suspends, or restarts processes.
- Windows WDDM drivers may omit per-process GPU framebuffer memory; unavailable metrics display `-` rather than `0`.
- `nvidia-smi` fallback reports compute-apps only; per-process GPU utilization % is not fabricated from device-wide utilization.
- Process I/O counters reflect OS process I/O accounting, not confirmed physical disk throughput.
