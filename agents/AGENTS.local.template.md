# AGENTS.local.md

> Personal/machine-specific overrides. Add to .gitignore. Never commit.
> Supplements AGENTS.md with local environment configuration.

<local_environment>
## Machine Identification
- Hostname: [machine name]
- Platform: [wsl2 | termux | windows | macos | linux]
- Shell: [bash | zsh | pwsh | fish]

## Paths
- Home: [/home/user | /data/data/com.termux/files/home | C:\Users\user]
- Projects: [~/projects | /mnt/c/dev | custom]
- Python: [system | pyenv | custom path]
- Node: [system | nvm | n | custom path]
</local_environment>

<local_tool_overrides>
## Package Manager
- uv available: [true | false]
- Fallback: [pip | pip --break-system-packages]

## Command Overrides
```bash
# Example: Termux without uv
# alias uv="pip"
# Example: Custom Python path
# PYTHON=/usr/local/bin/python3.12
```

## Test Subset (fast iteration)
```bash
# Skip slow tests during development
# pytest tests/ -m "not slow" -x
```
</local_tool_overrides>

<local_constraints>
## Resource Limitations
- [ ] Low RAM (<8GB): limit parallel test workers
- [ ] No GPU: skip CUDA tests
- [ ] Metered network: avoid large downloads
- [ ] Termux: no native compilation, pip-only
- [ ] WSL2: avoid /mnt/c/ for performance

## Disabled Features
- [ ] Docker unavailable
- [ ] Root access unavailable
- [ ] Specific ports blocked
</local_constraints>

<local_secrets>
## Environment Variables (reference only, never values)
- API_KEY: [purpose]
- DATABASE_URL: [purpose]
- AWS_PROFILE: [purpose]

## Credential Paths
- SSH: ~/.ssh/
- AWS: ~/.aws/
- GCP: ~/.config/gcloud/
</local_secrets>

<local_notes>
## Current Work Context
- Active branch: [branch name]
- WIP: [description]
- Blocked by: [blocker if any]
- Next action: [next step]
</local_notes>
