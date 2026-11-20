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
- [x] Revise workflow auth so `scripts` uses `GITHUB_TOKEN` and `PSCRIPTS_READ_TOKEN` is used only for pinned recursive checkout of private `pscripts` and its nested repository; do not persist checkout credentials.
- [x] Seventh hosted run `44662184899`: independent Ubuntu checks passed again (104 consumer tests passed, one pscripts-dependent test deselected; 12 Runmux HTTP tests passed); redacted preflight confirmed the `PSCRIPTS_READ_TOKEN` Actions secret is absent, so private checkout was skipped.
- [ ] Task owner securely provisions `PSCRIPTS_READ_TOKEN` as an Actions secret with fine-grained `Contents: Read-only` access restricted to `MaxCarlson/pscripts` and `MaxCarlson/aebn-vod-downloader-custom`, then reruns full bootstrap, generated launchers, the deferred setup test, and post-bootstrap consumers. Do not provide token values in chat.
- [x] Attempt local wheel reproduction in `.tmp_build/ci-wheel-repro-ff134131`; sandbox DNS could not resolve PyPI while fetching build-isolation requirement `wheel`. The attempt failed before package build; shared source was not modified. Since the pinned shared Git tree does not contain the qualified wheel artifacts and wheel ZIP file timestamps are not represented by Git, CI uses the exact committed artifact fixture rather than rebuilding and assuming identical bytes.
- [ ] Run Runmux TestClient request tests in a compatible Windows environment if required. Proactor and SelectorEventLoop both fail before dispatch in this host; Ubuntu successfully ran the synthetic-state HTTP-only tests.

## Retirement/integration

- [x] Preserve existing retirement branch/checkpoint/quarantines and raw evidence files.
- [x] Keep all existing source ownership and data holds; do not delete or move source.
- [x] Prepare non-mutating retirement reconciliation and rollback order; integration changes must be accepted first, then selectively apply qualified module removals on a separate branch after comparing current main and quarantine manifests.
- [x] Compare integration and retirement diffs: overlap is limited to `scripts_setup/transferred_modules.py` and `scripts_setup/tests/transferred_modules_test.py`; do not merge the retirement branch wholesale.
- [ ] Apply retirement deletions or merge retirement work (explicitly out of scope for this phase).
- [ ] Review five raw JSON files for sensitivity before any future publication.
- [ ] Obtain later cleanup/integration authorization; do not merge, push, publish or retire primary-checkout source in this task.
