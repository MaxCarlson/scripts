# Runmux Web Process Launching

## Goal

Allow an authenticated Runmux Web user to launch a supervised process from a
workspace tab, then immediately inspect its registered run and output.

## Scope

Implement P0 requirements L01–L09: a persistent `+` tab, an empty-registry
action, command and argument entry, optional name, explicit working-directory
default, actionable validation/errors, pending-state duplicate protection, and
automatic transition to the real run tab after launch. Preserve the current
read-only details and supervisor-gated terminal behavior. Use disposable state
and synthetic processes for validation.

Out of scope: lifecycle controls, presets, saved commands, metadata disclosure,
monitoring, advanced logs, TUI formatting changes, and workspace customization.

## Approaches

1. Reuse `runmux.runner.create_managed_run` from an authenticated API route
   (chosen). It performs the same registry, history, environment, and supervisor
   setup used by `runmux run`, while accepting a structured argv list.
2. Execute the `runmux run` CLI as a child of the web service. This duplicates
   command serialization and startup error handling and adds an unnecessary
   process boundary.
3. Add a separate web-specific process launcher. This risks diverging from the
   established supervision and registration semantics.

The form will collect the executable and each argument as separate values (one
argument per line), keeping whitespace and quoting literal across Windows and
POSIX. It will never parse a shell command string. A blank working-directory
field means the directory from which `runmux web` was started; the UI will show
that concrete default. The optional name will be bounded and validated.

## Security and behavior

Mount launch only below `/api` so `web_ui_tools` applies its authenticated
session, trusted-host, same-origin, and no-store protections. Validate request
shape, argument count/size, executable, name, and directory before calling the
shared runner in a worker thread. Reject invalid directories with actionable
client errors. Do not change terminal websocket or input-lock code.

## Validation

- Add API tests first for authentication, same-origin enforcement, malformed
  input, valid argv/cwd/name forwarding, duplicate safety, and startup failures.
- Add frontend harness coverage for the plus/empty-state actions, pending guard,
  error display, and successful tab selection/output refresh.
- Run focused Runmux web tests, dashboard harness, Node syntax check, Ruff, and
  package compatibility checks; use a disposable state directory.
- Run the local authenticated browser against a synthetic registry and verify
  the new run appears and output is displayed.

## Delivery

Dedicated worktree: `.worktrees/runmux-web-launch-20261024`, branch
`codex/runmux-web-launch-20261024`, based on `origin/main` at
`6cbf599a8c5e51839f742c02876d035efefbca36`. Preserve the supplied image and gap
analysis in this branch. Update module documentation, then commit and push this
branch only; do not merge.
