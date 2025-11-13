# README.md
# mypysetup (mps)

**Goals**
- Create new projects quickly (uv or stdlib venv).
- Install/check uv, pipx, micromamba (idempotent).
- Keep Windows `py` launcher aligned with `python` (offers to set `PY_PYTHON`).
- Append **pwsh7** `$PROFILE` / **WSL Ubuntu** `~/.zshrc`/`~/.bashrc` snippets on request.
- Uses your `cross_platform` module for OS detection and shell-safe commands.
- **New:** `-p/--print-cmds` prints a cheat-sheet of basic commands for your OS.

**Examples**
```bash
# List environment status (tools, paths, profiles)
mps -S

# Install missing tools only (user-scope where possible)
mps -I

# Create a project using uv + .venv
mps -C myproj -k uv -V .venv

# Create a project using stdlib venv
mps -C myproj -k venv -V .venv

# Create project without a venv (system python)
mps -C myproj -k none

# Print basic commands for your OS (uv, pipx, micromamba, venv, etc.)
mps -p
```

**Windows py-launcher alignment**
- If `py` resolves to a different interpreter than `python`, `mps` will offer to set `PY_PYTHON=3.11` (or your chosen version) in your profile.

**Profile snippets**
- PowerShell 7: `$PROFILE`
- Ubuntu (WSL2): `~/.zshrc` (or `~/.bashrc` if zsh isn’t default)
