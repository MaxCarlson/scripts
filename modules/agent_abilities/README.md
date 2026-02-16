# Agent Abilities

Universal resource manager for AI coding agents (Claude Code, Codex CLI, Cursor, Gemini CLI).

Manages 4 resource types: **agents**, **prompts**, **instructions**, and **skills** -- with proper frontmatter schemas, naming conventions, symlink wiring, and template generation.

## Installation

```bash
pip install -e /path/to/agent_abilities
```

## Quick Start

```bash
# Create a new resource
abilities create agent my-agent -d "Does X"
abilities create prompt my-prompt -d "Generates Y"
abilities create instruction my-rules -d "Enforces Z" --apply-to "**.py"
abilities create skill my-skill -d "Handles W"

# Register and sync all resources from dotfiles
abilities auto ~/dotfiles/symlinked/llms/custom_agents/ -s

# List all registered resources
abilities list

# Sync to all CLIs
abilities sync
```

## How It Works

1. **Source of truth**: Resources live in `~/dotfiles/symlinked/llms/custom_agents/` (git-tracked)
2. **Central registry**: Symlinked to `~/.local/share/agent-abilities/`
3. **CLI sync**: Symlinked from central to each CLI's resource directories
4. **Templates**: Each type follows a defined frontmatter schema and file structure

### Symlink Chain

```
dotfiles/symlinked/llms/custom_agents/  (source, git-tracked)
    -> ~/.local/share/agent-abilities/  (central registry)
        -> ~/.claude/                   (CLI target)
        -> ~/.codex/                    (CLI target)
        -> ~/.cursor/                   (CLI target)
```

## Resource Types

| Type | File Pattern | Location | Required Frontmatter |
|------|-------------|----------|---------------------|
| agent | `name.agent.md` | `agents/` | `description` |
| prompt | `name.prompt.md` | `prompts/` | `description` |
| instruction | `name.instructions.md` | `instructions/` | `description`, `applyTo` |
| skill | `name/SKILL.md` | `skills/` | `name`, `description` |

## CLI Reference

| Command | Description |
|---------|-------------|
| `abilities list [--type TYPE]` | List registered resources |
| `abilities create <type> <name> -d "..."` | Create from template |
| `abilities add <path>` | Register existing resource |
| `abilities remove <name> --type <type>` | Remove a resource |
| `abilities sync [cli]` | Sync to CLI directories |
| `abilities scan <path>` | Find resources in a directory |
| `abilities auto <path>` | Auto-register found resources |
| `abilities info <name> --type <type>` | Show resource details |
| `abilities validate <path>` | Validate frontmatter |
| `abilities types` | Show resource type specs |

## Supported CLIs

- **Claude Code**: `~/.claude/{agents,prompts,instructions,skills}/`
- **Codex CLI**: `~/.codex/{agents,prompts,instructions,skills}/`
- **Cursor**: `~/.cursor/{agents,prompts,instructions,skills}/`

## Directory Structure

```
agent_abilities/
├── agent_abilities/       # Python package
│   ├── __init__.py
│   ├── cli.py             # CLI entry point
│   ├── manager.py         # Resource management logic
│   ├── resource_types.py  # Type definitions and validation
│   └── templates.py       # Template generators
├── refs/
│   ├── agentskills/       # Anthropic spec (submodule)
│   └── openai-skills/     # OpenAI catalog (submodule)
├── tests/                 # Pytest tests
├── AGENTS.md              # Instructions for AI agents
├── SKILL.md               # This module as a skill
└── README.md              # This file
```

## License

MIT
