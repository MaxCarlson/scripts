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
- [x] Run focused setup regressions (58 passed, 1 submodule-dependent test deselected), the vdedup compatibility test (1 passed), Python compilation, Ruff, and CRLF-aware whitespace checks.
- [ ] Run final task-only diff/status checks, then stage, commit, push, and prepare the scoped PR.
- [ ] If a suitable Windows environment becomes available, verify real shell symlink integration separately; current machine reports WinError 1314 and user/system integration remains intentionally disabled.

## Known qualification limits

- The installed Torch build is CPU-only. The existing vdedup setup hook consequently force-reinstalls its GPU requirements on setup runs; full CUDA operation and setup idempotence on a CUDA-enabled machine are not demonstrated.
- Pip reports no broken requirements but emits a warning about an invalid `~ympy` leftover in this disposable worktree venv.
- A previous broad Python test attempt was blocked by unrelated environment/dependency conditions; focused setup suites pass.
