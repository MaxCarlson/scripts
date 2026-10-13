# Stage 3: Nested guidance and module routing

## Scope

- Make repo-root instructions explicitly discover nested module `AGENTS.md` files before editing module code.
- Keep module-owned plans and handoffs under that module's `docs/` when present; reserve `scripts/docs/` for shared work.
- Replace the runmux documentation-level policy copy with concise module-root guidance and a redirect.
- Replace obsolete aebndl git and machine-path instructions with verified, scoped module guidance.

## Verification

- Check paths and commands against the module source, README, and `pyproject.toml`.
- Verify the root-to-module instruction routing and keep the runmux generic policy copy out of active entrypoints.
- Run staged and unstaged `git diff --check` with submodule diff ignored; inspect status without recursing into `pscripts`.

## Boundary

Documentation-only. Do not commit, push, or change dotfiles. Fresh Codex runtime discovery from a module working directory remains an external manual check.

Last edited: 2026-10-12 21:45:53 -07:00
