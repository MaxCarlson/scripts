# Post-P6 source retirement — current-main reconciliation

Audit date: 2026-11-23

Current scripts base: `main` / `628d9ed4aca6e0aa0884bfcf687b03740b3f6d79`

Historical checkpoint preserved: `audit/post-p6-source-retirement-20261119` / `cc3273f0e1571816de4864af17ab2e1d36bde58e`

## Decision and branch layout

The fresh audit covers the 23 directories in `scripts_setup/transferred_modules.py` and the five in `scripts_setup/shared_packages.py`; three overlap, so the unique inventory is 25 directories. Seventeen are proposed for Git-tracked source retirement in two review units, and eight remain protected.

Count reconciliation: PR #35 proposes 13 toolkit-source removals and PR #34 proposes four shared-source removals; `25 - 13 - 4 = 8` holds. A continuation handoff referred to “13 remaining holds,” which conflicts with the verified registries and current PR diffs; no additional five candidate directories were found outside the 25-directory inventory. The per-directory table and eight explicit hold contracts below are the audited disposition.

- `retire/toolkit-sources-current-main`: 13 toolkit-owned source directories. This PR can be reviewed independently of PyPI publication.
- `retire/shared-sources-current-main`: four shared-library copies. It uses the qualified local wheelhouse. A public-index check on 2026-11-25 found `mxc-resource-metrics==0.3.0`, `mxc-script-logging==0.1.1`, and `mxc-platform-utils==0.9.0`; `mxc-web-ui-tools` and `mxc-termdash` were unavailable. Keep PR #34 gated until those two ordinary dependencies and clean-index qualification are available.
- Replacement PR #35 is open against current main on `retire/toolkit-sources-current-main`.
- Replacement PR #34 is open as draft against current main on `retire/shared-sources-current-main`, at shared-branch commit `f7b119a0b37024624ed6299c0247c213ff93a1e7`.
- Both branches start at current `scripts/main`. They do not merge the historical retirement branch or alter the primary checkout.
- Old PRs #27 and #28 were closed as superseded after replacements #35 and #34 were opened. PR #28's former base was the now-merged `reconcile/scripts-mxc-main-20261120` branch; neither old PR was merged.

No files were permanently deleted or moved. Git-tracked removals exist only in isolated feature worktrees and can be restored from the base commit. The historical quarantine, seven prior holds, five raw evidence files, `.tmp_build/`, primary diagnostics, and other agents' worktrees remain intact.

## Complete 25-directory disposition

