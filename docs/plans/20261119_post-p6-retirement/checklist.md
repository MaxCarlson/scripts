# Source-retirement checklist — PR B

- [x] Start an isolated retirement branch from the validated PR #22 source tree.
- [x] Recheck PR #22 is open/unmerged and its Ubuntu qualification evidence.
- [x] Reuse the prior five-directory file inventories; confirm all tracked/filesystem counts match and no ignored, untracked, symlink, reparse-point, or enumeration-error entries exist in the candidate worktree.
- [x] Recompute all five qualified shared-wheel SHA-256 hashes and verify package import names/versions.
- [x] Audit active source paths, runtime consumers, launcher/help entries, installer metadata, validation targets, and legacy user-data discovery paths.
- [x] Preserve the `resource_metrics` H4 bundle-source hold and `web_ui_tools` ownership hold.
- [x] Remove `script_logging`, `termdash`, and `cross_platform` in this branch only; verify the paths are absent.
- [x] Update validation targets to install qualified wheels, remove source-path PYTHONPATH/editable dependencies, and check installed distribution provenance.
- [x] Remove stale TermDash source entries from both Scripts Help registries while preserving the installed TermDash console command.
- [x] Update current setup standards to refer to shared distribution ownership.
- [x] Observe the new Help-registry test fail before registry cleanup and pass afterward.
- [x] Run setup/shared ownership and Scripts Help tests: 53 passed.
- [x] Run cross-platform and script-logging wheel validation targets: both pass, including `pip check`.
- [x] Run Compresser tests (61 passed), MangaDL tests, scheduler analytics/history (13 passed), and RRBackup selected suite (321 passed, 7 skipped; two external-binary cases deselected).
- [x] Verify five wheel import origins in disposable venv; no old shared distributions; `pip check`; TermDash and Runmux CLI help.
- [x] Run bootstrap dry-run; zero failures and no writes.
- [x] Restore only pre-existing tracked validation reports changed/pruned by the validation dispatcher; retain new run evidence as untracked artifacts.
- [x] Update STATUS with exact dispositions for all 25 unique directories, holds, test results, and rollback steps.
- [x] Review task-only diff and run final `git diff --check`.
- [x] Commit the cleared PR B subset (`6fe4d814`) and push branch `retire/shared-sources-20261123`.
- [x] Open PR #28 targeting PR #22's branch; PR #28 is open and currently reported mergeable.
- [x] Keep both retirement PRs unmerged; preserve historical retirement evidence and all protected work.

## Remaining holds

- `resource_metrics`: active Resource Coordinator H4 bundle builder exports the path as a pinned `resource-metrics==0.2.0` source artifact. Coordinate an H4 artifact/source change before retiring it.
- `web_ui_tools`: explicit ownership hold; automatic safety review rejected removing it. Requires a direct revised ownership decision before any retirement attempt.
- Windows Runmux HTTP: not requalified because the known host socket-pair initialization failure happens before request dispatch. Ubuntu Runmux HTTP passed on PR #22 before source removals; no Ubuntu job was run on PR B.
- RRBackup's validation-target editable install: the disposable venv hits a Setuptools temp-variable error; direct source consumer tests pass. The unfiltered Windows suite has a host `rclone` process launch failure (`WinError 623`).
- Publication and clean-PyPI installation remain separate integration gates; they do not invalidate the wheelhouse-backed source-removal proof.
