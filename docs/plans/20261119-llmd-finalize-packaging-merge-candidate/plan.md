# Plan — Finalize llmd packaging and merge candidate

## Objective

Integrate the verified dispatcher commit into a fresh branch based on current `main`, declare `terminal-launcher` as a required local runtime dependency, synchronize terminal package versions at 0.1.1, document supported installation paths and remaining operational limitations, validate the combined product, and create one clean candidate commit.

## Ordered work

1. Preserve and inspect current refs/worktrees; merge verified integration commit `4cddb9a60c92e59a61740eee6f4fee416df06cc9` into the new branch based on `2edd36334d7d34074e03830b8896e8c9c8377da5`, then incorporate the newly advanced `main` commit `719e2e70a7fb9c3b3b530fe09b013ef3a6e3f0df`.
2. Confirm help registry registrations from both sides, required dependency ordering, and candidate differences from the earlier integration.
3. Add regression coverage for dependency and version metadata; update package metadata, implementation version, installation docs, and smoke-test instructions.
4. Run requested suites, static checks, CLI/import/discovery checks, wheel and disposable-environment install checks, and pseudo-TTY no-argument selector check. Do not launch Windows Terminal or providers.
5. Review task-only diff and worktree statuses; create the final merge checkpoint on the release-candidate branch with current `main` in its ancestry.

## Constraints and decisions

- `agent-continuity` requires `terminal-launcher>=0.1.1,<0.2`; the library has no reverse dependency.
- Both packages remain independently installable. Do not include Windows Terminal as a Python dependency.
- Preserve native session correlation as manual attach until hooks provide deterministic launch-ID correlation.
- Keep live Windows Terminal geometry and process startup explicitly unverified.
- Do not change prior worktrees, `main`, root `diagnostics/`, hooks, terminal settings, or external refs.

## Acceptance

A clean candidate commit preserves both current `main` and verified integration ancestry, required package metadata is consistent, the setup resolver orders terminal launcher before agent continuity, requested automated tests and installation checks pass (with environmental skips recorded), and no live provider or terminal launch occurs.
