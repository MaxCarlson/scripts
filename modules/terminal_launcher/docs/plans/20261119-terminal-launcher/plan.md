# Reusable Terminal Launcher Implementation Plan

## Goal

Implement a terminal-independent immutable plan/layout API and a Windows Terminal backend for `modules/terminal_launcher`, preserving the public integration contract in the implementation handoff.

## Decisions

- Keep the package dependency-free and module-root importable, following adjacent flat package conventions.
- Represent layouts as `auto`, `single`, `two-column`, `three-left`, and `grid`; use deterministic Windows Terminal command sequences for the documented 1–4 pane layouts.
- Build `wt.exe` calls as argument vectors with explicit Windows Terminal command separators; use a package-local Python relay and URL-safe payload to preserve original child argv/cwd across WT's command grammar; never use a shell.
- Reject semicolons in tab titles and target-window names because WT's own delimiter handling cannot safely preserve these metadata values.
- Treat a successful `wt.exe` process exit as submission only. Child process state remains unknown.
- Keep `target_window=None` mapped to Windows Terminal's documented default window selection and report that policy in preview warnings.
- Do not modify global terminal settings or depend on `agent_continuity`.

## Milestones

1. Models and deterministic grouping/layout planning.
2. Typed backend contract, preview/result models, and errors.
3. Windows Terminal capability validation, command construction, and subprocess submission.
4. Package docs, exports, dependency/package discovery, and focused regression checks.

## Validation

- Run package pytest suite and Ruff from this module.
- Check `git diff --check`, import from the repository `modules` path, and confirm no `agent_continuity` import/dependency.
- Inspect package discovery and run the closest repository setup/help checks.
- Use the current Microsoft Windows Terminal CLI documentation for syntax. No interactive terminal launch is authorized; actual window geometry and child-process startup remain unverified.

## Git

- Base: `f57b22652dfc8cd67823a2a0d1d2792b3f09a320`.
- Branch: `feature/terminal-launcher` in `.worktrees/terminal-launcher-20261119`.
- Checkpoint commits are authorized. Pushing and merging are explicitly out of scope.
