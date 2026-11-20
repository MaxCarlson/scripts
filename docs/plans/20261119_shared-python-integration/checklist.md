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
