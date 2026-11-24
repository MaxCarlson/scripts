# Status

Updated: 2026-11-24

## Baseline

- Feature branch: `fix/post-migration-linux-qualification-20261124`
- Base: `b60155b94efb54da703ed166fb9a01bb8982d1d4`
- Root cause confirmed: the workflow asserts a stale pscripts SHA literal instead of deriving expected commits from checked-out parent Gitlink entries.

## Progress

- [x] Test-first Gitlink validator repair: baseline test collection failed because the helper was absent; after implementation, 4 Gitlink tests pass, including mismatch and missing-link cases.
- [x] Replace fixed pscripts/AEBN SHAs with Gitlink-derived expected commits; add post-bootstrap procparsers import and migrated CLI launcher checks.
- [x] Focused Ruff, Python AST, YAML parse, and `git diff --check` checks pass locally; hosted qualification remains pending.
- [x] Windows isolation review: `--dotfiles-dir` and `--bin-dir` can target temporary paths; `setup_skills.py` has no destination override and `setup_path.py` still writes HKCU PATH through `pwsh_pathmgr.py`. No root CLI option skips those hooks. A process-local `USERPROFILE` can redirect `Path.home()` skill targets, but cannot isolate the registry update.
- [ ] Push and dispatch hosted Linux qualification; evaluate all job outcomes and skipped steps.

## Windows root-setup recommendation

Add a root-level opt-out for user integrations during disposable qualification. Thread it through PATH registration and skill-link setup; add a configurable skills destination (or a narrowly scoped profile-root option). Keep `--dotfiles-dir`/`--bin-dir` pointed at temporary paths and set `USERPROFILE`/`APPDATA` only in the child process. This avoids HKCU writes and real profile paths. Windows symbolic links still require either Developer Mode already enabled or the symbolic-link privilege; Developer Mode itself is not a non-admin setup escape hatch on a machine where an administrator has not enabled it. Directory junctions do not replace the file symlinks used by this setup.
