# Collection File Format Specification

> Adapted from [awesome-copilot](https://github.com/github/awesome-copilot) collection format.

## File Pattern

```
<name>.collection.yml
```

## Directory Structure

```
collections/
  my-tools.collection.yml
  python-dev.collection.yml
```

## YAML Schema

```yaml
id: my-tools
name: 'My Tools Collection'
description: 'Curated set of agents and prompts for my workflow'

tags:
  - tools
  - productivity

items:
  - type: agent
    path: agents/my-agent.agent.md
  - type: prompt
    path: prompts/my-prompt.prompt.md
  - type: instruction
    path: instructions/my-rules.instructions.md
  - type: skill
    path: skills/my-skill

display:
  icon: collection
  color: blue
```

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique kebab-case identifier |
| `name` | string | Human-readable display name |
| `description` | string | What this collection contains |

### Optional Fields

| Field | Type | Description |
|-------|------|-------------|
| `tags` | list | Categorization tags |
| `items` | list | Resources included in this collection |
| `display` | object | Display hints (icon, color) |

### Item Entry Format

```yaml
- type: agent|prompt|instruction|skill|hook
  path: relative/path/to/resource
```

## Best Practices

- Collections group related resources around a theme or workflow
- Use descriptive tags for discoverability
- Include a mix of resource types (agents + prompts + instructions)
- Keep collections focused -- prefer multiple small collections over one large one
