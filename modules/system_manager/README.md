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