| Directory | Canonical owner and source comparison | Consumers, data, or remaining risk | Disposition |
|---|---|---|---|
| `agent_abilities` | Canonical toolkit branch `feat/agent-reference-gitlinks-20261125` registers both upstream Gitlinks at their original pins (`c4a84f9`). | Fresh worktree initialized all four references at exact commits; module tests passed. Scripts source removal is isolated at `84231074`; hosted run `45347910359` passed. | RETIRE — toolkit Gitlinks and scripts branch; ordered integration pending |
| `agent_benchmark` | llm-agent-toolkit has all source paths and one additional test; 250 of 254 common files match, four differ. | Benchmark/monitor optional integration is internal to the toolkit-owned benchmark group; tracked fixtures remain in canonical Git history. | RETIRE — toolkit PR |
| `agent_memory` | Canonical toolkit branch `feat/agent-memory-data-migration-20261125` adds explicit copy migration and marker-based discovery (`6aaa933`). A pinned VCS install with dependencies builds in a fresh disposable venv. | Disposable migration tests include SQLite WAL data; full suite 178 passed, one platform-specific symlink case skipped. Scripts branch `retire/agent-memory-20261125` removes 38 code/docs/test files while preserving the tracked empty SQLite index and all local WAL/SHM residuals. Follow-up workflow fix is `729e51d8`; hosted run `45347914913` passed at that implementation head. No live notes were moved. | RETIRE — canonical data portability and scripts branch; integration approval pending |
| `agent_skills` | Canonical toolkit branch registers `agentskills` and `openai-skills` Gitlinks at original pins (`c4a84f9`). | Fresh worktree initialized all four references at exact commits; module tests passed. Scripts source removal is isolated at `84231074`; hosted run `45347910359` passed. | RETIRE — toolkit Gitlinks and scripts branch; ordered integration pending |
| `agent_sync` | 49 source paths; 47 match and two are toolkit adaptations. | Legacy database discovery remains read-only in `db_manager`; no database moved. | RETIRE — toolkit PR |
| `agt` | 27 paths; 25 match and two are newer in toolkit. | No scripts runtime consumer found. | RETIRE — toolkit PR |
| `ai_orchestrator` | Toolkit has the source; scripts' only direct consumer is XInstall's optional advisor. | XInstall catches the missing optional import and returns no recommendation; fallback smoke passed. | RETIRE — toolkit PR |
| `benchmark_core` | 35 paths match toolkit. | Remaining consumers are the toolkit-owned `agent_benchmark` and `interactive_reports` group, retired together. | RETIRE — toolkit PR |
| `interactive_reports` | 14 paths match toolkit. | Only active Python consumer found is the toolkit-owned Benchmark Core group. | RETIRE — toolkit PR |
| `knowledge_manager` | Canonical toolkit contains all common source paths plus a newer test and newer implementation/metadata/docs. | Legacy SQLite discovery remains read-only; no database moved. | RETIRE — toolkit PR |
| `llm-interface` | Canonical toolkit carries the API-parser/module and packaging adaptations. | No remaining scripts source consumer found. | RETIRE — toolkit PR |
| `llm_local` | Canonical toolkit package builds and imports from a pinned VCS install with dependencies in a fresh disposable venv. | Agent Memory absent-package fallback and installed-package classification were tested with a mocked completion API; no inference. PR #38 source removal is hosted-qualified, but its current head includes the preceding #35 retirement history (710 changed files). Preserve it as evidence; after #35 integration, prepare and qualify an incremental replacement containing only this module's change. | HOLD — stacked PR #38 needs post-#35 reconciliation |
| `llm_monitor` | Canonical toolkit source now targets `0.9.0` and namespaced optional dependencies in PR #5. | Built wheel passed Runmux integration and synthetic web API suites (19 tests) with canonical web UI tools. Resource Coordinator H4 still stages the scripts source and is protected from this work. | HOLD — H4 bundle and ordinary install source |
| `llm-models` | Five paths; implementation matches and packaging metadata is toolkit-specific. | No scripts source consumer found. | RETIRE — toolkit PR |
| `llm-patcher` | Canonical toolkit has all source files plus a newer import test; entry points differ intentionally. | Scripts Help no longer depends on the source file path. | RETIRE — toolkit PR |
| `lmstui` | 31 paths; one README differs, executable source matches. | No scripts source consumer found. | RETIRE — toolkit PR |
| `local_agent_bridge` | Toolkit has all common paths plus three source/test additions and newer setup/metadata. | Scripts Help source-path entry removed; no remaining runtime consumer found. | RETIRE — toolkit PR |
| `orchestrator_web_viewer` | Canonical toolkit package builds and installs with dependencies from pinned VCS in a fresh disposable venv; the `termdash` extra resolves against the qualified `mxc-termdash` wheel. | Canonical viewer TermDash API tests passed (7); direct `TERMDASH_WEB_ATTACH` smoke registered a synthetic dashboard. PR #39 source removal is hosted-qualified, but its current head includes the preceding #35 retirement history (728 changed files). Preserve it as evidence; after #35 integration, prepare and qualify an incremental replacement containing only the viewer change. | HOLD — stacked PR #39 needs post-#35 reconciliation |
| `resource_coordinator` | Toolkit canonical source exists; scripts tree contains H4-specific tests/config/state. | H4 commits `afee9c772205d4d918a129a40259ad2026820e79` (2026-11-19 20:39:55 -08:00) and bundle-builder change `1b71f5c4cfa0ea6c09a9d0f294400c26d7415960` (2026-11-19 05:34:22 -08:00) are recent. Registered worktree `.worktrees/resource-coordinator-phase-d` is dirty with H4 docs plus untracked durable-state design/plans. Preserve it and its data. | HOLD — active H4 work/data |
| `resource_metrics` | Canonical shared distribution is `mxc-resource-metrics`; source imports remain available from the wheel. | Resource Coordinator H4 bundle builder exports the scripts tree as pinned `resource-metrics==0.2.0`. | HOLD — H4 snapshot contract |
| `script_logging` | Shared canonical package supplies `mxc-script-logging`; 12 of 14 compared paths match, with launcher/init adaptations. | Telemetry databases are not touched; validation target now installs the wheel. | RETIRE — shared-source PR |
| `termdash` | Shared canonical package supplies `mxc-termdash`; imports and CLI name remain unchanged. | Validation targets install the wheel. Its documented `TERMDASH_WEB_ATTACH` option imports `orchestrator_web_viewer.api.termdash.register_dashboard`; the viewer source remains held. | RETIRE — shared-source PR; viewer dependency remains |
| `cross_platform` | Shared canonical package supplies `mxc-platform-utils`; import remains `cross_platform`. | Validation target installs wheel and no longer references the retired source. | RETIRE — shared-source PR |
| `web_ai_automator` | Toolkit has all common paths; 13 of 15 match and two are canonical API/metadata updates. | No active scripts consumer found. | RETIRE — toolkit PR |
| `web_ui_tools` | Eight package paths match the shared canonical package. | Runmux and LLM Monitor continue through the optional `mxc-web-ui-tools` distribution; source-path test injection removed. | RETIRE — shared-source PR |

## Consumer and data review

- The toolkit-owned candidates are absent from scripts installation/discovery already; the historical transferred-module registry remains so scripts continues to exclude their distributions and CLI names.
- Newly cleared candidates have canonical counterparts and no remaining scripts-only runtime consumer. XInstall's `ai_orchestrator` advisor import is optional and its fallback smoke passed. The untracked primary `ytaedl` tree is not among the tracked retirement candidates and no source import into `orchestrator_web_viewer` was found.
- Canonical viewer/TermDash installation and attachment were qualified from disposable package targets. PR #39 removes the scripts duplicate; its merge remains gated on ordinary package-index availability.
- `web_ui_tools` ownership was re-evaluated: canonical ownership is the shared package, and direct scripts consumers declare/use the installed namespaced dependency.
- `llm_monitor/pyproject.toml` on the shared branch had legacy optional requirement names. They were corrected to `mxc-web-ui-tools>=0.2.0,<0.3` and `mxc-resource-metrics>=0.3.0,<0.4`; package version is bumped to `0.9.0` per repository metadata-change policy. Import names and APIs are unchanged.
- The retained `orchestrator_web_viewer` copy had an optional extra pinned to legacy `termdash>=0.3.0`. Its scripts-side metadata now uses `mxc-termdash>=0.10.0,<0.11`, retains the Windows `windows-curses` extra used by canonical toolkit metadata, and bumps the local compatibility package to `0.3.0`; a focused metadata test covers this contract. The directory itself remains present because TermDash's documented opt-in attachment still imports it.
- `validation-targets.json` now installs TermDash, script logging, and platform utilities from the qualified wheelhouse and removes source paths; current-main targets, including MangaDL, were preserved.
- The current-main `procparsers` package-layout repair and MangaDL/media migration were present in the b601 base and are unchanged in both retirement worktrees (`git diff b601... -- modules/procparsers modules/mangadl` is empty). The recent cross-platform storage-media implementation remains in `mxc-platform-utils`; its source file and qualified installed wheel copy have identical SHA-256 `2395da6af28acc1fb0dfa17e09a1e016a497f4dff815d46205968c4f30db631c`.
- At the original b601 audit snapshot, the primary checkout's tracked state was unchanged; `diagnostics/`, `modules/ytaedl/`, Agent Memory SQLite `-wal`/`-shm`, and ignored test/cache data were preserved. The current main SHA and current untracked paths are recorded in the latest continuation checkpoint. Some nested Ytaedl pytest-temp paths denied enumeration, so no claim is made about their contents.

