# Integration Checklist

## Prerequisite and ownership

- [x] Commit the local qualification workflow and wheelhouse at `e71ec54b` on `feat/scripts-shared-packages-20261119`; subsequent continuation authorizes pushing this branch only, with no merge.
- [x] Inspect supplied shared-package contract and package metadata.
- [x] Match all five wheel hashes against `dist/SHA256SUMS.txt`.
- [x] Install the wheels into a separate scripts integration worktree environment.
- [x] Independently inspect local dirty state in shared and toolkit checkouts: shared clean at `a5602e56` (`feat/dev-bootstrap-20261119`), package/dist tree same as `main` `ff134131`; toolkit clean at `0462cf49`. Read-only GitHub query found no open scripts PR and one unrelated toolkit Dependabot PR; shared repository query was inaccessible (API 422), so check its open PRs before integration.

## Scripts installer and launcher

- [x] Add scripts-owned shared distribution ranges and source install detection.
- [x] Exclude shared source copies from root/module setup, dependency resolution, bootstrap and module discovery.
- [x] Preserve toolkit transferred application and CLI exclusions.
- [x] Keep TermDash installed CLI discoverable.
- [x] Remove toolkit `.venv` fallback from generated scripts launchers.
- [x] Add scripts-owned manifest refresh adapter and invocation-preserving wrapper tests.
- [x] Update scripts-owned package dependencies and corresponding embedded package versions.

## Validation

