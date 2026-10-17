# Scripts Repository

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
└── AGENTS.md             # This file
```

## Key Guidelines

### Python Code Standards

**Argument Syntax (MANDATORY)**
- ALL CLI arguments MUST use `-a/--abbreviated-argument-name` format
- Every argument requires both short and long forms
- Examples: `-v/--verbose`, `-f/--force`, `-n/--dry-run`, `-R/--scripts-dir`

**Code Style**
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

### Testing Requirements

**Pytest Standards (MANDATORY)**
- Test files MUST be named `tests/<module_name>_test.py`
- Never use `test_<module>.py` format
- Coverage required: happy path, edge cases, error conditions
- Mock external dependencies (filesystem, network, env vars, registry)
- Run tests before committing: `pytest tests/`

### Module Installation

**Dependency Ordering**
- Core modules have explicit ordering in `setup.py`:
  1. `standard_ui` (no dependencies)
  2. `cross_platform` (required by python_setup)
  3. `python_setup` (depends on cross_platform)
  4. `scripts_setup` (final setup utilities)
- Other modules use automatic dependency resolution via `setup_utils/dependency_resolver.py`

**Setup Script Usage**
```bash
python setup.py                    # Standard installation
python setup.py -v                 # Verbose output
python setup.py -f                 # Force reinstall
python setup.py -F                 # Fail-fast on errors
python setup.py -p                 # Production (non-editable) install
```

**Directory Defaults**
- Scripts: `$SCRIPTS` env var or `~/scripts`
- Dotfiles: `$DOTFILES` env var or `~/dotfiles`
- Bin: `$SCRIPTS/bin` or `~/scripts/bin`

### Cross-Platform Support

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

### Development Workflow

**Before Code Changes**
- Read relevant module code to understand structure
- Check tests to understand expected behavior
- Review `pyproject.toml` for dependencies

**After Code Changes**
- Run formatters: `black --line-length 120 <file>`
- Run linters: `ruff check <file>`
- Run tests: `pytest tests/<module>_test.py -v`
- Verify cross-platform compatibility if applicable

**Module Installation Flow**
1. Create/activate venv (`.venv/`)
2. Install core modules in order (standard_ui → cross_platform → python_setup → scripts_setup)
3. Auto-resolve dependencies for remaining modules
4. Skip requirements.txt if pyproject.toml exists
5. Install modules in editable mode by default (`-e` flag)

### Version Management

**Semantic Versioning (SemVer) - MANDATORY**

All Python modules MUST follow Semantic Versioning 2.0.0 (MAJOR.MINOR.PATCH):

- **MAJOR version (X.0.0)**: Increment for backwards-incompatible API changes
  - Breaking changes to public interfaces
  - Removing or renaming functions, classes, CLI flags
  - Changing function signatures or return types
  - Examples: Python 2→3, TensorFlow 1→2

- **MINOR version (0.X.0)**: Increment for backwards-compatible new features
  - Adding new functions, classes, or CLI flags
  - Adding optional parameters with defaults
  - New functionality that doesn't break existing code

- **PATCH version (0.0.X)**: Increment for backwards-compatible bug fixes
  - Bug fixes without API changes
  - Performance improvements
  - Documentation updates
  - Internal refactoring

**Version Bumping Rules**:
- When modifying a module, ALWAYS bump the version in `pyproject.toml` or `setup.py`
- Choose the appropriate level based on the change type
- Reset lower version numbers when bumping higher ones (e.g., 1.2.3 → 2.0.0, not 2.2.3)
- Pre-1.0.0 versions (0.y.z) indicate initial development; breaking changes allowed

### Configuration Files

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

### Common Issues and Fixes

**"Module not found" during installation**
- Cause: Modules installed out of dependency order
- Fix: Use `dependency_resolver.py` or manual ordering in `setup.py`

**"No attribute 'is_windows'" error**
- Cause: Outdated `SystemUtils` class or fallback implementation
- Fix: Update `cross_platform/system_utils.py` with missing methods

**uv installation fails on Termux**
- Cause: Native compilation (Rust crates) not supported
- Fix: Use `pkg install uv` instead of pip/cargo

**Hardlink warnings on Termux**
- Cause: Android filesystem doesn't support hardlinks
- Fix: Set `UV_LINK_MODE=copy` environment variable (non-critical)

**patchelf/autoreconf build failures**
- Cause: Missing build tools on Termux
- Fix: `pkg install automake autoconf` or skip affected modules

### Security Guidelines

- Validate and sanitize all user inputs
- Use secure temp file creation
- Apply least privilege principles
- Never log secrets, API keys, or credentials
- Set timeouts on all external operations
- Use context managers for resource cleanup

## Commands Reference

**Setup and Installation**
```bash
# Bootstrap Python environment (Termux/fresh systems)
bash modules/python_setup/scripts/bootstrap.sh -v

# Install all modules
python setup.py -v

# Force reinstall all modules
python setup.py -f -v

# Production install (non-editable)
python setup.py -p

# Custom directories
python setup.py -R /custom/scripts -D /custom/dotfiles -B /custom/bin
```

**Testing**
```bash
# Run all tests
pytest tests/ -v

# Run specific module tests
pytest tests/cross_platform_test.py -v

# Run with coverage
pytest tests/ --cov=modules --cov-report=html
```

**Dependency Analysis**
```bash
# Show module installation order
python modules/setup_utils/dependency_resolver.py modules/
```

## Notes for AI Agents

- Always preserve public interfaces (functions, classes, CLI flags) unless explicitly authorized
- Output complete files, not diffs or snippets
- When in doubt about requirements, ask or state assumptions clearly
- Test naming violations will cause pytest discovery to fail
- Argument syntax violations break CLI consistency
- Cross-platform code must handle all three target platforms
- **ALWAYS bump module version** when modifying code (follow SemVer rules above)