## Verification evidence

- Fresh scripts main wheelhouse contains the five qualified wheel artifacts. All five SHA-256 values matched both `.github/qualified-wheelhouse/SHA256SUMS.txt` and the shared repository's `dist/SHA256SUMS.txt`; distribution metadata names/versions matched the approved contract.
- Offline `pip install --no-index --no-deps --target .retirement-site` installed the five wheel artifacts. Under an isolated importer, all five Python imports resolved from that target directory. TermDash `--help` passed. This validates wheel contents/import provenance, not transitive dependency resolution.
- Toolkit branch: `scripts_setup/tests/transferred_modules_test.py`, `scripts_setup/tests/shared_packages_test.py`, and Scripts Help tests — 58 passed. Expanding the source-path assertion to all 13 retired toolkit directories first exposed a stale `agent-benchmark` Help entry; that entry was removed and the expanded test passes.
- Shared branch: the same setup/ownership/Help selection plus LLM Monitor and retained-viewer optional-dependency metadata tests — 62 passed.
- Shared branch Runmux CLI/web-option selection before the final split — 65 passed. After the split, `web_cli_test.py` — 11 passed; a combined web CLI/adapter/API test selection emitted 22 passing cases but did not complete in the bounded Windows session and was stopped, consistent with the known host socket-pair limitation. No post-removal HTTP success is claimed. Prior PR #22 Ubuntu qualification had passed 12 synthetic HTTP tests and 104 selected consumer tests before source removal; this is historical evidence, not a post-removal run.
- XInstall optional advisor smoke returned no recommendation when `ai_orchestrator` was unavailable.
- `bootstrap_latest.py --dry-run` on both branches: 56 packages found, five missing, zero unreadable/unknown, 156 launchers absent in the fresh worktree, zero failures. It previewed missing private `pscripts` initialization and three shared wheel installs; no setup mutation occurred.
- The earlier scripts bootstrap audit also recorded a pre-existing missing `agent-continuity` installation. Treat that as a baseline environment issue, not a regression from these retirement branches; this dry-run did not establish a full installation either way.
- The shared branch LLM Monitor CLI selection had 23 passes and two failures in Windows-only server-descriptor owner-ACL verification. `icacls` on the disposable descriptor exposed only SYSTEM, Administrators, and OWNER RIGHTS, not the current username that the unchanged verifier requires. This runtime code is unchanged from main; Ubuntu HTTP/consumer results are the appropriate platform evidence. The package metadata test passed.
- The existing developer `.venv` is not a clean qualification environment: its `pip check` reports missing distributions (including mxc dependencies and stale legacy consumer requirements). No dependency installation was attempted after DNS/index access failed. Therefore a fresh full bootstrap and clean `pip check` remain unverified here; the dry-run and wheel-only install are not substitutes.
- The Linux workflow implementation and Windows root-setup code are owned by another agent and were not changed. This assignment attempted hosted dispatch on the two exact qualification refs, but could not authenticate/resolve GitHub; see the recorded dispatch blocker below. Windows root-setup qualification remains with its owner.

## Post-retirement qualification refs and current gates

The following disposable refs combine the exact requested revisions. They are separate from the retirement PR branches and do not change PR #33, PR #34, or PR #35:

| Qualification stage | Included revisions | Branch / commit | Local result |
|---|---|---|---|
| Toolkit-only removal | `scripts/main` `b60155b94efb54da703ed166fb9a01bb8982d1d4` + PR #33 `72dbf8370cf98ee8422dd946a84c1f177581d3d1` + PR #35 `2d12fc3266349f775a070e28f2bb877eee0ccbc1` | `qualify/retirement-toolkit-pr33-pr35-20261124` / `526af4aafda829013f246c6b13e0947fe62806b0` | Ownership, shared-package, Scripts Help, and Gitlink selection: 62 passed (refreshed locally). |
| Combined removals | Above + PR #34 `f7b119a0b37024624ed6299c0247c213ff93a1e7` with qualification-only conflict resolutions | `qualify/retirement-combined-pr33-pr34-pr35-20261124` / `f4a06aab3a24fe2bb672f5b63ba0b06d8e2e752a` | Ownership, shared-package, Scripts Help, and Gitlink selection: 65 passed; Runmux web CLI plus LLM Monitor/viewer metadata selection: 13 passed (refreshed locally). |

The combined ref resolves a test-only conflict by removing the deleted `web_ui_tools` source from the LLM Monitor test path injection and relying on the qualified installed wheel; the production implementation is unchanged. The transferred-source test recognizes both the 13 toolkit removals and the shared removals. These qualification-only edits are not on PR #34 or #35.

Hosted qualification was **not run** on either retirement ref. PR #33's successful run `45302927058` validates its workflow correction only, before source removals; it is not post-retirement evidence. A fresh `gh auth status` reports the saved GitHub token is invalid and the API host lookup fails with `no such host`. The connected GitHub tool can read PRs and workflow records but exposes no workflow-dispatch operation. Native Chrome automation timed out before opening the app. No workflow run IDs exist for the qualification refs. This is an access/dispatch blocker, not a test failure.

Fresh local checks on the exact refs:

