# Scripts Repository - Gemini Context

Personal automation scripts and utilities for cross-platform development (Windows 11, Termux, WSL2).

## Project Structure

```
scripts/
├── modules/              # Python modules installed via setup.py
│   ├── cross_platform/   # OS detection and platform utilities
│   ├── python_setup/     # Python environment bootstrap
│   ├── scripts_setup/    # Scripts installation utilities
│   ├── setup_utils/      # Module installation helpers
│   ├── standard_ui/      # CLI UI components
│   └── */                # Additional utility modules
├── pscripts/             # PowerShell scripts
├── bin/                  # Symlinked executables
├── setup.py              # Main module installer
├── AGENTS.md             # Instructions for OpenAI Codex
└── GEMINI.md             # This file (instructions for Gemini CLI)
```

## Core Development Rules

### Python Argument Syntax (MANDATORY)

**ALL CLI arguments MUST use `-a/--abbreviated-argument-name` format**

- Every argument requires both short and long forms
- Examples: `-v/--verbose`, `-f/--force`, `-n/--dry-run`, `-R/--scripts-dir`
- Never use only long form (`--verbose` without `-v`)

### Version Management (MANDATORY)

**Always bump version when modifying Python modules using Semantic Versioning (SemVer 2.0.0)**

Format: `MAJOR.MINOR.PATCH` (e.g., `1.2.3`)

- **MAJOR (X.0.0)**: Breaking changes - backwards-incompatible API changes
  - Removing/renaming functions, classes, CLI flags
  - Changing function signatures or return types
  - Examples: Python 2→3, TensorFlow 1→2

- **MINOR (0.X.0)**: New features - backwards-compatible additions
  - Adding new functions, classes, CLI flags
  - Adding optional parameters with defaults
  - New functionality without breaking existing code

- **PATCH (0.0.X)**: Bug fixes - backwards-compatible fixes only
  - Bug fixes without API changes
  - Performance improvements
  - Documentation updates
  - Internal refactoring

**Rules**:
- ALWAYS bump version in `pyproject.toml` or `setup.py` when modifying a module
- Reset lower numbers when bumping higher (1.2.3 → 2.0.0, NOT 2.2.3)
- Pre-1.0.0 (0.y.z) = initial development, breaking changes allowed

### Testing Requirements (MANDATORY)

**Pytest Standards**
- Test files MUST be named `tests/<module_name>_test.py`
- Never use `test_<module>.py` format (old pytest style)
- Coverage required: happy path, edge cases, error conditions
- Mock external dependencies (filesystem, network, env vars, registry)
- Run tests before committing: `pytest tests/`

### Code Style

**Python Best Practices**
- PEP 8 compliant with type hints and docstrings
- Use `logging` module, NOT `print()` for library code
- Use `pathlib.Path`, NOT `os.path`
- UTF-8 encoding for all file I/O
- Include safety toggles: `--dry-run/-n`, `--confirm/-y` for destructive operations

**Error Handling**
- Structured exceptions with meaningful messages
- Map exceptions to appropriate CLI exit codes
- Never log secrets or sensitive data
- Timeouts on all network operations

### Output Format

**File Output Policy**
- Always output COMPLETE files (no truncation or "rest of file" placeholders)
- File labels OUTSIDE code fences
- Preserve public interfaces without explicit authorization
- One file per code block

## Cross-Platform Support

**Target Platforms**
- Windows 11 (PowerShell 7+)
- Termux (Android with Zsh and Python)
- WSL2 (Ubuntu with Bash/Zsh)

**Platform-Specific Handling**
- Use `SystemUtils` class from `cross_platform` module for OS detection
- Available methods: `is_windows()`, `is_linux()`, `is_termux()`, `is_wsl()`, `is_darwin()`
- Handle path separators correctly via `pathlib`
- Document platform-specific behavior in docstrings

**Termux Specifics**
- uv installed via `pkg install uv` (NOT pip)
- Virtual environments require `UV_LINK_MODE=copy` (no hardlink support)
- Native compilation often fails; prefer pre-built packages via `pkg`
- Bootstrap script: `modules/python_setup/scripts/bootstrap.sh`

## Module Installation

### Dependency Ordering
- Core modules have explicit ordering in `setup.py`:
  1. `standard_ui` (no dependencies)
  2. `cross_platform` (required by python_setup)
  3. `python_setup` (depends on cross_platform)
  4. `scripts_setup` (final setup utilities)
- Other modules use automatic dependency resolution via `setup_utils/dependency_resolver.py`

### Setup Commands
```bash
python setup.py                    # Standard installation
python setup.py -v                 # Verbose output
python setup.py -f                 # Force reinstall
python setup.py -F                 # Fail-fast on errors
python setup.py -p                 # Production (non-editable) install
```

### Directory Defaults
- Scripts: `$SCRIPTS` env var or `~/scripts`
- Dotfiles: `$DOTFILES` env var or `~/dotfiles`
- Bin: `$SCRIPTS/bin` or `~/scripts/bin`

## Configuration Files

**Python Modules**
- Prefer `pyproject.toml` over `setup.py` for new modules
- Skip `requirements.txt` when `pyproject.toml` declares dependencies
- Include metadata: name, version, dependencies, entry points
- Version field MUST follow SemVer format: `version = "X.Y.Z"`

**Environment Variables**
- `SCRIPTS`: Scripts directory path
- `DOTFILES`: Dotfiles directory path
- `UV_LINK_MODE=copy`: Required for Termux venv creation
- `PYTHONPATH`: Extended by bootstrap.sh for module imports

## Common Issues

### "Module not found" during installation
- Cause: Modules installed out of dependency order
- Fix: Use `dependency_resolver.py` or manual ordering in `setup.py`

### "No attribute 'is_windows'" error
- Cause: Outdated `SystemUtils` class or fallback implementation
- Fix: Update `cross_platform/system_utils.py` with missing methods

### uv installation fails on Termux
- Cause: Native compilation (Rust crates) not supported
- Fix: Use `pkg install uv` instead of pip/cargo

### Hardlink warnings on Termux
- Cause: Android filesystem doesn't support hardlinks
- Fix: Set `UV_LINK_MODE=copy` environment variable (non-critical)

### patchelf/autoreconf build failures
- Cause: Missing build tools on Termux
- Fix: `pkg install automake autoconf` or skip affected modules

## Security Guidelines

- Validate and sanitize all user inputs
- Use secure temp file creation
- Apply least privilege principles
- Never log secrets, API keys, or credentials
- Set timeouts on all external operations
- Use context managers for resource cleanup

## Key Reminders for Gemini

1. **Always bump version** when modifying modules (follow SemVer rules)
2. **All Python arguments** must use `-a/--abbreviated` format
3. **Test files** must be named `tests/*_test.py`
4. **Output complete files** - no truncation or snippets
5. **Preserve public interfaces** unless explicitly authorized
6. **Handle all three platforms** (Windows 11, Termux, WSL2)
