# Status

- State: implementation and focused regressions complete; full qualification and publication remain blocked by shared Git metadata write denial, unavailable dependency wheels/package-index DNS, and inability to launch Git's submodule shell
- Branch: `fix/isolated-root-setup-20261124`
- Base: `b60155b94efb54da703ed166fb9a01bb8982d1d4`
- Workspace: `C:\Users\mcarls\src\scripts\.worktrees\isolated-root-setup-20261124`
- Implemented: `-r/--repository-only`, environment propagation, integration-hook gating, public/private standalone launcher discovery, and repeatable skill destinations.
- Regression evidence: before implementation, the new suite reported 12 expected failures and 3 passes. After implementation, it reports 16 passes.
- Focused regression suites: 44 passed, 1 submodule-dependent test deselected. Existing launcher tests could not collect because the isolated environment lacks `script_logging.launcher` from the required shared distribution.
- Static checks: Python compilation passed; Ruff passed with the known, unchanged F841 finding ignored; CRLF-aware `git diff --check` passed.
- Windows simulation: the symlink helper's WinError 1314 path raised and reported the privilege requirement. Full shell-symlink integration was not run.
- Disposable setup: the isolated worktree venv contains seed `pip`; seed-only `pip check` passed. A fresh repository-only setup attempt with `PIP_FIND_LINKS` pointed at `.github/qualified-wheelhouse` exited 1 at shared-package preflight. The local wheels were discovered, but uncached transitive dependencies could not resolve because DNS to the package index failed (`psutil`, `fastapi`, and Windows-only `windows-curses`). Repository-only setup stopped before private module setup or launcher generation. Full package inventory, private CLI help, and full dependency `pip check` remain unqualified.
- Qualified artifacts: all five `.github/qualified-wheelhouse` wheel hashes and metadata names/versions match `SHA256SUMS.txt`.
- Submodule: the worktree records pscripts Gitlink `d25e095f1ced76ec9e7904e0bf12db592defc798`, but the checkout is uninitialized. `git submodule update --init --recursive pscripts` could not start Git for Windows `sh.exe` (`NtCreateDirectoryObject ... 0xC0000022`), preventing private package installation in this environment.
- Publication blocker: `git add` failed creating `C:\Users\mcarls\src\scripts\.git\worktrees\isolated-root-setup-20261124\index.lock` with `Permission denied`. `git rev-parse --git-common-dir` resolves to `C:\Users\mcarls\src\scripts\.git`; its ACL includes explicit deny entries for write access despite the sandbox declaring this directory writable. Commit, push, and PR creation cannot proceed. No escalation was attempted.
- Remaining: restore effective write access to the linked-worktree Git metadata and a working Git shell, and provide the uncached dependencies in the configured wheelhouse or package-index access. Then initialize only the pinned pscripts submodule, rerun full and incremental setup qualification, and stage/commit/push/open the scoped PR.
- Coordination: PR #34/#35 do not change root setup or launcher generator; avoid their shared/transferred ownership files. LLMD v2.1 changes only `modules/agent_continuity`.