- Toolkit-only ref: `python -m pytest -q -p no:cacheprovider scripts_setup/tests/transferred_modules_test.py scripts_setup/tests/shared_packages_test.py modules/scripts_help/tests/scripts_help_test.py scripts_setup/tests/gitlink_validation_test.py` — 62 passed.
- Combined ref: the same command — 65 passed.
- Combined ref with the qualified `.retirement-site` on `PYTHONPATH`: `python -m pytest -q -p no:cacheprovider modules/runmux/tests/web_cli_test.py modules/llm_monitor/tests/package_metadata_test.py modules/orchestrator_web_viewer/tests/orchestrator_viewer_package_metadata_test.py` — 13 passed.
- Refreshed on the combined ref, the isolated import-provenance probe confirmed all five imports (`resource_metrics`, `script_logging`, `web_ui_tools`, `termdash`, `cross_platform`) resolve from `.retirement-site`; all five legacy distribution names are absent. This is wheel-content/import-path evidence only.
- The five combined-ref wheel files still match `.github/qualified-wheelhouse/SHA256SUMS.txt`: `mxc_resource_metrics-0.3.0` `1512d9e9ab1a1d603c2dc244d1459baff1abcc738d82c4ee2a5fac835a04189a`; `mxc_script_logging-0.1.1` `7554f367067123e23e2369b12996af2593adb4437a79667b53528d2e7bdd90b7f45`; `mxc_web_ui_tools-0.2.0` `0171dfa984eb9d521bb340a0d0241056fdea8be685fe0c3a26bc7cc2c7f54341`; `mxc_termdash-0.10.0` `34c69cd508753001cda19882c99aea17fcac558679c4274e6d68874065081c9b`; `mxc_platform_utils-0.9.0` `8d64a0553776065a12d1fd3342199e9f68d13bb6a18e834a4c39b6d6c41df7dc`.
- The shared worktree has untracked `.retirement-site/` and `.retirement-venv/` validation artifacts. They remain untouched and are not included in either qualification ref.

Full dependency-resolved bootstrap, `pip check` against the complete installed application set, authenticated submodule checkout on the retirement refs, post-removal Ubuntu Runmux HTTP tests, and the owning agent's Windows root bootstrap remain unverified. An earlier `pip check` against the empty/incomplete retirement venv is not evidence of a qualified full dependency set. Do not characterize PR #33's earlier Ubuntu HTTP/consumer tests as post-removal qualification.

## Current hold and integration gates

The original eight holds now have separate canonical or scripts-side checkpoints for Gitlinks, Agent Memory, `llm_local`, and the viewer. Pinned VCS source installation is qualified without publication; hosted runs for PRs #38, #39, #41, and #42 passed. PRs #38/#39 are stacked on the prior #35 retirement history and are not merge candidates as-is; prepare incremental replacement PRs after #35 is integrated. Ordered integration remains gated on approval. The 2026-11-27 continuation below qualifies two of the three H4-coupled source retirements on isolated successors; they remain unmerged. Resource Coordinator remains gated on owner reconciliation.

| Held directory | Evidence and required follow-up |
|---|---|
| `llm_monitor` | The isolated Scripts successor `retire/llm-monitor-successor-20261127` has implementation commit `ee0bdd899fda12366e2c7b4329e48ae616c1c52d`; its bundle wheel is built from Toolkit `e10544f63ceb2f2082bc716edb4d6227087b8e03` and has SHA-256 `bc503adab4b02416f56cd1c286ab827116e2ba527afcd49790a79704c4175adb`. | Canonical launcher/bundle/import-provenance, synthetic proxy, H4 integrity, and source-ownership checks pass. Docs and Phase-D evidence remain. Branch is stacked on the Metrics successor and is unmerged; no PR was created. |
| `resource_coordinator` | Scripts `ee0bdd89` vs Toolkit `e10544f6`: 23 common files differ, including 8 runtime files, 9 tests, 2 H4 tooling files, 3 docs, and package metadata; 7 files are unique to each side. Toolkit-only runtime adds delegation and contains newer lifecycle/safety behavior. | Only the safe dependency metadata correction was made on Toolkit branch `retire/resource-coordinator-metrics-dependency-20261127`. Keep the Scripts source retirement gated on Phase-D owner reconciliation and H4 snapshot/API review. Preserve the dirty owner worktree. |
| `resource_metrics` | Scripts successor `retire/resource-metrics-successor-20261127` is pushed at `dd076e98d26fb93185ab6c4c3a6d1d36a5ff5bf3`; its in-bundle wheel is the verified published `mxc-resource-metrics==0.3.0` artifact, SHA-256 `a1e0e66c5d1b8bed507af26a906d0728b1da65fa14684be4a369da4b60ccac71`. | Bundle snapshots omit the old source; dependency and ownership metadata plus focused offline regressions pass. Branch is unmerged; H4 owner review remains required before live deployment. |

