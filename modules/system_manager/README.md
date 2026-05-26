<!-- version: 0.3.0 -->
# system_manager Module

A comprehensive cross-platform system management CLI that exposes and extends the functionality of the `cross_platform` module.

## Features

- **Nested CLI**: Organized by categories like `net`, `proc`, `sys`, `clipboard`, etc.
- **25+ Custom Commands**: Useful, non-intuitive utilities for daily development.
- **Cross-Platform**: Full support for Windows 11, WSL2, and Termux.
- **Rich Output**: Pretty tables and colorized terminal output.

## Installation

```bash
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
