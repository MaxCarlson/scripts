---
name: agent-abilities
description: Manage AI agent resources (agents, prompts, instructions, skills). Create, register, sync, and validate resources across CLI tools.
metadata:
  version: 0.2.0
  author: mcarls
  category: meta
compatibility:
  - codex-cli
  - claude-code
  - cursor
  - gemini-cli
---

# Agent Abilities Manager

Universal resource manager for AI coding agents. Create, register, validate, and sync agents, prompts, instructions, and skills across multiple CLI tools.

## Commands

```bash
# List registered resources
abilities list
abilities list --type skill --json

# Create a new resource from template
abilities create agent my-agent -d "Description of what this agent does"
abilities create prompt my-prompt -d "Description of what this prompt does"
abilities create instruction my-rules -d "What standards this enforces" --apply-to "**.py"
abilities create skill my-skill -d "What this skill does" --with-refs

# Register an existing resource
abilities add /path/to/resource
abilities add /path/to/resource --sync

# Remove a resource
abilities remove my-agent --type agent

# Sync to CLI directories
abilities sync            # All CLIs
abilities sync claude     # Just Claude Code

# Scan for resources
abilities scan ~/dotfiles/symlinked/llms/custom_agents/

# Auto-register all found resources
abilities auto ~/dotfiles/symlinked/llms/custom_agents/ --sync

# Show resource details
abilities info my-skill --type skill

# Validate frontmatter
abilities validate /path/to/resource.agent.md

# Show resource type specifications
abilities types
```

## Resource Types

| Type | Pattern | Required Fields |
|------|---------|----------------|
| agent | `*.agent.md` | `description` |
| prompt | `*.prompt.md` | `description` |
| instruction | `*.instructions.md` | `description`, `applyTo` |
| skill | `<name>/SKILL.md` | `name`, `description` |

## When to Use

- Use when: creating new agent resources, registering existing ones, syncing across CLIs
- Use when: asked to "make a skill", "create a prompt", "add an instruction", or "define an agent"
- Do not use when: simply reading or editing existing resource files directly

## Key Paths

| Path | Purpose |
|------|---------|
| `~/dotfiles/symlinked/llms/custom_agents/` | Source of truth (git-tracked) |
| `~/.local/share/agent-abilities/` | Central registry (symlinks) |
| `~/.claude/`, `~/.codex/`, `~/.cursor/` | CLI targets (symlinks) |
