# Stage 2: Setup Gate and Short Windows Setup Command

## Plan

- Use `cross_platform.SystemUtils` for current-OS detection and a shared readiness helper for the Windows runner.
- Treat the Windows setup as complete only when the runner is registered, enabled, interactive, and highest privilege.
- Add `scheduler setup windows` as a direct install command, with status/start/remove subcommands and the existing `windows-runner` spelling retained as an alias.
- Before normal CLI parsing or execution, show a red setup warning when setup is incomplete. Continue parsing help requests after warning, and allow setup operations through.
- In the TUI, show a large red warning and a setup-only main menu until setup is complete; refresh readiness after setup.
- Do not implement Linux setup. Explain that setup is not available yet on unsupported operating systems.
- Add focused CLI, readiness, and TUI tests; update package docs, version, validation target, status, checklist, and handoffs.

## Verification

- Run scheduler validation through `./Invoke-Tests.ps1 -Target scheduler -SkipBootstrap`.
- Run Ruff and `git diff --check` for the changed files.
- Confirm tests mock Task Scheduler and do not install or modify a live task.

## Acceptance Criteria

1. Normal CLI operations are blocked with a red setup instruction until the Windows runner is ready.
2. `scheduler -h` displays the warning before standard help when setup is incomplete.
3. Setup commands remain available before setup; `scheduler setup windows` installs the runner.
4. The TUI shows a red setup banner and only setup is selectable until setup completes.
5. No Linux setup code is added.
