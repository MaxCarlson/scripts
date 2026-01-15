---
name: agent-skills
description: Manage and discover skills for AI coding assistants. Register skills, sync to CLIs (Codex, Claude, Cursor).
metadata:
  version: 0.1.0
  author: mcarls
  category: meta
compatibility:
  - codex-cli
  - claude-code
  - cursor
  - gemini-cli
---

# Agent Skills Manager

Universal skill management for AI coding assistants.

## Commands

```bash
# List registered skills
skills list
skills list --json

# Add a skill (directory must contain SKILL.md)
skills add /path/to/skill
skills add /path/to/skill --name custom-name
skills add /path/to/skill --sync  # Also sync to CLIs

# Remove a skill
skills remove skill-name

# Sync skills to CLI directories
skills sync            # All CLIs
skills sync codex      # Just Codex
skills sync claude     # Just Claude
skills sync cursor     # Just Cursor

# Scan for skills
skills scan ~/projects
skills scan ~/projects --json

# Auto-register all found skills
skills auto ~/projects
skills auto ~/projects --sync

# Show skill details
skills info skill-name
skills info skill-name --json
```

## Directories

- Central skills: `~/.local/share/agent-skills/`
- Codex skills: `~/.codex/skills/`
- Claude skills: `~/.claude/skills/`
- Cursor skills: `~/.cursor/skills/`

## Creating a Skill

Add a `SKILL.md` file to any project:

```markdown
---
name: my-skill
description: What this skill does
metadata:
  version: 1.0.0
compatibility:
  - codex-cli
  - claude-code
---

# My Skill

Documentation for the AI to read...
```

Then register it:

```bash
skills add /path/to/my-project --sync
```
