# Scripts Repository - Claude Code Memory Bank

## Project Overview
Cross-platform Python/Shell scripting toolkit supporting Windows 11, Termux (Android), and WSL2 (Ubuntu).

**Primary directories**:
- `~/scripts/` - Main repository
- `~/dotfiles/` - Shell configurations
- `~/Repos/W11-Powershell/` - Windows-specific (when on Windows)

## Critical Rules

### 1. Python Argument Syntax (MANDATORY)
**ALL arguments MUST have short + long forms**:
```python
parser.add_argument("-v", "--verbose", ...)    # ✅ Correct
parser.add_argument("-f", "--force", ...)      # ✅ Correct
parser.add_argument("--verbose", ...)          # ❌ Missing short form
```

### 2. Test File Naming (STRICT)
```python
tests/module_name_test.py   # ✅ Correct - ends with _test.py
tests/test_module.py        # ❌ Wrong - old pytest style
```

### 3. File Output Policy (NON-NEGOTIABLE)
- ✅ Always output COMPLETE files
- ✅ File labels OUTSIDE code fences
- ✅ NO truncation or "rest of file" placeholders
- ✅ Preserve public interfaces without explicit authorization
- ✅ One copyable element per code block

### 4. Platform Compatibility
Handle differences explicitly for:
- **Windows 11**: PowerShell 7+, paths with backslashes
- **Termux**: Android filesystem restrictions, pkg manager, no hardlinks
- **WSL2**: Ubuntu, both Bash and Zsh

## Project Structure

```
scripts/
├── .claude/               # Claude Code configuration
│   ├── settings.json     # Project settings
│   ├── AGENTS.md         # Behavior specification
│   └── README.md         # Configuration docs
├── .venv/                # Python virtual environment
├── modules/              # Python modules
│   ├── setup_utils/      # Setup utilities (dependency resolver)
│   ├── cross_platform/   # Cross-platform utilities
│   ├── standard_ui/      # Terminal UI components
│   └── ...
├── pyscripts/            # Python scripts with CLI
├── pscripts/             # Python scripts (alternative)
├── shell-scripts/        # Shell scripts
├── scripts_setup/        # Setup utilities
├── setup.py             # Main setup script
└── bootstrap.sh         # Bootstrap Python environment
```

## Module Dependencies

**Core module order** (manual):
1. `standard_ui` - No dependencies
2. `cross_platform` - No dependencies
3. `python_setup` - Depends on `cross_platform`
4. `scripts_setup` - No dependencies

**Other modules**: Auto-resolved via `modules/setup_utils/dependency_resolver.py`

## Common Commands

### Setup
```bash
./bootstrap.sh -v              # Bootstrap Python environment (uv, pipx)
python setup.py -v             # Install all modules (verbose)
python setup.py -f             # Force reinstall
python setup.py -F             # Fail-fast mode
```

### Development
```bash
pytest tests/                  # Run all tests
pytest tests/module_test.py -v # Run specific test
python -m pip install -e .     # Install module editable
```

### Termux-Specific
```bash
pkg install uv                 # Install uv (faster than pip)
pkg install automake autoconf  # For native builds
export UV_LINK_MODE=copy       # Suppress hardlink warnings
```

## Known Issues & Solutions

### Termux
- **uv installation**: Use `pkg install uv` (precompiled)
- **Hardlink warnings**: Expected, harmless (Android filesystem)
- **Native builds**: May need `automake`, `autoconf` for some packages
- **patchelf failures**: Install `pkg install patchelf` or skip those modules

### Dependency Errors
- Run `python modules/setup_utils/dependency_resolver.py modules/` to check order
- Manually fix by installing dependencies first
- Auto-resolved in `modules/setup.py` if dependency_resolver available

## Code Standards

### Python
- PEP 8 compliant with type hints
- Use `logging` not `print`
- Use `pathlib` not `os.path`
- UTF-8 everywhere
- `-v/--verbose` and `-q/--quiet` flags
- `--dry-run/-n` for destructive operations
- Structured exceptions with actionable messages

### Shell
- Bash/Zsh: `set -euo pipefail`
- PowerShell: `try/catch/finally` with `$ErrorActionPreference = 'Stop'`
- Cross-platform path handling

### Testing
- pytest mandatory for Python
- Mock: filesystem, network, env, registry
- Cover: happy path, edge cases, errors

## Recent Fixes (2025-10-04)

1. ✅ Fixed SystemUtils missing methods (`is_windows()`, `is_linux()`)
2. ✅ Fixed uv installation on Termux (use `pkg install uv`)
3. ✅ Fixed venv creation (`--python` flag for Termux)
4. ✅ Added dependency resolver for auto-ordering
5. ✅ Skip requirements.txt when pyproject.toml exists
6. ✅ Reduced pip verbosity (uses `-q` by default)
7. ✅ Fixed hardlink warnings (set `UV_LINK_MODE=copy`)
8. ✅ Created comprehensive Claude Code configuration

## Configuration Files

See `.claude/` directory for:
- `settings.json` - Claude Code project settings
- `AGENTS.md` - Detailed behavior specifications
- `README.md` - Configuration documentation

## External References

Based on custom instructions from:
- `../projects/notes/custom_instructions/chatgpt-projects/python-scripting-v4.md`
- `../projects/notes/custom_instructions/chatgpt-projects/w11-pwshv3.md`
