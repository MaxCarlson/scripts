# Tool Install Manager (tim)

This module helps answer: "Is a tool installed? Where? Which package manager owns it?" and provides guidance for safe installs, avoiding shadowed duplicates.

## Quick Usage

```bash
tim isin rg
tim isin rg --cleanup
tim tool status -c rg
tim tool ensure -c rg
```

`tim isin <tool>` prints:
- Primary path (PATH order)
- All detected paths
- Manager candidates and uninstall hints
- Duplicate signals (multi-path / multi-manager)

Use `--cleanup` to offer an uninstall plan for non-primary managers (dry-run unless `--apply`).

## Package Manager Guidance

### When to use `uv`

Use `uv` for:
- Creating project virtual environments quickly (`uv venv --seed`)
- Installing project dependencies inside a venv (`uv pip install -r requirements.txt`)
- Installing Python-based CLI tools in isolated tool environments (`uv tool install ruff`)

Avoid `uv` for:
- System-level packages managed by OS package managers (`apt`, `pkg`, `winget`)
- Non-Python tools where OS package managers are available

### When to use `pipx`

Use `pipx` for:
- Python CLI tools you want globally available without polluting your base Python
- Tools that aren't packaged well by the OS package manager

Avoid `pipx` for:
- Libraries needed only inside a project venv
- OS-managed tools (prefer OS package manager)

### When to use a `.venv`

Use a per-project `.venv` for:
- Any Python project with dependencies
- Reproducible builds and isolation
- Avoiding conflicts with global packages

Recommended:
- Create with `uv venv --seed` (fast, reliable)
- Install with `uv pip install -e .` for local dev

### Global Python

Recommended policy:
- Keep system Python clean (minimal base deps)
- Use `pipx`/`uv tool` for global CLIs
- Use `.venv` for projects

This avoids version conflicts and makes upgrades safer.

### Decision Guide (Short Version)

- OS package managers (`apt/pkg/winget`):
  - Preferred for system tools and compiled binaries (rg, fd, jq, git).
- `uv tool`:
  - Preferred for Python CLIs you want system-wide but isolated (ruff, black, mypy).
- `pipx`:
  - OK alternative for Python CLIs if `uv` is missing or for compatibility.
- Project `.venv`:
  - Always use for application/project dependencies.
- Never install libraries into the global Python unless you intentionally maintain a global env.

### Decision Guide (Verbose)

If the tool is:
- **System/binary tool** -> use OS manager (winget/apt/pkg).
- **Python CLI (not a library)** -> use `uv tool` (or `pipx`).
- **Python library for a project** -> install in `.venv` via `uv pip`.
- **Build tool for one repo** -> use `.venv`.
- **Tool used across repos** -> `uv tool` or `pipx`.
- **Already managed by another manager** -> upgrade via that manager, avoid shadow installs.

### Termux specifics

- Prefer `pkg` for binaries.
- Prefer `uv`/`pipx` for Python CLIs.
- Avoid manual installs to `/data/data/com.termux/files/usr` unless necessary.

## Activation / Deactivation

### Termux (Android)

```bash
source .venv/bin/activate
deactivate
```

### WSL2 / Linux

```bash
source .venv/bin/activate
deactivate
```

### Windows (PowerShell 7)

```powershell
.\.venv\Scripts\Activate.ps1
deactivate
```

### Windows (cmd)

```cmd
.\.venv\Scripts\activate.bat
deactivate
```

## Auto-Activation When `cd`

Python cannot auto-activate on `cd` without shell hooks. Recommended options:

1) `direnv` (best)
   - Add `.envrc` with:
     ```bash
     source .venv/bin/activate
     ```
   - Run `direnv allow`

2) `autoenv` (legacy)
3) Shell hook function (manual)

Example `zsh`/`bash` hook:

```bash
_auto_venv() {
  local dir="$PWD"
  while [[ "$dir" != "/" ]]; do
    if [[ -f "$dir/.venv/bin/activate" ]]; then
      if [[ "$VIRTUAL_ENV" != "$dir/.venv" ]]; then
        [[ -n "$VIRTUAL_ENV" ]] && deactivate
        source "$dir/.venv/bin/activate"
      fi
      return
    fi
    dir="$(dirname "$dir")"
  done
  [[ -n "$VIRTUAL_ENV" ]] && deactivate
}
autoload -U add-zsh-hook 2>/dev/null || true
add-zsh-hook chpwd _auto_venv
_auto_venv
```

PowerShell auto-activate is possible via profile scripts; similar logic can be added for `Set-Location`.

## Preferred Installation Choices

Default priority by OS:
- Windows: winget, scoop, choco, uv, pipx
- WSL2/Linux: apt, brew, uv, pipx
- Termux: pkg, apt, uv, pipx

Per-tool overrides live in `manager_policy.json`.

## Notes

- `tim` is safe by default (dry-run). Use `--apply` to execute commands.
- Use `tim tool guard` before installing to avoid shadowing existing installs.