- [x] Targeted setup/shared-package/launcher tests (28 passed; one submodule-dependent test excluded).
- [x] Consumer regression selection: backup_module, compresser, rrbackup, system_manager, scheduler (61 passed).
- [x] sysmon sampler tests (4 passed).
- [x] vdedup capability tests (19 passed; one actual-GPU test deselected).
- [x] Runmux web CLI and adapter tests (22 passed).
- [x] Construct Runmux ASGI app using installed `web-ui-tools` with temporary state and without starting a service.
- [x] Verify installed shared import paths and distribution versions under `python -I`.
- [x] Verify `pip check` and TermDash CLI help.
- [x] Exercise TermDash dashboard model update/read without starting its renderer.
- [x] Run latest bootstrap dry-run; no installation or wrapper mutation.
- [x] Complete full `bootstrap_latest.py` in a representative clean scripts export with the pinned `pscripts` and nested submodule commits; 62 package installs, 157 launchers, 0 failures; clean-env `agent-continuity` resolved.
- [x] Run clean-env `pip check`, all five shared import provenance checks, TermDash and Runmux CLI help, generated TermDash/Runmux `.cmd` wrapper help, and transferred-command collision check (none).
- [ ] Complete Runmux browser TestClient HTTP suite. **Blocked before request dispatch** by Windows Proactor `_fallback_socketpair`/`socket.accept`; same stall reproduced with minimal FastAPI in baseline primary environment. Runmux app construction passes; no application regression identified. Retry under a Windows environment where asyncio socket pairs work.
- [x] Compare the Runmux HTTP hang against a baseline minimal FastAPI app and capture bounded faulthandler evidence; no scripts-owned fix justified.
- [x] Make one bounded Python 3.12 SelectorEventLoop TestClient attempt using AnyIO's supported `loop_factory`; faulthandler confirms the same `_fallback_socketpair`/`socket.accept` stall before request dispatch. Stop Windows workarounds; no production event-loop changes.
- [x] Run Ubuntu package and HTTP qualification on GitHub-hosted Ubuntu 24.04 / Python 3.12.10; WSL Ubuntu and docker-desktop were not started.
- [x] Prepare an Ubuntu GitHub Actions workflow using the five committed CI-only wheel fixtures under `.github/qualified-wheelhouse/`; it checks exact hashes/metadata, runs independent package/consumer/Runmux HTTP qualification, then gates Bash bootstrap and post-bootstrap validation on pinned private `pscripts` access. Added a push trigger scoped to `feat/scripts-shared-packages-20261119` while retaining manual dispatch and `contents: read` permissions.
- [x] Verify through GitHub API that both `MaxCarlson/pscripts` and nested `MaxCarlson/aebn-vod-downloader-custom` are private. The scripts repository is public; its `GITHUB_TOKEN` cannot read either private repo.
- [x] Parse the workflow with PyYAML and verify the branch trigger, Ubuntu job, least-privilege permissions, wheel filenames, metadata, and all five SHA-256 hashes.
- [x] Push the integration branch; first hosted run `44654625788` confirmed that the scripts repository `GITHUB_TOKEN` cannot clone private `MaxCarlson/pscripts` and therefore did not reach wheel verification or tests.
- [x] Reorder qualification so independent Linux wheel/import/dependency/CLI/Runmux HTTP checks run before the private-submodule gate; retain an explicit failed workflow result if full bootstrap cannot proceed.
- [x] Second hosted run `44655256163`: wheel checks, wheel installation, `pip check`, import provenance and both CLI help checks passed; HTTP selection exposed a FastAPI 0.165.0 internal-route test incompatibility.
- [x] Update the Runmux route assertion to inspect public OpenAPI paths and rerun the previously failing test locally (1 passed).
- [x] Third hosted run `44655686691`: all five wheel hashes/metadata, isolated installation, provenance, `pip check`, TermDash/Runmux CLI help and 12 Runmux synthetic-state HTTP tests passed. The private `pscripts` clone still failed; the workflow reported the blocker explicitly.
- [x] Extend the pre-bootstrap CI path to install selected scripts consumer packages directly and run their safe regression tests without requiring `pscripts`.
- [x] Fourth hosted run `44656360846`: wheel and Runmux HTTP checks passed; consumer package installation passed; consumer tests yielded 104 passed and one failure caused by missing `pscripts/modules/setup.py`.
- [x] Exclude only `test_pscripts_duplicate_aebndl_skips_when_canonical_module_exists` before submodule checkout; keep `modules/setup_utils/tests` fully enabled after the authenticated bootstrap path.
- [x] Fifth hosted run `44656660627`: all wheel, import, `pip check`, CLI, 12 Runmux HTTP, and selected consumer checks passed; consumer suite was 104 passed / one pscripts-dependent test deselected. The explicit private-submodule gate failed as expected.
- [x] Sixth hosted run `44657040721`: independent Ubuntu checks repeated successfully (104 consumer tests passed, one pscripts-dependent test deselected; 12 Runmux HTTP tests passed); private checkout still failed.
- [x] Replace the prior PAT-based checkout with repository-specific read-only SSH deploy keys; keep scripts checkout credentials unpersisted and avoid any pull-request trigger.
- [x] Seventh hosted run `44662184899`: independent Ubuntu checks passed again (104 consumer tests passed, one pscripts-dependent test deselected; 12 Runmux HTTP tests passed); redacted preflight confirmed the `PSCRIPTS_READ_TOKEN` Actions secret is absent, so private checkout was skipped.
- [x] Eighth hosted run `44662494038` on `2676729a34a9dcf4c66fe5037c4162f1d8d641e6`: wheel/hash/metadata checks, independent package install and provenance, `pip check`, CLI checks, all 12 Runmux HTTP tests, and 104 consumer tests passed; preflight again confirmed the secret is absent, so private checkout and full bootstrap/post-bootstrap steps were skipped and the workflow failed at its explicit gate.
- [x] Verify existing GitHub CLI admin access on all three repositories and confirm both private repositories had zero existing deploy keys. Register two distinct Ed25519 deploy keys with `read_only: true`; verify their public metadata matches the generated keys.
- [x] Store the private keys as encrypted `scripts` Actions secrets `PSCRIPTS_DEPLOY_KEY` and `AEBN_DEPLOY_KEY` through standard input; verify secret names only. Do not retrieve or print values.
- [x] Verify each SSH identity can read refs only from its matching private repository; validate GitHub host-key fingerprints from HTTPS metadata and both private HTTPS-to-SSH URL rewrites.
- [x] Push the scoped SSH workflow update. Hosted Run 11 (`44673087117`) authenticated to both private repositories, verified both exact Gitlink pins, completed Bash bootstrap, and reported 62 packages, 69 script launchers, 88 console commands, and zero missing items or failures. All five distribution imports/provenance, `pip check`, TermDash/Runmux CLI checks, and the earlier 12 Runmux HTTP tests passed.
- [x] After successful hosted use, overwrite and remove the two local private-key files; preserve the rest of `.tmp_build/` and its nonsecret evidence.
- [x] Run 12 (`44674677235`): independent Ubuntu wheel/import/dependency/CLI checks, 12 Runmux HTTP tests, and 104 selected consumer tests passed. The private-checkout step stopped before SSH because the unauthenticated GitHub `/meta` request returned HTTP 403.
- [x] Scope repository `GITHUB_TOKEN` (contents: read) to the SSH host-key metadata request and send explicit GitHub API headers; retain fingerprint validation and repository-specific read-only deploy keys.
- [x] Run 13 (`44675121304`) passed: authenticated read-only checkout of both private repositories and exact Gitlink pins; full Bash bootstrap; 62 packages, 69 script launchers, and 88 console commands with zero missing; five shared imports plus `script_logging.launcher` provenance under scripts `.venv`; isolated launcher tests (3 passed); post-bootstrap setup/consumer/Runmux HTTP selection (117 passed); final `pip check` clean. The independent Runmux HTTP (12 tests) and selected consumer (104 passed, 1 pscripts-only test deselected) steps also passed.
- [x] Attempt local wheel reproduction in `.tmp_build/ci-wheel-repro-ff134131`; sandbox DNS could not resolve PyPI while fetching build-isolation requirement `wheel`. The attempt failed before package build; shared source was not modified. Since the pinned shared Git tree does not contain the qualified wheel artifacts and wheel ZIP file timestamps are not represented by Git, CI uses the exact committed artifact fixture rather than rebuilding and assuming identical bytes.
- [ ] Run Runmux TestClient request tests in a compatible Windows environment if required. Proactor and SelectorEventLoop both fail before dispatch in this host; Ubuntu successfully ran the synthetic-state HTTP-only tests.
- [x] Readiness for this checkpoint: READY FOR MERGE REVIEW. Windows HTTP setup remains host-blocked, with Ubuntu HTTP qualification passing. The separately requested `mxc-*` distribution rename is a follow-up and has not been started.

