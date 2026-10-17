# LLM CLI Configuration Files

This directory contains configuration files and context files for various AI coding assistant CLIs.

## Structure

```
llms/
├── AGENTS.md                    # Master agent instructions (symlink target)
├── AGENTS.local.template.md     # Copy-only template for AGENTS.local.md
├── research-request-template.md # Copy-only template for .research-requests/_template.md
├── README.md                    # This file
├── symlinks.sh                  # Auto-sourced by setup/symlinks.sh
├── claude/
│   ├── CLAUDE.md                # Optional override (blank by default)
│   └── settings.json            # System-wide Claude Code settings
├── codex/
│   ├── AGENTS.md                # Optional override (blank by default)
│   └── config.toml              # Codex CLI config
├── gemini/
│   ├── GEMINI.md                # Gemini context
│   └── settings.json            # System-wide Gemini CLI settings
└── scripts/                     # Legacy context for ~/scripts repo
    ├── AGENTS.md
    └── GEMINI.md
```

## Automatic Symlinks

The `symlinks.sh` script creates the following symlinks automatically during setup:

- `~/.claude/settings.json` → `$DOTFILES/symlinked/llms/claude/settings.json`
- `~/.claude/CLAUDE.md` → Defaults to `symlinked/llms/AGENTS.md` unless `claude/CLAUDE.md` contains custom content
- `~/.gemini/settings.json` → `$DOTFILES/symlinked/llms/gemini/settings.json`
- `~/.gemini/GEMINI.md` → `$DOTFILES/symlinked/llms/gemini/GEMINI.md`
- `~/.codex/config.toml` → `$DOTFILES/symlinked/llms/codex/config.toml`
- `~/.codex/AGENTS.md` → Defaults to `symlinked/llms/AGENTS.md` unless `codex/AGENTS.md` contains custom content

## Project Initialization (`agents-init`)

Use the `agents-init` helper to drop the master AGENTS instructions into any project. Two entry points are provided so every platform is covered and both are linked into `$HOME/bin` / `$SCRIPTS/bin` during setup:

- `scripts/shell-scripts/agents-init.sh`
- `scripts/pwsh/agents-init.ps1`

### Bash/Zsh/Fish (Termux, Linux, macOS, WSL2)

```bash
# Initialize current repo
agents-init.sh

# Initialize a specific directory
agents-init.sh ~/code/my-app

# Replace an existing AGENTS.md (keeps templates intact)
agents-init.sh --force
```

### PowerShell (Windows, pwsh on Linux)

```powershell
# Initialize current directory
agents-init.ps1

# Point to another project and overwrite existing AGENTS.md
agents-init.ps1 -ProjectDir C:\code\my-app -Force
```

Each run:
- Symlinks `AGENTS.md` → `symlinked/llms/AGENTS.md`
- Copies `AGENTS.local.template.md` → `AGENTS.local.md` (only if missing)
- Copies `research-request-template.md` → `.research-requests/_template.md`
- Appends gitignore entries for `AGENTS.local.md` and research drafts

Override flow:
- Leave `claude/CLAUDE.md` and `codex/AGENTS.md` empty to inherit the master instructions everywhere
- Add content to either file to ship tool-specific overrides without touching the master

## Configuration Details

### Claude Code (`claude/settings.json`)

System-wide settings for [Claude Code](https://github.com/anthropics/claude-code):
- Environment variables (`SCRIPTS`, `DOTFILES`, `UV_LINK_MODE`)
- Extended thinking enabled

### Gemini CLI (`gemini/settings.json`)

System-wide settings for [Gemini CLI](https://github.com/google-gemini/gemini-cli):
- UI preferences (line numbers, citations)
- Context loading (recursive, respects gitignore)
- Theme and authentication settings

### Agent Context Files

#### AGENTS.md (master)
Vendor-neutral instructions consumed by every LLM CLI. Keep this file updated once and the symlinked copies stay in sync across projects and machines.

#### AGENTS.local.template.md
Copy-once helper that seeds `AGENTS.local.md` so each project can describe secrets, tokens, or machine-specific context without checking them into git.

#### research-request-template.md
Drop this into `.research-requests/_template.md` to guide future research tasks. The template lives in git, while per-request notes stay ignored.

#### GEMINI.md
Gemini CLI still consumes its own context file. Keep it under `gemini/GEMINI.md` (or link from `scripts/` if needed) to document workflows unique to Gemini.

## Usage

These symlinks are automatically set up when you run:

```bash
bash ~/dotfiles/setup.sh
```

Or specifically for symlinks only:

```bash
bash ~/dotfiles/setup/symlinks.sh
```

## Updating Configurations

To update a configuration:

1. Edit the file in `~/dotfiles/symlinked/llms/`
2. Changes are immediately reflected via the symlink
3. Commit and push to sync across systems

## Cross-Platform Notes

These configurations are designed to work across:
- **Termux** (Android): Primary development environment
- **Windows 11** (PowerShell 7+): Desktop development
- **WSL2** (Ubuntu): Linux subsystem on Windows

Platform-specific behavior is documented in the context files (AGENTS.md, GEMINI.md).