Prepared, separately pushed source-retirement batches: Agent Abilities/Skills (`retire/agent-abilities-skills-20261125`), `llm_local` (PR #38), viewer (PR #39), and Agent Memory (`retire/agent-memory-20261125`). Canonical changes are isolated on toolkit branches, including Gitlink initialization and Agent Memory data portability. Exact PyPI lookups found no `agent-memory`, `llm-local`, or `orchestrator-web-viewer` projects. A fresh disposable venv installed all three packages from pinned GitHub VCS refs with dependencies resolved; the viewer's `termdash` extra used the qualified `mxc-termdash` wheelhouse. `pip check` passed and all three import origins resolved under the venv. PRs #38, #39, #41, and #42 hosted qualifications passed. No branch was merged and no package was published.

## Rollback and integration sequence

Before PR #34 or #35 merges, restore any directory with `git restore --source=b60155b94efb54da703ed166fb9a01bb8982d1d4 -- modules/<directory>` in that PR worktree. The Agent Memory retirement branch is based on `628d9ed4aca6e0aa0884bfcf687b03740b3f6d79`; use that base for restoration there. After any merge, use a normal revert commit; do not reset or rewrite history. No primary checkout synchronization or local data cleanup is authorized in this assignment.

1. Integrate PR #33 at `72dbf8370cf98ee8422dd946a84c1f177581d3d1`, then PR #35 at `b9b32b2b0e5d679b4a78e9eef30c723d2e26a000`, preserving PR #35's qualified source tree.
2. Integrate ownership protection PR #36 at `3d971c223b952815e1911058b296b69fa4736908` before follow-up source-deletion batches.
3. Integrate toolkit PR #6 (`c4a84f94432ee266a4ae220260c8b0c100ccd34b`) before scripts PR #41 (`84231074866eab44844761c17f7ffb17d2ea9837`); integrate toolkit PR #7 (`6aaa933a39c6aacc5bbc2a393ca70865dbfb0c0e`) before scripts PR #42 (current head `9fef6fcb`; hosted source tree passed at `729e51d8`).
4. After PR #35 is integrated, prepare incremental replacements for stacked PRs #38/#39 from the new main. Preserve their qualified source removals and tests, but do not merge the current 710/728-file stacked diffs.
5. Keep shared-source retirement pending public clean-index qualification for `mxc-web-ui-tools` and `mxc-termdash`. Three of the five qualified shared distributions are now available from PyPI; wheelhouse qualification is staged and reversible but does not establish default bootstrap availability.
6. After any merge, use the repository's approved local synchronization procedure only on a clean compatible main checkout. Preserve `diagnostics/`, `modules/ytaedl/`, Agent Memory sidecars, ignored data, and all historical evidence for separate inventory before any cleanup.
7. Re-run post-removal setup, launcher, `pip check`, consumer, and Ubuntu HTTP qualification after reconciliation; do not merge the historical 2026-11-19 retirement branch wholesale.

## Primary-checkout synchronization and local residual plan (not applied)

- The primary checkout is verified at current `main` snapshot `628d9ed4aca6e0aa0884bfcf687b03740b3f6d79` and has not been modified by this assignment. The original b601 audit counted 1,319 tracked files across the 25 candidate trees and at least 34,657 ignored paths; those counts are historical, and ignored-path enumeration was incomplete because of permission-denied subtrees.
- Preserve primary untracked `diagnostics/`, untracked `modules/ytaedl/`, Agent Memory SQLite `-wal`/`-shm` runtime sidecars, ignored caches, and denied-enumeration Ytaedl pytest-temp descendants. None is part of the PR diffs.
- After separately authorized PR merges, verify exact merge SHAs and run the repository synchronization utility only against a clean compatible `main`. Because the primary checkout contains user-owned untracked state, do not run `git clean`, broad reset, or recursive cleanup. If a fast-forward could collide with any untracked path, synchronize a fresh worktree instead and leave primary untouched.
- Git removes only tracked paths from the active tree. Before any later local residual quarantine, inventory each candidate path with tracked/untracked/ignored listings, reparse-point checks, and hashes; classify runtime databases, credentials, configuration, and logs; then use the persistent quarantine process under separate authorization. Do not infer that merged PRs authorize removal of ignored/untracked data.
- Remaining source-ownership holds are `llm_monitor`, `resource_coordinator`, and `resource_metrics`. H4 canonicalization is prepared on two isolated branches: `feat/resource-metrics-canonical-bundle-20261125` at `8d98af2f731f6592668c6eaa5e89db87a91de72a` stages the qualified `mxc-resource-metrics==0.3.0` wheel and removes staged metrics source; `feat/h4-canonical-llm-monitor-20261124` at `89b71be2ec4ca0b7f7a5e04ec8c654a90037b8f5` stages `llm-monitor==0.9.0` from its pinned Toolkit commit, switches H4 proxy-chain tests to the canonical wheel, and removes the scripts Monitor path from the managed launcher. Their synthetic/bundle qualification passed; H4 owner review/integration and the remaining Windows guest gates are pending. Local ignored/untracked data remains outside source-retirement commits.

At the original audit checkpoint, PR #35 was open, PR #34 was draft, and stale PRs #27/#28 were closed. Current PR states and later retirement branches are recorded below. No merge, package publication, local inference, primary checkout cleanup, or runtime-data removal has occurred.

## Continuation checkpoint — 2026-11-25

- Current scripts main is `628d9ed4aca6e0aa0884bfcf687b03740b3f6d79`. PR #35 remains open at `b9b32b2b0e5d679b4a78e9eef30c723d2e26a000` and mergeable; PRs #33, #34, and #36 currently report unmergeable against the advanced main. No merge approval is treated as a blocker for these independent branches.
- PR #36 ownership check passed at `3d971c223b952815e1911058b296b69fa4736908`; its production CLI accepted exact deletion exceptions and rejects unauthorized source edits. This retirement branch also passed the production CLI at base `628d9ed4` / end `438bd9d5` after restoring a docs edit that crossed ownership boundaries.
- Toolkit Gitlink branch `feat/agent-reference-gitlinks-20261125` is pushed at `c4a84f9`; fresh-worktree initialization checked out all four Gitlinks at the assigned pins. Static validation passed (1); Agent Abilities tests passed (34, 1 deselected) and Agent Skills tests passed (7, 1 deselected). Scripts source retirement is pushed at `84231074`; hosted qualification `45347910359` passed.
- Toolkit Agent Memory portability branch `feat/agent-memory-data-migration-20261125` is pushed at `6aaa933`. Disposable migration/discovery and CLI tests pass; the full Agent Memory suite is 178 passed, 1 skipped, and lint passed on changed files. The scripts branch `retire/agent-memory-20261125` is pushed at `438bd9d5`; it deletes all 38 tracked implementation/docs/test files, retains the empty tracked SQLite data artifact, and preserves local WAL/SHM residuals. Transfer/launcher/setup tests pass (7); the production ownership CLI exits 0.
- PyPI has no exact `agent-memory`, `llm-local`, or `orchestrator-web-viewer` distributions. A fresh venv at `.pytest_tmp_root/ordinary-vcs-qualification-20261125` installed `agent-memory` from `6aaa933a39c6aacc5bbc2a393ca70865dbfb0c0e` and `llm-local` plus viewer from toolkit `39f8d781efe5fe7ed9accbbfe613d234fbd69160`, with dependency resolution and the viewer `termdash` extra using the qualified wheelhouse. `pip check` passed; all three import origins resolved inside the venv, including `register_dashboard`. PR #38 hosted qualification `45347357571`, PR #39 run `45348359248`, PR #41 run `45347910359`, and PR #42 run `45347914913` passed. PR #42 head `9fef6fcb` carries the implementation plus ledger-only follow-ups after its hosted run.
- Scripts hosted qualification originally failed because the workflow hardcoded an obsolete `pscripts` commit instead of reading the parent Gitlink. PR #38 adds the Gitlink-derived check (`ec123539`); PR #39/#41/#42 carry the same correction (`1abb7675`, `84231074`, `729e51d8`). The earlier pre-fix runs are not current qualification results.
- Toolkit PR #5 runs `45333414610`, `45334638802`, `45345602914`, and `45345628821` each failed all eight jobs before runner assignment; metadata has `runner_id=0`, empty step arrays, and the log endpoint returns 404. Local Runmux API tests remain 19 passed. Do not retry until hosted diagnostics become available.
- Public package-index checks found `mxc-resource-metrics==0.3.0`, `mxc-script-logging==0.1.1`, and `mxc-platform-utils==0.9.0`; `mxc-web-ui-tools` and `mxc-termdash` were not available. PR #34 remains gated on the latter ordinary install sources and clean-index qualification. No package publication was attempted.
- Active source holds remain `llm_monitor`, `resource_coordinator`, and `resource_metrics`. H4 canonical bundle branches `8d98af2f731f6592668c6eaa5e89db87a91de72a` (Metrics) and `89b71be2ec4ca0b7f7a5e04ec8c654a90037b8f5` (Monitor, stacked after Metrics) are based on committed H4 `ea6ad23fe705bc828f06a99ccf1ab3477e621d49`. Focused H4 offline qualification passed 77 tests, skipped 1, and deselected 4 host-dependent checks. The H4 owner must review/integrate these branches before corresponding source-retirement batches. The dirty Phase-D worktree remains unchanged and protected.
- The primary checkout remains `main` at `628d9ed4aca6e0aa0884bfcf687b03740b3f6d79`, with `diagnostics/`, `modules/ytaedl/`, and Agent Memory `-wal`/`-shm` sidecars untracked. They were preserved.
- No merge, package publication, primary checkout mutation, live data migration, or local residual cleanup occurred.


## 2026-11-27 published-package and branch qualification checkpoint

Current remote main refs were refreshed and verified: Scripts `93c0f29788fe57e56df124f699ebbd4116a7b6a8`; Toolkit `c002929e8a83de10d14ba30da83562b5bd0ec1f7`. The PR #34 and PR #39 branches were replayed onto Scripts current main; PR #39 is stacked on PR #34 so it also removes the Viewer metadata test introduced under the retired directory. Toolkit PR #5 was replayed onto Toolkit current main. No PR was merged.

All five requested PyPI projects now publish the exact requested versions. Downloaded wheel and sdist SHA256 values matched their PyPI JSON release-file records, and artifact metadata matched each project name and version:

| Release | Wheel SHA256 | Sdist SHA256 |
|---|---|---|
| `mxc-script-logging==0.1.1` | `a9f0f7fe0f806637d3000374b163bf77ccefa4e00d1241e769387063656e4d92` | `bb409a46954203b7645a718d158f5428c4bd32104b6877bb1058ccc7fd7ec4e7` |
| `mxc-platform-utils==0.9.0` | `24f9f70f265c9c18db31e59ecb9394b883de88fc7e7626c3713fc7d64828b6aa` | `558b2679ae07b7c811c198984fd6a7482ea845e982bdcfabd88ff3dad45a9206` |
| `mxc-resource-metrics==0.3.0` | `a1e0e66c5d1b8bed507af26a906d0728b1da65fa14684be4a369da4b60ccac71` | `f385bd1163ca23c410748fa4f320d23835393b77e69b603d6acd68be4bcd09cf` |
| `mxc-web-ui-tools==0.2.0` | `0171dfa984eb9d521bb340a0d0241056fdea8be685fe0c3a26bc7cc2c7f54341` | `060735a26e105c9eb6db41c855923f2417c3f9e676102ee6412355515fdae0db` |
| `mxc-termdash==0.10.0` | `b97f31d275c930f90f614cee05e7d8176f3068f8506835f2d9a36c653fdd0f5d` | `adb9034a33ce691dc58399cfb657e63dc8af1bf0b801d58e03574c5514884758` |

PyPI Integrity API provenance requests returned HTTP 404 for all ten files. The source contents were compared with prior qualified artifacts: all wheel entries matched; sdist file entries matched after line-ending normalization, with no source difference observed. PyPI release records establish artifact hashes and identity, but no signed build/source provenance was available, so source-to-release lineage remains unverified.

The disposable `resolved-venv` installed all five published distributions from `https://pypi.org/simple` with dependency resolution; `pip check` passed. A clean `pip install --dry-run --ignore-installed --report` resolved the combined Runmux web, Toolkit Monitor all, canonical Viewer TermDash extra, and five exact published versions from PyPI. Canonical shared imports resolved under that venv's `site-packages`; Monitor and Viewer imports resolved to Toolkit worktrees, and Runmux resolved to the disposable combined Scripts tree. `llm-monitor.exe --help`, `termdash.exe --help`, and `runmux.exe --help` succeeded.

PR #34 now uses PyPI release-file preflight and package-index installs in qualification; its validation targets no longer reference the qualification wheelhouse. The shared installer no longer falls back to local shared-package source directories when index installation fails. A synthetic regression test proves index failure is reported without a direct source install. PR #39 is stacked after #34 so the final source deletion also removes its Viewer metadata test.

ReportLab/Pillow fix `8f770444ae54bf8e9cd9d05ec5b5867b23c47099` remains separate and unmerged; no file from that commit was incorporated into the retirement branches or combined tree. Its web-docs-processor version bump to 0.4.0 and `reportlab>=4.2,<5` cap were reviewed, but that compatibility fix was not qualified as part of this retirement batch.

H4-dependent Resource Metrics and Monitor retirement remains gated on H4 owner reconciliation. H4 bundle commits `8d98af2f` and `89b71be2` remain separate. The protected Phase-D worktree was not opened or changed; Agent #1's local adoption worktree and cleanup responsibilities remain untouched. The primary checkout and unrelated dirty/untracked files were preserved. Toolkit hosted CI remains a pre-runner infrastructure failure (`runner_id=0`, no steps, log endpoint 404); no failed runs were redispatched.


## 2026-11-27 final current-main sync and pushed refs

Scripts main advanced during final qualification. The final fetched Scripts base is `a2c09bc5a666961359df8c04303105754f66486d`; Toolkit main remains `c002929e8a83de10d14ba30da83562b5bd0ec1f7`. The prior 2026-11-27 checkpoint above records the first fetch; both retirement branches were replayed again onto this later Scripts base before push.

Final pushed refs: Scripts PR #34 `df546641c3809150a203270fcdff1cd4afb4568c`; stacked Scripts PR #39 `b13f3062629439825659114d8193ce9b6571c46b`; Toolkit PR #5 `4973c76782290776e0002fead128011aad80d42b`. Final disposable integration trees were Scripts `b47b16b734a792b3d7236c87c96e1da542aa7697` and Toolkit `309c47dde51f19e0c33c53aaa994157ea053644e`. On those refs, the combined synthetic qualification passed 110 tests, the production Scripts ownership checker returned 0, and `pip check` reported no broken requirements. The exact PyPI install plan was also re-resolved from the public index; all three installed launchers and all canonical import origins were verified.

The pushed branches remain separate and draft. No PR merge, package publication, primary-checkout change, live-data migration, or protected H4/Phase-D operation occurred. Pause at the ordered approval gate: Toolkit PR #5, Scripts PR #34, then Scripts PR #39.

## 2026-11-27 Metrics, Monitor, and Coordinator continuation

The Scripts successors were based on the available `origin/main` checkpoint
`61722b3c04bc36d32e0eaa51b2a478ab155a6dea` and remain unmerged. Implementation
heads are recorded below; this status/checklist refresh is committed after the
Monitor implementation head:

- Resource Metrics: `retire/resource-metrics-successor-20261127` at
  `dd076e98d26fb93185ab6c4c3a6d1d36a5ff5bf3`. The H4 bundle embeds the
  published `mxc-resource-metrics==0.3.0` wheel
  (`a1e0e66c5d1b8bed507af26a906d0728b1da65fa14684be4a369da4b60ccac71`),
  exports only Resource Coordinator source for both snapshots, and loads the
  wheel by its verified path. Scripts consumer metadata and source ownership
  records are updated. Focused retirement/policy tests: 24 passed; H4
  compatibility/integrity/Windows harness: 38 passed; ownership CLI passed.
- LLM Monitor: `retire/llm-monitor-successor-20261127` at
  `ee0bdd899fda12366e2c7b4329e48ae616c1c52d`, stacked on Metrics. The duplicate
  package implementation, tests, and web assets are removed; README, examples,
  historical docs, and Phase-D evidence remain tracked unchanged. Its bundled
  wheel was built from Toolkit `e10544f63ceb2f2082bc716edb4d6227087b8e03`,
  SHA-256 `bc503adab4b02416f56cd1c286ab827116e2ba527afcd49790a79704c4175adb`.
  Source/registry tests: 25 passed; canonical bundle/Runmux: 2 passed;
  synthetic proxy chain: 4 passed; H4 harness: 39 passed; ownership CLI passed.
- Toolkit metadata: `retire/resource-coordinator-metrics-dependency-20261127`
  at `6b09559c287fb434ede42c4e64f5e5097c6982fd`, based on Toolkit
  `e10544f63ceb2f2082bc716edb4d6227087b8e03`. The canonical Coordinator
  dependency is bounded to `mxc-resource-metrics>=0.3.0,<0.4`; its metadata
  regression passed and a locally built wheel advertises
  `Requires-Dist: mxc-resource-metrics<0.4,>=0.3.0`.

Current Scripts-versus-Toolkit Resource Coordinator comparison at those refs:
23 common files differ and 7 files are unique to each side. Of the common
differences, 8 are runtime modules (admission/gateway, config/state, policy,
process/service lifecycle, installation), 9 are tests, 2 are H4 tools, 3 are
H4 docs/evidence, and 1 is package metadata. The Toolkit-only files include
delegation runtime and reservation tests; the Scripts-only files are the H4
bundle plans, test, and pinned wheel artifacts. The runtime differences include
newer delegation, manual-override, restart/backoff, and terminal-error
handling. Only the independent dependency metadata was reconciled; no runtime
implementation was copied across the active owner boundary.

The two Scripts branches would raise the integrated retirement count from
22/25 to 24/25 after their ordered integration (Metrics before stacked Monitor).
Resource Coordinator remains the concrete H4/Phase-D owner gate. This initial checkpoint predates the later authorized ordered integration and
local adoption. See the 2026-11-27 closeout below for final repository state.


## 2026-11-27 integration and local-adoption closeout

Ordered branch-first integrations are complete and pushed. Toolkit main is
`6b09559c287fb434ede42c4e64f5e5097c6982fd`. Scripts main integration is
`9d9a813b8b58f5f94bb4fe9ab5ea20d828a88a79`, merging Resource Metrics after
current main and Monitor after Metrics. The Monitor branch follow-up
`73a6e8255104fee0d2bfa2ae6cf36f1c89b75938` moved its 88 retained README,
documentation, examples, and evidence files verbatim to
`docs/archive/llm_monitor/`; two direct references were repaired.

The 25-directory ownership inventory now has 24 retired implementations.
`resource_coordinator` remains the sole implementation hold;
`agent_memory` retains its tracked SQLite index only. The protected
`.worktrees/resource-coordinator-phase-d` remains untouched at
`a3bbb53dd658e9a9e3413056fa3b3c3aea571259` with its pre-existing owner edits.

Before primary synchronization, both original Scripts module directories were
backed up to
`C:\Users\mcarls\src\_migration_backups\source_retirement_20261127_052030`.
The SHA-256 manifest covers 22 Resource Metrics files and 280 Monitor files;
all hashes matched. After synchronization, 13 and 103 ignored residual files
were moved into `post_sync_residuals` after matching them against the backup.
Both `scripts/modules/resource_metrics` and `scripts/modules/llm_monitor` are
physically absent.

The Scripts venv resolves `mxc-resource-metrics==0.3.0` from site-packages and
passes `pip check`; the Toolkit venv resolves editable `llm-monitor==0.9.0`
from `llm-agent-toolkit/modules/llm_monitor` and also passes `pip check`. The
managed `llm-monitor.cmd --help` and `resource-coordinator.cmd --help` both
exit successfully. No unrelated public `llm-monitor` distribution was
installed.

The previously completed combined 110-test qualification and artifact evidence
were reused. On the actual integrated tree, retirement/registry checks passed
11 tests and the focused synthetic H4 bundle/consumer recheck passed 3 tests;
source-ownership enforcement passed. Bundle wheel digests remained
`a1e0e66c5d1b8bed507af26a906d0728b1da65fa14684be4a369da4b60ccac71` for
Metrics and `bc503adab4b02416f56cd1c286ab827116e2ba527afcd49790a79704c4175adb`
for Monitor.

The remaining gate is H4 owner reconciliation before Resource Coordinator
retirement or live deployment. No additional retirement batch is started here.

## 2026-11-28 final Resource Coordinator retirement candidate

Prepared two new isolated feature branches from Scripts `7b28b81cad915982ab38961c7538ca1c2ff5f032` (which includes accepted checkpoint `a4ae995b`) and Toolkit `98cfb2a6505f15bea23128776bc889cad49b45dd`. The Scripts candidate was replayed onto the LLMD-updated main head before publication. It removes the final duplicate implementation on the Scripts branch, raising the proposed inventory from 24/25 to 25/25 once integrated. The existing Scripts primary checkout and all unrelated local changes remain untouched.

The canonical Toolkit H4 builder now requires a full immutable Toolkit revision for the current source. It continues to obtain the historical baseline only from Scripts commit `873a49382a5e03da47f793608d3519f7e69da646` and verifies the pinned `4fa9978e...` source digest. Bundle metadata records both repository identities and commits. Current source exports only Toolkit Coordinator code; historical compatibility retains the old Metrics source. The published Metrics and Toolkit Monitor wheels are included from the verified artifacts, with SHA-256 values `a1e0e66c5d1b8bed507af26a906d0728b1da65fa14684be4a369da4b60ccac71` and `bc503adab4b02416f56cd1c286ab827116e2ba527afcd49790a79704c4175adb`. Other third-party dependencies remain clearly marked partial, not a complete offline wheelhouse.

On the Scripts candidate, all tracked module documentation, plans, handoffs, and historical evidence were moved verbatim to `docs/archive/resource_coordinator/`; the former package README is preserved as `RESOURCE_COORDINATOR.md`. The duplicate package, tests, configuration, and H4 copy were removed only from the feature branch. A narrowly scoped `type: retirement` exception covers `modules/resource_coordinator`. Existing transferred-distribution and CLI mappings remain intact, and PrivExec's H4 path defaults/examples now point at the canonical Toolkit tooling.

Focused Scripts checks passed: `scripts_setup/tests/transferred_modules_test.py` and the PrivExec path assertion (8 passed), `python -m scripts_setup.source_ownership --base origin/main --end HEAD` (exit 0), and PowerShell parser validation (pass). Toolkit H4 offline/synthetic tests completed with exit 0: 69 collected, 68 passed and one Windows guest bootstrap case skipped. Temporary roots were unique and package-local. Prior 205 runtime tests from Agent #1 were reused, not repeated. No inference, live H4 deployment, merge, primary synchronization, or permanent deletion occurred.

Integration remains gated. The protected Phase-D worktree at `a3bbb53d...` is unchanged and has six uncommitted/new documentation paths: `docs/HANDOFF.md`, `docs/PHASE_D_SAFETY_REVIEW.md`, telemetry T1 `STATUS.md`, `docs/plans/HANDOFF.md`, `docs/INFERENCE_DURABLE_STATE_DESIGN.md`, and the new inference crash-recovery plan. These changes overlap the documentation subtree archived by the retirement branch and must be preserved/reconciled by their owner before integration.
