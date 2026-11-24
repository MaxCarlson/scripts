# Checklist

- [x] Add and observe failing regression tests before implementation.
- [x] Add repository-only CLI mode and subprocess propagation.
- [x] Keep local package installation and managed launcher generation active.
- [x] Discover private standalone scripts under `pscripts/pyscripts`.
- [x] Suppress PATH, profile, skill, alias, PYTHONPATH, WSL2, and auto-activation hooks in repository-only mode.
- [x] Add explicit skill destination support and preserve defaults.
- [x] Ignore inherited `SCRIPTS` for repository-only mode; require explicit source paths to resolve to the invoked checkout and output paths to resolve below it.
- [x] Reject redirected source/output paths and external venv selection before venv creation or package installation; ignore inherited `SKIP_VENV_BOOTSTRAP` and reject `--no-venv`.
- [x] Exercise full repository-only orchestration with conflicting `SCRIPTS`/`DOTFILES` and mocked external integrations.
- [x] Run the actual repository-only entrypoint with conflicting external environment targets and offline qualified wheels; it stopped at the known missing transitive dependencies and did not create the external `DOTFILES` sentinel.
- [x] Validate Windows symlink privilege failure separately without a no-op fallback.
- [x] Run focused setup tests, syntax/lint checks, and attempt disposable clean/incremental Windows setup.
- [x] Reverify all five qualified wheel hashes and metadata; repository-only setup reaches shared-package preflight but cannot resolve uncached dependencies because package-index DNS is unavailable.
- [x] Verify source launcher discovery identifies all 164 commands, including private `mangadl`, `ytaedl`, and `aebndl` sources.
- [ ] Complete full/incremental package installation, installed launcher inventory/invocation, private CLI help, and full dependency consistency checks when uncached dependencies and Git submodule metadata access are available. Current `pip check` covers the incomplete worktree venv only.
- [x] Review task-only diff; the final diff check is clean with CRLF-aware whitespace handling.
- [ ] Stage/commit/push and prepare a scoped PR; new follow-up changes remain uncheckpointed because writing `.git/worktrees/isolated-root-setup-20261124/index.lock` is denied by ACL. Submodule status is also blocked on its administrative worktree path and Git `sh.exe` fails with `NtCreateDirectoryObject ... 0xC0000022`.
