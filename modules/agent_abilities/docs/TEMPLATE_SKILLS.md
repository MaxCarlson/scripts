# Skill Folder Format Specification

> Based on the [Agent Skills specification](https://agentskills.io/specification) and [awesome-copilot](https://github.com/github/awesome-copilot).

## Structure

```
skills/
  my-skill/
    SKILL.md           # Required: Entry file with frontmatter + instructions
    references/        # Optional: Reference documentation
    scripts/           # Optional: Helper scripts
    assets/            # Optional: Bundled assets (templates, data)
```

## SKILL.md Frontmatter Schema

```yaml
---
name: my-skill                                         # Required: kebab-case identifier
description: 'Required: What this skill does (10-1024 chars)'  # Required
license: MIT                                           # Optional
allowed-tools: 'bash, read, write'                     # Optional
---
```

### Required Fields

| Field | Type | Constraints |
|-------|------|-------------|
| `name` | string | kebab-case, max 64 chars, must match folder name |
| `description` | string | 10-1024 characters |

### Optional Fields

| Field | Type | Description |
|-------|------|-------------|
| `license` | string | License identifier (MIT, Apache-2.0, etc.) |
| `allowed-tools` | string | Comma-separated list of allowed tools |

## Body Format

```markdown
# Skill Name

## Overview
What this skill does.

## When to Use This Skill
- Trigger conditions and keywords
- Specific scenarios

## Workflow
1. Step 1
2. Step 2
```

## Best Practices

- Skills differ from prompts by supporting bundled resources (scripts, data, templates)
- Use skills for complex, repeatable workflows
- Name must be kebab-case and match the folder name exactly
- Description must be 10-1024 characters
- Include trigger keywords in "When to Use" for agent auto-discovery