## Retirement/integration

- [x] Preserve existing retirement branch/checkpoint/quarantines and raw evidence files.
- [x] Keep all existing source ownership and data holds; do not delete or move source.
- [x] Prepare non-mutating retirement reconciliation and rollback order; integration changes must be accepted first, then selectively apply qualified module removals on a separate branch after comparing current main and quarantine manifests.
- [x] Compare integration and retirement diffs: overlap is limited to `scripts_setup/transferred_modules.py` and `scripts_setup/tests/transferred_modules_test.py`; do not merge the retirement branch wholesale.
- [ ] Apply retirement deletions or merge retirement work (explicitly out of scope for this phase).
- [ ] Review five raw JSON files for sensitivity before any future publication.
- [ ] Obtain later cleanup/integration authorization; do not merge, push, publish or retire primary-checkout source in this task.

## mxc-* distribution rename — 2026-11-20

- [x] Verify canonical mxc wheel filenames, versions, metadata, and SHA-256 values against the shared repository manifest; correct the handoff typo for the `mxc-script-logging` digest.
- [x] Replace the five old wheel fixtures in `.github/qualified-wheelhouse/`; preserve the prior wheelhouse under local `.tmp_build/` evidence.
- [x] Update scripts-owned shared dependency requirements, consumer `pyproject.toml` declarations, optional Runmux web-extra guidance, distribution checks, and workflow metadata assertions while preserving all import and CLI names.
- [x] Ensure the installer removes old shared distributions and refreshes only scripts-owned editable consumers whose installed metadata still lists old distribution names.
- [x] Run focused shared-installer/launcher/transferred-module tests (17 passed).
- [x] Run selected Windows consumer tests (79 passed); verify all five mxc imports/provenance and `pip check` in the worktree environment.
- [x] Run 36 selected TermDash and cross-platform utility tests from a temporary copy against the installed mxc wheel imports (repository source paths were not injected).
- [x] Confirm no active scripts-owned `pyproject.toml` declares an old shared distribution. Old-name references remain only in legacy-uninstall checks, historical/transferred metadata, and protected transferred applications.
- [x] Confirm prior hosted Ubuntu runner availability before qualification; private read-only deploy-key workflow remains unchanged.
- [x] Inspect the pinned private `pscripts` dependency metadata read-only and identify two old `termdash>=0.1.0` requirements in `download_scanner` and `video_tools`.
- [x] Run mxc-specific hosted Ubuntu qualification (`44682930075`): five wheel hashes/metadata, install, imports/provenance, CLI, no legacy distributions, and `pip check` passed; the Runmux synthetic-state HTTP step passed; consumer regressions passed (106 passed, 1 deselected).
- [x] Verify authenticated checkout of the exact pinned `pscripts` and nested Gitlink commits in hosted CI.
- [ ] Complete full authenticated Bash bootstrap with all legacy shared distributions absent and `pip check` clean. Hosted run `44682930075` failed on pinned `pscripts` requirements `termdash>=0.1.0` for `download_scanner` and `video_tools` (no matching distribution); bootstrap reported 62 missing packages, 155 missing launchers, and 2 failures. Blocked until a qualified `pscripts` revision stops requiring old `termdash`; scripts cannot update that repository under this assignment.
- [ ] Complete post-bootstrap generated launcher and regression checks with mxc distributions; hosted run skipped them after the bootstrap failure above.
- [ ] Complete a full representative Windows bootstrap with the renamed wheels; the previous clean-copy dry-run was 62 packages, 69 script launchers, and 87 console commands with none missing, while full old-name checkpoint counts were 62/157/88.
- [ ] Publish the five distributions through the authorized package channel before claiming ordinary public-index installation independence.
- [ ] Reconcile with current scripts `main` (`2edd3633`). At the last snapshot before this documentation update, integration was `76972eb9`, merge base was `f57b2265`, and each side had 26 unique commits; changed-path sets did not overlap. Recalculate after subsequent commits; no merge/rebase was performed under this task's boundary.
- [ ] Integration readiness: BLOCKED pending full bootstrap after the pinned `pscripts` dependency update, a full clean Windows bootstrap with mxc wheels, package publication, and reconciliation with current `main`. Keep the old retirement branch and source holds unchanged.

