# Stage 1: Windows Runner and Unattended Elevation

## Implementation

- Add a PowerShell-backed Windows Task Scheduler integration module.
- Wire install/status/start/remove commands into the CLI.
- Wire the same actions into the TUI configuration menu.
- Skip the UAC wrapper when the process already holds an elevated token and repair child exit-code handling in the fallback.
- Add isolated unit tests for Windows task definitions, CLI/TUI integration, and elevation behavior.
- Update the scheduler README, package version, help registry, plan, and handoffs.

## Verification

- Run focused scheduler tests, then the full scheduler test target.
- Run compile and CLI help checks from the validation target.
- Inspect the final diff and confirm tests never register a production Windows task.
- Live task installation is not part of automated verification and must be an explicit setup action.
