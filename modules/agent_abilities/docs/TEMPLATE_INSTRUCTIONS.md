# Instruction File Format Specification

> Adapted from [awesome-copilot](https://github.com/github/awesome-copilot) instruction specification.

## File Pattern

```
<name>.instructions.md
```

## Directory Structure

```
instructions/
  python-style.instructions.md
  typescript-rules.instructions.md
```

## Frontmatter Schema

```yaml
---
description: 'Required: What these instructions cover'   # Required
applyTo: '**/*.py'                                        # Required: File glob pattern
---
```

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `description` | string | What these instructions cover |
| `applyTo` | string | Glob pattern for files these rules apply to |

## Body Format

```markdown
# Instruction Name

Description of the coding standards.

## Conventions
- Follow existing project patterns
- Maintain consistency

## Guidelines
- Specific rules and standards

## Examples
- Before/after examples
```

## applyTo Patterns

| Pattern | Matches |
|---------|---------|
| `**` | All files |
| `**/*.py` | All Python files |
| `**/*.{ts,tsx}` | All TypeScript/TSX files |
| `src/**` | All files under src/ |

## Best Practices

- Instructions automatically apply to matching files
- Keep rules clear and actionable
- Include examples of correct and incorrect patterns
- Use specific glob patterns to target relevant files only
