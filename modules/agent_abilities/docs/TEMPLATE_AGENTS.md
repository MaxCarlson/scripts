# Agent File Format Specification

> Adapted from [awesome-copilot](https://github.com/github/awesome-copilot) agent specification.

## File Pattern

```
<name>.agent.md
```

## Directory Structure

```
agents/
  my-agent.agent.md
  code-reviewer.agent.md
```

## Frontmatter Schema

```yaml
---
description: 'Required: What this agent does'  # Required
name: 'Display Name'                            # Optional
model: claude-opus-4-6                            # Optional: AI model to use
tools: ['bash', 'read', 'write']                # Optional: Allowed tools
---
```

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `description` | string | What this agent does (shown in listings) |

### Optional Fields

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Human-readable display name |
| `model` | string | AI model identifier |
| `tools` | list | Tools/capabilities the agent can use |

## Body Format

The markdown body after frontmatter contains the agent's system prompt:

```markdown
# Agent Name

You are Agent Name, a specialized AI coding agent.

## Mission
What this agent does.

## Core Principles
- Principle 1
- Principle 2

## Workflow
1. Step 1
2. Step 2
```

## Best Practices

- Keep descriptions under 200 characters for clean listing output
- Use kebab-case for filenames: `my-agent.agent.md`
- Structure the system prompt with clear sections (Mission, Principles, Workflow)
- Specify only the tools the agent actually needs
