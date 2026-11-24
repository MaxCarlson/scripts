# Status

- State: repository-only root setup is implemented and isolated Windows qualification is substantially complete; follow-up corrections are uncommitted on the feature branch.
- Branch: `fix/isolated-root-setup-20261124`
- Base: `b60155b94efb54da703ed166fb9a01bb8982d1d4`
- Workspace: `C:\Users\mcarls\src\scripts\.worktrees\isolated-root-setup-20261124`
- Pushed checkpoint: `e6af88d3381e7abd04312f47e5eea17cd4491056`; follow-up corrections include package import detection, managed launcher cleanup, and dependency compatibility.
- Private source: pinned `pscripts` Gitlink `d25e095f1ced76ec9e7904e0bf12db592defc798`; nested downloader dependency `af6bb8b1db14c8434c0a9da446ec49bbf067ab9b` is initialized.
- Isolation behavior: repository-only setup resolves to the invoked checkout, validates venv/source/output paths before installation, propagates mode through subprocesses, retains package/launcher installation, and skips user/system integration. It ignores inherited `SCRIPTS` and `SKIP_VENV_BOOTSTRAP`, and rejects incompatible external venv selection.
- Full setup: an earlier online repository-only run exited 0, installed public/private modules, and generated launchers. The current online incremental run exited 0; `scripts_setup` was correctly recognized as installed and skipped.
- Incremental qualification: all 55 public module entries processed, private setup processed all 8 modules, and managed launcher refresh completed. A `DOTFILES` sentinel outside the checkout remained absent.
- Package import correction: `scripts_setup_utils` now packages/imports `scripts_setup`; `_expected_import_modules()` recognizes an explicit setuptools root `package-dir`. The regression assertion failed before this correction (`['scripts_setup_utils']` instead of `['scripts_setup']`) and passes after it.
- Current environment health: `pip check` reports no broken requirements. Pip emits a non-fatal warning for an invalid `~ympy` leftover in the disposable venv. Torch is CPU-only, so the existing vdedup setup hook force-reinstalls its GPU requirements during setup; CUDA qualification is not claimed.
- Launchers: 164 discovered commands, 164 manifest entries, and 164 `.cmd` wrappers; zero missing, collision, unmanaged, or obsolete wrappers after cleanup. Imports for `scripts_setup`, MangaDL, YTAEDL, and AEBN resolve to the worktree/private sources. `mangadl`, `ytaedl`, `aebndl`, `runmux`, and `termdash` `--help` invocations pass from an external working directory with `PYTHONPATH` cleared.
- Focused tests: 58 passed, 1 submodule-dependent test deselected; vdedup dependency compatibility test 1 passed. Python compilation and Ruff passed (`F841` ignored per the existing baseline); CRLF-aware diff check passed before the latest test-only/doc edits and must be rerun before checkpoint.
- Windows privilege boundary: the symlink helper reports WinError 1314 without a no-op fallback. Full profile/shell symlink integration was not run or altered.
- Remaining: rerun final focused checks and diff review; commit and push the follow-up; inspect/create the scoped PR. Do not merge. Report CPU-only GPU reinstall behavior and privilege-dependent shell symlink limitation.
- Coordination: preserve retirement qualification branches PRs #34/#35, shared-package PR #22, and LLMD v2.1 work. No overlapping source changes were made.
