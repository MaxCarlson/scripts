# Scripts Repository

Cross-platform Python/Shell scripting toolkit supporting **Windows 11**, **Termux (Android)**, and **WSL2 (Ubuntu)**.

## Quick Start

### Prerequisites

- Python 3.12+ (see `.python-version`)
- [uv](https://github.com/astral-sh/uv) (recommended) or pip

### Installation

**Linux/macOS/WSL2/Termux:**
```bash
./bootstrap.sh -v
```

**Windows (PowerShell):**
```powershell
.\bootstrap.ps1 -Verbose
```

**Manual setup:**
```bash
python setup.py -v       # Install all modules (verbose)
python setup.py -f       # Force reinstall
python setup.py -F       # Fail-fast mode
```

## Project Structure

```
scripts/
├── .claude/              # Claude Code configuration
├── .venv/                # Python virtual environment (auto-created)
├── agents/               # AI agent configurations
├── bin/                  # Executable wrappers
├── modules/              # Python packages (installable)
│   ├── standard_ui/      # Terminal UI components
│   ├── cross_platform/   # Cross-platform utilities
│   ├── python_setup/     # Setup utilities
│   ├── clipboard_utils/  # Clipboard operations
│   ├── file_utils/       # File manipulation tools
│   ├── tmux_manager/     # Tmux session management
│   ├── ytaedl/           # YouTube/audio downloader
│   ├── ...               # 40+ modules
│   └── setup.py          # Module installer
├── pyscripts/            # Standalone Python scripts
├── pscripts/             # Additional Python scripts
├── pwsh/                 # PowerShell scripts
├── shell-scripts/        # Bash/Zsh scripts
├── scripts_setup/        # Setup utilities
├── knowledge_manager/    # Knowledge base management
├── bootstrap.sh          # Unix bootstrap script
├── bootstrap.ps1         # Windows bootstrap script
└── setup.py              # Main setup orchestrator
```

## Key Modules

| Module | Description |
|--------|-------------|
| `standard_ui` | Terminal UI components (menus, progress bars, prompts) |
| `cross_platform` | OS detection, path handling, platform abstractions |
| `clipboard_utils` | Cross-platform clipboard operations |
| `file_utils` | File and directory manipulation utilities |
| `tmux_manager` | Tmux session and window management |
| `parallel_runner` | Concurrent task execution |
| `ytaedl` | YouTube and audio download tools |
| `sshmanager` | SSH connection management |
| `gitpulse` | Git repository monitoring |
| `termdash` | Terminal dashboard framework |

## Development

### Running Tests

```bash
pytest tests/                    # Run all tests
pytest tests/module_test.py -v   # Run specific test (verbose)
```

### Installing a Module in Development Mode

```bash
cd modules/module_name
pip install -e .
```

### Module Dependencies

Core modules are installed in order:
1. `standard_ui` - No dependencies
2. `cross_platform` - No dependencies
3. `python_setup` - Depends on `cross_platform`
4. `scripts_setup` - No dependencies

Other modules are auto-resolved via `modules/setup_utils/dependency_resolver.py`.

## Platform Notes

### Windows 11
- PowerShell 7+ recommended
- Uses backslash paths internally
- Run scripts from PowerShell or Git Bash

### Termux (Android)
```bash
pkg install uv python           # Install dependencies
export UV_LINK_MODE=copy        # Suppress hardlink warnings
./bootstrap.sh
```

**Common issues:**
- Use `pkg install uv` for precompiled uv
- Hardlink warnings are expected (Android filesystem limitation)
- Some native builds may need `pkg install automake autoconf patchelf`

### WSL2 (Ubuntu)
- Both Bash and Zsh supported
- Standard Linux installation applies

## Configuration

### Environment Variables

| Variable | Description |
|----------|-------------|
| `UV_LINK_MODE=copy` | Suppress uv hardlink warnings (Termux) |
| `SKIP_VENV_BOOTSTRAP=1` | Skip automatic venv creation |

### Claude Code Integration

See `.claude/` directory for AI assistant configuration:
- `settings.json` - Project settings
- `AGENTS.md` - Agent behavior specifications

## Contributing

### Code Standards

**Python:**
- PEP 8 compliant with type hints
- Use `logging` instead of `print`
- Use `pathlib` instead of `os.path`
- Arguments must have short + long forms: `-v/--verbose`
- Include `--dry-run/-n` for destructive operations

**Shell:**
- Bash/Zsh: `set -euo pipefail`
- PowerShell: `$ErrorActionPreference = 'Stop'`

**Tests:**
- File naming: `module_name_test.py` (not `test_module.py`)
- Use pytest
- Mock filesystem, network, and environment

## License

Private repository - All rights reserved.
