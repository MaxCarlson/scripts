# Custom Agent Resources

Personal collection of AI agent resources, managed by the `agent_abilities` Python module.

## Directory Structure

```
custom_agents/
  agents/           *.agent.md files -- custom AI agent definitions
  prompts/          *.prompt.md files -- reusable prompt templates
  instructions/     *.instructions.md files -- coding standards per file pattern
  skills/           <name>/SKILL.md -- self-contained skill folders with bundled assets
  templates/        Reference templates for each resource type
```

## Resource Types

| Type | File Pattern | Required Frontmatter |
|------|-------------|---------------------|
| agent | `name.agent.md` | `description` |
| prompt | `name.prompt.md` | `description` |
| instruction | `name.instructions.md` | `description`, `applyTo` |
| skill | `name/SKILL.md` | `name`, `description` |

## Usage

```bash
# Create a new resource
abilities create agent my-agent -d "Does X"
abilities create prompt my-prompt -d "Generates Y"
abilities create instruction my-rules -d "Enforces Z" --apply-to "**.py"
abilities create skill my-skill -d "Handles W"

# Register and sync
abilities auto ~/dotfiles/symlinked/llms/custom_agents/ -s

# List all registered resources
abilities list
```

## Symlink Chain

```
dotfiles/symlinked/llms/custom_agents/  (source of truth, git-tracked)
    -> ~/.local/share/agent-abilities/  (central registry)
        -> ~/.claude/                   (CLI target)
        -> ~/.codex/                    (CLI target)
        -> ~/.cursor/                   (CLI target)
```
