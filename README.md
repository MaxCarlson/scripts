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

**Install only what is missing:**
```bash
./bootstrap_latest.sh --dry-run  # preview
./bootstrap_latest.sh            # install missing packages and launchers
```
```powershell
.\bootstrap_latest.ps1 -DryRun  # preview
.\bootstrap_latest.ps1          # install missing packages and launchers
```

The `bootstrap_latest` entry points use the repo `.venv`. They do not reinstall an
existing distribution even when its source version changes, and they never replace
an existing `bin/` launcher. They create a missing venv or initialize a missing
`pscripts` submodule only when applying; a dry run changes nothing. They do not
refresh PATH, profiles, aliases, skills, help metadata, or package-specific runtime
extras. Use the regular `bootstrap` when those full setup tasks are wanted.
`--skip-reinstall` on the regular bootstrap retains its existing behavior and is
not equivalent to this missing-only mode.

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
│   ├── ...               # 40+ modules
│   └── setup.py          # Module installer
├── pyscripts/            # Standalone Python scripts
├── pscripts/             # Pinned private scripts and installable modules
├── pwsh/                 # PowerShell scripts
├── shell-scripts/        # Bash/Zsh scripts
├── scripts_setup/        # Setup utilities
├── knowledge_manager/    # Knowledge base management
├── bootstrap.sh          # Unix bootstrap script
├── bootstrap.ps1         # Windows bootstrap script
├── bootstrap_latest.py   # Shared missing-only installer
├── bootstrap_latest.sh   # Unix missing-only entry point
├── bootstrap_latest.ps1  # Windows missing-only entry point
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
| Private download CLIs | Installed from the pinned `pscripts` submodule |
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

### Module Dependencies and Ownership Boundary

Core modules are installed in order:
1. `standard_ui` - No dependencies
2. `cross_platform` - No dependencies
3. `python_setup` - Depends on `cross_platform`
4. `scripts_setup` - No dependencies

Other `scripts`-owned modules are auto-resolved via `modules/setup_utils/dependency_resolver.py`.

#### Transferred LLM Agent Toolkit Modules (Excluded from `scripts` Setup)

The 23 LLM/agent/benchmark modules transferred to [`MaxCarlson/llm-agent-toolkit`](https://github.com/MaxCarlson/llm-agent-toolkit) retain their historical source directories under `scripts/modules/` untouched on disk, but are permanently excluded from `scripts` installation, `scripts_manifest.json`, skill symlinking, and `scripts/bin` wrapper generation via [`scripts_setup/transferred_modules.py`](scripts_setup/transferred_modules.py):

- `agent_abilities` (`agent-abilities`), `agent_benchmark` (`agent-benchmark`), `agent_memory` (`agent-memory`), `agent_skills` (`agent-skills`), `agent_sync` (`agent-sync`), `agt` (`agt`), `ai_orchestrator` (`ai_orchestrator`), `benchmark_core` (`benchmark-core`), `interactive_reports` (`interactive-reports`), `knowledge_manager` (`knowledge_manager`), `llm-interface` (`api-parser`), `llm-models` (`llm-models`), `llm-patcher` (`llm-patcher`), `llm_local` (`llm-local`), `llm_monitor` (`llm-monitor`), `lmstui` (`lmstui`), `local_agent_bridge` (`local-agent-bridge`), `orchestrator_web_viewer` (`orchestrator-web-viewer`), `resource_coordinator` (`resource-coordinator`), `resource_metrics` (`resource-metrics`), `script_logging` (`script-logging`), `web_ai_automator` (`web-ai-automator`), and `web_ui_tools` (`web-ui-tools`).
- Install and manage those 23 modules and their 28 CLI commands from the standalone `llm-agent-toolkit` checkout (`.\bootstrap.ps1 -x` / `./bootstrap.sh -x`), which exposes `<llm-agent-toolkit>/bin` globally on `PATH`.
- `termdash` and `cross_platform` remain `scripts`-owned shared modules.
- See [`docs/POST_P6_CUTOVER_REPORT.md`](docs/POST_P6_CUTOVER_REPORT.md) for the complete cutover inventory and verification evidence.

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