## Current-main reconciliation and pinned pscripts gate — 2026-11-20

- [x] Refresh and inspect `origin/main` at `719e2e70a7fb9c3b3b530fe09b013ef3a6e3f0df`; preserve integration tip `7ee3c4c18a5a798b500941b84ad8979d8b0e1cb1` and retirement checkpoint `cc3273f0e1571816de4864af17ab2e1d36bde58e`.
- [x] Create isolated worktree `.worktrees/scripts-mxc-main-reconcile-20261120` on `reconcile/scripts-mxc-main-20261120`; leave the original integration worktree, `.tmp_build/`, primary `diagnostics/`, and retirement evidence untouched.
- [x] Merge refreshed `origin/main` into the isolated branch in ordinary two-parent commit `e7e2bda57bfe322b6c915bd5a773260e75f5b18e`; no conflicts, and main's changed path set had no pre-merge overlap with the integration branch's changes.
- [x] Verify the mxc workflow, wheelhouse, shared-package ownership code, and scripts launcher adapter/generator remain identical to the original integration tip.
- [x] Recompute all five wheel hashes and inspect their wheel `METADATA`; all names, versions, Python requirements, and hashes match the committed manifest.
- [x] Verify installed mxc distribution versions and import provenance in the existing qualified scripts venv; no legacy shared distributions are installed; `python -I -m pip check` is clean.
- [x] Reconciled-tree tests: setup/shared ownership/launcher/transferred registry 17 passed; clipboard 11 passed; Runmux CLI/adapter 22 passed; Scripts Help registry/CLI 46 passed; TermDash utility/SimpleBoard/CLI 9 passed.
- [x] Audit exact pinned `pscripts` commit `70ba27dd9259eea44d3710691fb276573c26789a` metadata read-only. Only `modules/download_scanner/setup.py` and `modules/video_tools/setup.py` require old `termdash>=0.1.0`; six other packaging/setup metadata files contain no old shared distribution dependencies.
- [x] Confirm `download_scanner` uses the existing `TermDash`, `Line`, and `Stat` imports plus `TermDash.update_stat`; the unchanged Python package/API remains compatible with mxc distribution rename. `video_tools` does not import or call TermDash.
- [x] Prepare the minimal cross-repository fix: both affected requirements become `mxc-termdash>=0.10.0,<0.11`; no pscripts file was edited.
- [ ] Obtain separate authorization for pscripts ownership to apply and validate the two-line dependency fix, merge it through its normal workflow, then advance this branch's Gitlink to that verified commit.
- [ ] Run authenticated Ubuntu full Bash bootstrap, post-bootstrap launcher/setup/consumer tests, Runmux HTTP suite, and `pip check` against the fixed Gitlink; do not rerun the known-blocked full bootstrap against the unchanged pin.
- [ ] Complete a representative full Windows bootstrap using the renamed wheels.
- [ ] Publish the five mxc distributions through the authorized channel before claiming public-index installation independence.
- [ ] Reconsider merge review only after the pscripts Gitlink and full bootstrap gates above pass. Do not merge into `main` or integrate retirement deletions in this task.

## Final pscripts and full-install qualification — 2026-11-20

This section supersedes the preceding pending pscripts/full-bootstrap items. Remaining gates are public package publication and the separate pscripts/scripts merge approvals.

