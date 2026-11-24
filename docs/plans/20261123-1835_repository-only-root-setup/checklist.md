# Checklist

- [x] Add and observe failing regression tests before implementation.
- [x] Add `-r/--repository-only` mode and propagate it through subprocess setup calls.
- [x] Keep repository-local package installation and managed launcher generation active.
- [x] Discover private standalone scripts under `pscripts/pyscripts` as well as console entry points.
- [x] Suppress PATH, profile, skill, alias, PYTHONPATH, WSL2, and auto-activation hooks in repository-only mode.
- [x] Add explicit skill destination support and preserve defaults in normal setup.
- [x] Ignore inherited `SCRIPTS`; require explicit source paths to resolve to the invoked checkout and outputs below it.
- [x] Reject redirected source/output paths and external venv selection before installation; ignore inherited `SKIP_VENV_BOOTSTRAP` and reject `--no-venv`.
- [x] Exercise orchestration with conflicting `SCRIPTS`/`DOTFILES` and mocked external integrations.
- [x] Preserve external hooks in normal setup and suppress them in repository-only mode.
- [x] Run earlier full repository-only Windows setup successfully with online package access and the pinned private checkout.
- [x] Run a later online repository-only incremental setup successfully; verify `scripts_setup` is skipped after its package/import mapping repair.
- [x] Verify the `scripts_setup_utils` distribution import mapping with RED/GREEN regression evidence.
- [x] Keep repository-only launcher refresh active and enable cleanup of obsolete managed wrappers while preserving unmanaged launchers.
- [x] Verify 164 discovered commands, manifest entries, and wrappers; zero missing, colliding, unmanaged, or obsolete wrappers after cleanup.
- [x] Invoke `mangadl`, `ytaedl`, `aebndl`, `runmux`, and `termdash` launchers with `--help` from an external working directory and `PYTHONPATH` cleared.
- [x] Verify imports for `scripts_setup`, MangaDL, YTAEDL, and AEBN resolve to the worktree/private checkout.
- [x] Confirm `pip check` reports no broken requirements after setup; keep the non-fatal `~ympy` warning noted.
- [x] Pin vdedup's GPU Pillow requirement below 13 and test dependency compatibility with MangaDL.
- [x] Verify no external `DOTFILES` sentinel was created by repository-only setup.
- [x] Validate Windows symlink privilege failure separately; do not substitute a no-op or change profile/system state.
- [x] Add regressions for abbreviated long and combined short flags, symlinked POSIX interpreter identity, and inherited Python/pip destination overrides; observe six failures against the prior implementation.
- [x] Fix bootstrap environment detection using `sys.prefix`, fail closed on repository-only flag forms, clear common destination overrides, and validate resolved source/output paths.
- [x] Run focused setup regressions (64 passed, 1 POSIX-only skip, 1 submodule-dependent deselection), the vdedup compatibility test (1 passed), Python compilation, Ruff, and CRLF-aware whitespace checks.
- [x] Run repository-only `--help` with inherited PYTHONPATH/PIP destination overrides; exit 0 and no external target sentinels.
- [x] Run an actual POSIX symlink-venv bootstrap reproduction in Ubuntu WSL: venv `python` resolved to the same base binary as system Python, venv `sys.prefix` matched `.venv`, and setup selected `.venv/bin/python` for re-execution. The pytest form is skipped on this Windows host.
- [x] Re-run final-revision incremental repository-only setup: exit 0, all 55 public and 8 private module entries processed, launchers refreshed, and five representative `--help` commands passed externally with `PYTHONPATH` cleared.
- [x] Verify after final incremental setup: 164 commands, manifest entries, and `.cmd` wrappers; zero missing/colliding/unmanaged/obsolete wrappers; `pip check` reports no broken requirements.
- [x] Confirm vdedup GPU requirement wheels were reused from the local pip cache during the final incremental run; CPU-only force-reinstall behavior remains and CUDA is not qualified.
- [x] Replay full root setup from a fresh detached worktree with no `.venv` at final source revision `c5d579403557fb1b5fef265725c6cd40e01f5e1d`; `python setup.py --repository-only --no-update-help -v` exited 0 and installed 55 public modules plus 8 private modules.
- [x] Verify clean setup skipped PATH/profile/skills/activation integrations, selected the disposable worktree's own `.venv`, and did not create the external DOTFILES sentinel.
- [x] Run a subsequent incremental root setup in that fresh environment; exit 0, zero missing/colliding/unmanaged wrappers, and all 164 managed launchers up to date.
- [x] Run `pip check`, compare 164 manifest commands to 164 `.cmd` launchers, invoke five representative help commands externally with `PYTHONPATH` cleared, and confirm four import origins point into the disposable worktree/private checkout.
- [x] Keep Windows profile/shell symlink integration separate from repository-only qualification; WinError 1314 remains documented and no profile/system changes or privilege escalation were performed.
- [x] Stage, commit, and push the corrections as `97659e67c97a54900106ffe3b7b085c117d86de0`.
- [x] Update PR #37 with clean and incremental qualification evidence and mark it ready for review: https://github.com/MaxCarlson/scripts/pull/37 (base `main`; no applicable workflow runs reported).
- [x] Confirm no merge, user/system integration mutation, production GPU workload, or media download occurred.

## Known qualification limits

- The installed Torch build is CPU-only. The existing vdedup setup hook consequently force-reinstalls its GPU requirements on setup runs; full CUDA operation and setup idempotence on a CUDA-enabled machine are not demonstrated.
- Pip reports no broken requirements but emits a warning about an invalid `~ympy` leftover in this disposable worktree venv.
- A previous broad Python test attempt was blocked by unrelated environment/dependency conditions; focused setup suites pass.
