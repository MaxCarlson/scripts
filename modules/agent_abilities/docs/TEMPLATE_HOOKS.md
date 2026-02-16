# Hook Folder Format Specification

> Based on the [GitHub Copilot hooks specification](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/coding-agent/use-hooks) and [awesome-copilot](https://github.com/github/awesome-copilot).

## Structure

```
hooks/
  my-hook/
    hooks.json         # Required: Event configuration
    my-hook.sh         # Hook script(s)
    README.md          # Optional: Documentation
```

## hooks.json Schema

```json
{
  "version": 1,
  "hooks": {
    "sessionStart": [
      {
        "type": "command",
        "command": "./my-hook.sh"
      }
    ],
    "sessionEnd": [
      {
        "type": "command",
        "command": "./cleanup.sh"
      }
    ]
  }
}
```

## Available Events

| Event | Description |
|-------|-------------|
| `sessionStart` | Fired when an agent session begins |
| `sessionEnd` | Fired when an agent session ends |
| `userPromptSubmitted` | Fired when a user submits a prompt |
| `preToolUse` | Fired before a tool is invoked |
| `postToolUse` | Fired after a tool completes |
| `errorOccurred` | Fired when an error occurs |

## Hook Entry Format

Each event maps to an array of hook entries:

```json
{
  "type": "command",
  "command": "./script.sh"
}
```

## Installation

1. Copy the hook folder to `.github/hooks/` in your repository
2. Ensure scripts are executable: `chmod +x *.sh`
3. Commit to your repository's default branch

## Best Practices

- Keep hooks lightweight and fast (they run synchronously)
- Use `set -euo pipefail` in shell scripts for safety
- Log hook activity for debugging
- Handle errors gracefully -- a failing hook should not break the session
- Use `sessionEnd` for cleanup and auto-commit workflows