- [x] Create isolated pscripts fix branch `fix/mxc-termdash-deps-20261120` from exact pin `70ba27dd9259eea44d3710691fb276573c26789a`; change only `modules/download_scanner/setup.py` and `modules/video_tools/setup.py` to require `mxc-termdash>=0.10.0,<0.11`.
- [x] Run affected pscripts tests: 4 download_scanner tests and 12 video_tools tests passed; dry-run dependency resolution selected `mxc-termdash==0.10.0` without legacy `termdash`.
- [x] Commit/push pscripts fix `1640d1b80e60116aab74c9e89be67a83090a3727`; open [pscripts PR #1](https://github.com/MaxCarlson/pscripts/pull/1), currently open/unmerged. Separate authorization is required to merge it.
- [x] Advance only the reconciliation branch's pscripts Gitlink to `1640d1b80e60116aab74c9e89be67a83090a3727`; keep nested AEBN pin `af6bb8b1db14c8434c0a9da446ec49bbf067ab9b` and read-only deploy-key authentication.
- [x] Verify all five committed mxc wheel SHA-256 values against `.github/qualified-wheelhouse/SHA256SUMS.txt`; all matched.
- [x] Run hosted Ubuntu workflow [44690102265](https://github.com/MaxCarlson/scripts/actions/runs/44690102265) on scripts commit `fa8c34526a2988cbd9db5a19f3d866ce2141a046`: private pinned checkouts passed; 63 application packages installed; 69 script launchers and 93 console proxies generated; post-bootstrap inventory had zero missing items; mxc versions/import provenance and no-legacy checks passed; 3 managed-launcher tests, 119 post-bootstrap setup/consumer/Runmux tests, 12 Runmux HTTP tests, TermDash/Runmux CLI checks, and `pip check` passed.
- [x] Run full bootstrap in detached disposable Windows worktree `.worktrees/win-mxc-bootstrap-20261120`; bootstrap exit 0. Fresh post-bootstrap inventory: 63 package sources / 0 missing, 69 script launchers / 0 missing, 93 console commands / 0 missing proxies, zero failures (162 wrappers total). All five mxc distributions/imports resolved under that worktree's `.venv`, legacy distributions were absent, and `pip check` passed.
- [x] Run Windows focused tests: `scripts_setup/tests` (17 passed) and pscripts download_scanner/video_tools tests (16 passed). Direct installed `.venv\Scripts\download-scanner.exe --help` and `video-tools.exe --help` passed.
- [x] Fix the manifest gap by reading literal distribution/version/console-script fields from pscripts setup.py with AST parsing (without executing setup.py); add a regression test that failed before and passed after the fix.
- [x] Focused validation after the fix: `scripts_setup/tests` (18 passed), targeted Ruff checks (`E4,E7,E9,F`), and compileall passed. In the preserved full Windows install, regenerate the manifest from the fixed scanner; `download-scanner.cmd --help` and `video-tools.cmd --help` both returned exit 0.
- [x] Push scripts launcher-manifest fix `7cd5fdb4212398aea81a6cf2ac147ca591735751` and rerun hosted Ubuntu qualification: [run 44694590618](https://github.com/MaxCarlson/scripts/actions/runs/44694590618) passed. It authenticated both private submodules, completed the full Bash bootstrap (63 packages, 69 script launchers, 93 console commands; zero missing), passed the mxc/no-legacy/import-provenance checks and `pip check`, then passed 3 launcher tests, 120 post-bootstrap setup/consumer/Runmux tests, 12 Runmux HTTP tests, and CLI checks.
- [ ] Publish the five mxc distributions through the authorized channel before claiming ordinary package-index installation independence.
- [ ] Obtain separate approval before merging pscripts PR #1; after merge, verify the resulting main SHA and update the scripts Gitlink only if that approved SHA differs from the tested fix commit.
- [ ] Review the scripts PR targeting `main`; do not merge it in this task. Keep the original integration and retirement branches preserved.
- [ ] Preserve all 16 quarantines, seven retirement holds, five untracked raw evidence files, original integration `.tmp_build/`, and primary-checkout diagnostics.

**Current status: READY FOR MERGE REVIEW.** The scripts reconciliation branch contains current `origin/main` and is 31 commits ahead / zero behind. Full hosted Ubuntu qualification passed on the launcher-fix commit; the disposable Windows bootstrap and managed-wrapper checks passed; all five mxc wheel hashes match the committed manifest. The pscripts dependency patch remains in open PR #1 and the mxc distributions remain unpublished, so merge into scripts `main` stays gated on those cross-repository release steps. No merge or package publication is authorized in this task.

Historical checkpoint status above is superseded by the final pscripts and full-install qualification section.
