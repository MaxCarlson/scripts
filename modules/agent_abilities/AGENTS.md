# AGENTS.md

Instructions for AI coding assistants working in this repository.

## Purpose

This is the **agent_abilities** module -- a universal resource manager for AI agent resources. Use it to:
1. Create new resources (agents, prompts, instructions, skills) from templates
2. Register and sync resources across CLI tools
3. Validate resource frontmatter against schemas

## Resource Types

| Type | File Pattern | Required Frontmatter |
|------|-------------|---------------------|
| agent | `name.agent.md` | `description` |
| prompt | `name.prompt.md` | `description` |
| instruction | `name.instructions.md` | `description`, `applyTo` |
| skill | `name/SKILL.md` | `name`, `description` |

All resources use **kebab-case** naming. Files use YAML frontmatter in `---` delimiters.

## Creating Resources

When asked to create a new resource, use the `abilities` CLI:

```bash
abilities create agent <name> -d "Description" [--model claude-opus-4-6] [--tools Bash,Read]
abilities create prompt <name> -d "Description" [--model claude-opus-4-6] [--tools Bash]
abilities create instruction <name> -d "Description" --apply-to "**.py, **.sh"
abilities create skill <name> -d "Description" [--with-refs] [--with-scripts]
```

Resources are created in `~/dotfiles/symlinked/llms/custom_agents/<type>/` and can be registered with `--register` or `abilities add`.

## Frontmatter Schemas

### Agent (`*.agent.md`)
```yaml
---
name: 'Human Readable Name'        # optional
description: 'What this agent does' # required
model: claude-opus-4-6              # optional
tools: ['Bash', 'Read', 'Edit']    # optional
---
```

### Prompt (`*.prompt.md`)
```yaml
---
description: 'What this prompt does' # required
tools: ['execute/runInTerminal']     # optional
model: claude-opus-4-6              # optional
---
```

### Instruction (`*.instructions.md`)
```yaml
---
description: 'What standards this enforces' # required
applyTo: '**.py, **.sh'                     # required (glob patterns)
---
```

### Skill (`<name>/SKILL.md`)
```yaml
---
name: skill-name          # required, must match folder, [a-z0-9-]
description: 'What it does' # required, 10-1024 chars
license: MIT              # optional
allowed-tools: Bash       # optional
---
```

## Symlink Chain

```
~/dotfiles/symlinked/llms/custom_agents/  (source of truth)
    -> ~/.local/share/agent-abilities/     (central registry)
        -> ~/.claude/{agents,prompts,instructions,skills}/
        -> ~/.codex/{agents,prompts,instructions,skills}/
        -> ~/.cursor/{agents,prompts,instructions,skills}/
```

## Key Paths

| Path | Purpose |
|------|---------|
| `agent_abilities/` | Python package |
| `agent_abilities/resource_types.py` | Type definitions and validation |
| `agent_abilities/templates.py` | Template generators |
| `agent_abilities/manager.py` | Core resource management |
| `agent_abilities/cli.py` | CLI entry point |

## Do Not

- Modify `refs/agentskills/` or `refs/openai-skills/` (upstream references)
- Create resources with underscores in names (use kebab-case)
- Skip required frontmatter fields
- Create skills without a containing folder
