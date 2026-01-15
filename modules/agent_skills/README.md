# Agent Skills

Universal skill manager for AI coding assistants (Codex CLI, Claude Code, Cursor, Gemini CLI).

## Installation

```bash
pip install -e /path/to/agent_skills
```

## Quick Start

```bash
# Scan for skills in your projects
skills scan ~/scripts/modules

# Auto-register any found skills
skills auto ~/scripts/modules --sync

# List what's registered
skills list

# Sync to all CLIs
skills sync
```

## How It Works

1. **Central directory**: Skills registered at `~/.local/share/agent-skills/`
2. **Symlinks**: Each skill is a symlink to the actual project
3. **CLI sync**: Creates symlinks in each CLI's skill directory
4. **SKILL.md**: Standard format all CLIs understand

## CLI Reference

| Command | Description |
|---------|-------------|
| `skills list` | List registered skills |
| `skills add <path>` | Add skill from directory with SKILL.md |
| `skills remove <name>` | Remove a skill |
| `skills sync [cli]` | Sync to CLI directories |
| `skills scan <path>` | Find SKILL.md files |
| `skills auto <path>` | Auto-register found skills |
| `skills info <name>` | Show skill details |

## Supported CLIs

- **Codex CLI**: `~/.codex/skills/`
- **Claude Code**: `~/.claude/skills/`
- **Cursor**: `~/.cursor/skills/`

## Creating Skills

Any project can become a skill by adding `SKILL.md`:

```markdown
---
name: my-tool
description: Short description
metadata:
  version: 1.0.0
compatibility:
  - codex-cli
  - claude-code
---

# My Tool

Instructions for AI assistants...
```

## License

MIT
