# Scripts Repository

Personal automation monorepo: 50+ Python modules for cross-platform development.

> **AI assistants**: read [`MODULE_STANDARDS.md`](MODULE_STANDARDS.md) for
> versioning semantics, CLI flag conventions, subcommand guidelines, testing
> rules, and cross-platform requirements.  Those guidelines override any
> defaults you would otherwise apply.

## Architecture

```
scripts/
├── modules/              # Python modules (each has pyproject.toml)
│   ├── standard_ui/      # CLI UI components (no deps)
│   ├── cross_platform/   # OS detection, SystemUtils
│   ├── python_setup/     # Python environment bootstrap
│   ├── scripts_setup/    # Scripts installation utilities
│   ├── setup_utils/      # Module installer + dependency_resolver.py
│   └── <50+ more>/       # Various utility modules
├── pscripts/             # PowerShell scripts
├── bin/                  # Symlinked executables
└── setup.py              # Main module installer (handles dependency ordering)
```

## Commands

| Command | Description |
|---------|-------------|
| `python setup.py -v` | Install all modules (verbose) |
| `python setup.py -f -v` | Force reinstall all modules |
| `python setup.py -p` | Production install (non-editable) |
| `python setup.py -R DIR -D DIR -B DIR` | Custom directories |
| `bash modules/python_setup/scripts/bootstrap.sh -v` | Bootstrap Python env (Termux/fresh) |
| `pytest tests/ -v` | Run all tests |
| `pytest tests/<module>_test.py -v` | Run specific module tests |
| `pytest tests/ --cov=modules --cov-report=html` | Coverage report |
| `python modules/setup_utils/dependency_resolver.py modules/` | Show install order |
| `black --line-length 120 <file>` | Format |
| `ruff check <file>` | Lint |

## Module Dependency Ordering

Core modules MUST install in this order:
1. `standard_ui` (no dependencies)
2. `cross_platform` (required by python_setup)
3. `python_setup` (depends on cross_platform)
4. `scripts_setup` (final setup utilities)

Other modules: auto-resolved via `setup_utils/dependency_resolver.py`.
Default: editable install (`-e`). Skip `requirements.txt` when `pyproject.toml` exists.

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `SCRIPTS` | Scripts directory (default: `~/scripts`) |
| `DOTFILES` | Dotfiles directory (default: `~/dotfiles`) |
| `UV_LINK_MODE=copy` | Required for Termux venv creation |
| `PYTHONPATH` | Extended by bootstrap.sh for module imports |

## Gotchas

- **"Module not found" during install**: modules installed out of dependency order. Use `dependency_resolver.py` or manual ordering
- **"No attribute 'is_windows'"**: outdated `SystemUtils` class. Update `cross_platform/system_utils.py`
- **uv fails on Termux**: use `pkg install uv` (not pip/cargo, native compilation unsupported)
- **Hardlink warnings on Termux**: set `UV_LINK_MODE=copy` (Android doesn't support hardlinks)
- **patchelf/autoreconf failures**: `pkg install automake autoconf` or skip affected modules

## Key Files

- `setup.py` - Main installer with dependency ordering logic
- `modules/setup_utils/dependency_resolver.py` - Automatic dependency resolution
- `modules/python_setup/scripts/bootstrap.sh` - Termux/fresh system bootstrap
- `modules/cross_platform/system_utils.py` - SystemUtils class for OS detection
