# Prompt File Format Specification

> Adapted from [awesome-copilot](https://github.com/github/awesome-copilot) prompt specification.

## File Pattern

```
<name>.prompt.md
```

## Directory Structure

```
prompts/
  code-review.prompt.md
  generate-tests.prompt.md
```

## Frontmatter Schema

```yaml
---
description: 'Required: What this prompt does'   # Required
tools: ['bash', 'read']                           # Optional: Available tools
model: claude-sonnet-4-5-20250929                           # Optional: AI model
---
```

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `description` | string | What this prompt does |

### Optional Fields

| Field | Type | Description |
|-------|------|-------------|
| `tools` | list | Tools available during execution |
| `model` | string | AI model identifier |

## Body Format

```markdown
# Prompt Name

## Instructions
Detailed instructions for the prompt.

## Workflow
1. Step 1
2. Step 2

## Expected Output
Description of expected output format.
```

## Best Practices

- Prompts are reusable templates for specific tasks
- Use `/prompt-name` syntax to invoke in VS Code or similar
- Keep prompts focused on a single task or workflow
- Use kebab-case for filenames: `my-prompt.prompt.md`
