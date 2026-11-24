# Checklist

- [x] Add and observe failing regression tests before implementation.
- [x] Add repository-only CLI mode and subprocess propagation.
- [x] Keep local package installation and managed launcher generation active.
- [x] Discover private standalone scripts under `pscripts/pyscripts`.
- [x] Suppress PATH, profile, skill, alias, PYTHONPATH, WSL2, and auto-activation hooks in repository-only mode.
- [x] Add explicit skill destination support and preserve defaults.
- [x] Validate Windows symlink privilege failure separately without a no-op fallback.
- [x] Run focused setup tests, syntax/lint checks, and attempt disposable clean/incremental Windows setup.
- [x] Reverify all five qualified wheel hashes and metadata; repository-only setup reaches shared-package preflight but cannot resolve uncached dependencies because package-index DNS is unavailable.
- [ ] Complete full package installation, launcher inventory, private CLI help, and full dependency consistency checks when uncached dependencies and the pinned pscripts checkout are available.
- [x] Review task-only diff; the final diff check is clean with CRLF-aware whitespace handling.
- [ ] Stage/commit/push and prepare a scoped PR; `git add` remains blocked creating `.git/worktrees/isolated-root-setup-20261124/index.lock` with `Permission denied`, despite the declared writable root. Git submodule checkout is separately blocked by `sh.exe` `NtCreateDirectoryObject ... 0xC0000022`.
