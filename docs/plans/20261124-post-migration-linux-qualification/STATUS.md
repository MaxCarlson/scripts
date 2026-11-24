# Status

Updated: 2026-11-24

## Baseline

- Feature branch: `fix/post-migration-linux-qualification-20261124`
- Base: `b60155b94efb54da703ed166fb9a01bb8982d1d4`
- Root cause confirmed: the workflow asserts a stale pscripts SHA literal instead of deriving expected commits from checked-out parent Gitlink entries.

## Progress

- [x] Test-first Gitlink validator repair: baseline test collection failed because the helper was absent; after implementation, 4 Gitlink tests pass, including mismatch and missing-link cases.
- [x] Replace fixed pscripts/AEBN SHAs with Gitlink-derived expected commits; add post-bootstrap procparsers import and migrated CLI launcher checks.
- [x] Focused Ruff, Python AST, YAML parse, and `git diff --check` checks pass locally; the focused Gitlink regression suite passes (4 tests).
- [x] Windows isolation review: `--dotfiles-dir` and `--bin-dir` can target temporary paths; `setup_skills.py` has no destination override and `setup_path.py` still writes HKCU PATH through `pwsh_pathmgr.py`. No root CLI option skips those hooks. A process-local `USERPROFILE` can redirect `Path.home()` skill targets, but cannot isolate the registry update.
- [x] Push and dispatch hosted Linux qualification; evaluate all job outcomes and skipped steps.

## Hosted qualification

- Initial run `45301785949` exposed a missing checkout-path argument in the standalone procparsers assertion. Commit `96ec4232e8894132d0e5c21b5ba83697f4a85c86` fixed that invocation.
- Run `45302575918` showed the procparsers assertion ran in the wheel-only environment before procparsers was installed. Commit `32c54355430d605829e6e8f9aa42a65d643e3d91` moved that assertion to the full-bootstrap environment.
- Final run `45302927058` passed in 7m27s on Ubuntu 24.04 / Python 3.12. Standalone wheel checks, Runmux and consumer tests, Gitlink tests, scoped deploy-key preflight, pinned private submodule checkout, clean Bash bootstrap, launcher tests, post-bootstrap provenance checks, and final dependency health all succeeded. The fail-closed blocked-bootstrap step was skipped because authenticated private checkout succeeded.
- Hosted tests: Gitlink validator 4 passed; no-private Runmux API tests 3 passed; selected consumer regressions 120 passed; launcher tests 3 passed.
- Bootstrap inventory: 64 packages installed; 69 script launchers and 95 console commands (164 managed launchers total); after bootstrap, zero packages, launchers, or proxies were missing and launcher generation reported zero failures.
- `procparsers==0.1.0` imported from `modules/procparsers/src/procparsers/__init__.py`. `mangadl`, `ytaedl`, and `aebndl` help invocations passed from `$RUNNER_TEMP` with `PYTHONPATH` unset.
- Non-blocking hosted warning: GitHub Actions reports Node.js 20 deprecation for `actions/checkout@v4` and `actions/setup-python@v5`.

## Windows root-setup recommendation

Add a root-level opt-out for user integrations during disposable qualification. Thread it through PATH registration and skill-link setup; add a configurable skills destination (or a narrowly scoped profile-root option). Keep `--dotfiles-dir`/`--bin-dir` pointed at temporary paths and set `USERPROFILE`/`APPDATA` only in the child process. This avoids HKCU writes and real profile paths. Windows symbolic links still require either Developer Mode already enabled or the symbolic-link privilege; Developer Mode itself is not a non-admin setup escape hatch on a machine where an administrator has not enabled it. Directory junctions do not replace the file symlinks used by this setup.
