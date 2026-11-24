# Post-P6 source retirement — current-main reconciliation

Audit date: 2026-11-23

Current scripts base: `main` / `b60155b94efb54da703ed166fb9a01bb8982d1d4`

Historical checkpoint preserved: `audit/post-p6-source-retirement-20261119` / `cc3273f0e1571816de4864af17ab2e1d36bde58e`

## Decision and branch layout

The fresh audit covers the 23 directories in `scripts_setup/transferred_modules.py` and the five in `scripts_setup/shared_packages.py`; three overlap, so the unique inventory is 25 directories. Seventeen are proposed for Git-tracked source retirement in two review units, and eight remain protected.

Count reconciliation: PR #35 proposes 13 toolkit-source removals and PR #34 proposes four shared-source removals; `25 - 13 - 4 = 8` holds. A continuation handoff referred to “13 remaining holds,” which conflicts with the verified registries and current PR diffs; no additional five candidate directories were found outside the 25-directory inventory. The per-directory table and eight explicit hold contracts below are the audited disposition.

- `retire/toolkit-sources-current-main`: 13 toolkit-owned source directories. This PR can be reviewed independently of PyPI publication.
- `retire/shared-sources-current-main`: four shared-library copies. It uses the qualified local wheelhouse, but a default clean scripts install still needs public package availability; do not merge this PR until clean-index qualification is possible.
- Replacement PR #35 is open against current main on `retire/toolkit-sources-current-main`.
- Replacement PR #34 is open as draft against current main on `retire/shared-sources-current-main`, at shared-branch commit `f7b119a0b37024624ed6299c0247c213ff93a1e7`.
- Both branches start at current `scripts/main`. They do not merge the historical retirement branch or alter the primary checkout.
- Old PRs #27 and #28 were closed as superseded after replacements #35 and #34 were opened. PR #28's former base was the now-merged `reconcile/scripts-mxc-main-20261120` branch; neither old PR was merged.

No files were permanently deleted or moved. Git-tracked removals exist only in isolated feature worktrees and can be restored from the base commit. The historical quarantine, seven prior holds, five raw evidence files, `.tmp_build/`, primary diagnostics, and other agents' worktrees remain intact.

## Complete 25-directory disposition

| Directory | Canonical owner and source comparison | Consumers, data, or remaining risk | Disposition |
|---|---|---|---|
| `agent_abilities` | llm-agent-toolkit source exists; scripts also carries two Gitlinks absent from the canonical tree. | `refs/agentskills` and `refs/openai-skills` are pinned nested repositories; preserve until ownership/content is coordinated. | HOLD — Gitlinks |
| `agent_benchmark` | llm-agent-toolkit has all source paths and one additional test; 250 of 254 common files match, four differ. | Benchmark/monitor optional integration is internal to the toolkit-owned benchmark group; tracked fixtures remain in canonical Git history. | RETIRE — toolkit PR |
| `agent_memory` | Toolkit source is newer in five files and has an additional test; tracked SQLite database blob matches. | Different default storage paths; tracked index plus primary-checkout WAL/SHM sidecars may be active. No database or sidecar touched. | HOLD — data/path integrity |
| `agent_skills` | Toolkit source exists; scripts also carries the two nested Gitlinks absent from canonical toolkit. | Preserve both pinned repositories pending ownership review. | HOLD — Gitlinks |
| `agent_sync` | 49 source paths; 47 match and two are toolkit adaptations. | Legacy database discovery remains read-only in `db_manager`; no database moved. | RETIRE — toolkit PR |
| `agt` | 27 paths; 25 match and two are newer in toolkit. | No scripts runtime consumer found. | RETIRE — toolkit PR |
| `ai_orchestrator` | Toolkit has the source; scripts' only direct consumer is XInstall's optional advisor. | XInstall catches the missing optional import and returns no recommendation; fallback smoke passed. | RETIRE — toolkit PR |
| `benchmark_core` | 35 paths match toolkit. | Remaining consumers are the toolkit-owned `agent_benchmark` and `interactive_reports` group, retired together. | RETIRE — toolkit PR |
| `interactive_reports` | 14 paths match toolkit. | Only active Python consumer found is the toolkit-owned Benchmark Core group. | RETIRE — toolkit PR |
| `knowledge_manager` | Canonical toolkit contains all common source paths plus a newer test and newer implementation/metadata/docs. | Legacy SQLite discovery remains read-only; no database moved. | RETIRE — toolkit PR |
| `llm-interface` | Canonical toolkit carries the API-parser/module and packaging adaptations. | No remaining scripts source consumer found. | RETIRE — toolkit PR |
| `llm_local` | Six paths match toolkit. | Agent Memory's classifier optionally imports `llm_local`; the Agent Sync source is included in PR #35 and is no longer a continuing consumer after that proposal. No independently installable `llm-local` distribution contract was verified. | HOLD — optional consumer/package contract |
| `llm_monitor` | Toolkit source exists; packaging and TUI tests have canonical updates. | Scripts Runmux and Resource Coordinator use optional APIs; scripts copy remains until a dependency contract is coordinated. Its scripts optional extras now use `mxc-*` ranges. | HOLD — active consumers |
| `llm-models` | Five paths; implementation matches and packaging metadata is toolkit-specific. | No scripts source consumer found. | RETIRE — toolkit PR |
| `llm-patcher` | Canonical toolkit has all source files plus a newer import test; entry points differ intentionally. | Scripts Help no longer depends on the source file path. | RETIRE — toolkit PR |
| `lmstui` | 31 paths; one README differs, executable source matches. | No scripts source consumer found. | RETIRE — toolkit PR |
| `local_agent_bridge` | Toolkit has all common paths plus three source/test additions and newer setup/metadata. | Scripts Help source-path entry removed; no remaining runtime consumer found. | RETIRE — toolkit PR |
| `orchestrator_web_viewer` | Toolkit has all common paths and three additional canonical files. | TermDash documents `TERMDASH_WEB_ATTACH` and imports `orchestrator_web_viewer.api.termdash` when enabled. Removing this scripts copy would silently disable that optional integration for scripts users. | HOLD — TermDash integration contract |
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
- `orchestrator_web_viewer` remains held even though its canonical source is in the toolkit: the canonical `mxc-termdash` wheel explicitly supports opt-in attachment through `TERMDASH_WEB_ATTACH` and imports `orchestrator_web_viewer.api.termdash.register_dashboard`. The viewer source is not removed by PR #34. A future coordinated contract must preserve or deliberately retire that behavior before the scripts copy is removed.
- `web_ui_tools` ownership was re-evaluated: canonical ownership is the shared package, and direct scripts consumers declare/use the installed namespaced dependency.
- `llm_monitor/pyproject.toml` on the shared branch had legacy optional requirement names. They were corrected to `mxc-web-ui-tools>=0.2.0,<0.3` and `mxc-resource-metrics>=0.3.0,<0.4`; package version is bumped to `0.9.0` per repository metadata-change policy. Import names and APIs are unchanged.
- The retained `orchestrator_web_viewer` copy had an optional extra pinned to legacy `termdash>=0.3.0`. Its scripts-side metadata now uses `mxc-termdash>=0.10.0,<0.11`, retains the Windows `windows-curses` extra used by canonical toolkit metadata, and bumps the local compatibility package to `0.3.0`; a focused metadata test covers this contract. The directory itself remains present because TermDash's documented opt-in attachment still imports it.
- `validation-targets.json` now installs TermDash, script logging, and platform utilities from the qualified wheelhouse and removes source paths; current-main targets, including MangaDL, were preserved.
- The current-main `procparsers` package-layout repair and MangaDL/media migration were present in the b601 base and are unchanged in both retirement worktrees (`git diff b601... -- modules/procparsers modules/mangadl` is empty). The recent cross-platform storage-media implementation remains in `mxc-platform-utils`; its source file and qualified installed wheel copy have identical SHA-256 `2395da6af28acc1fb0dfa17e09a1e016a497f4dff815d46205968c4f30db631c`.
- Primary checkout is still at `b60155b94efb54da703ed166fb9a01bb8982d1d4` with tracked state unchanged. `diagnostics/` and `modules/ytaedl/` are untracked; Agent Memory SQLite `-wal` and `-shm` sidecars are untracked runtime state, with ignored test/cache data also present. They were not staged, moved, or removed. Some nested Ytaedl pytest-temp paths deny enumeration, so no claim is made about their contents.

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

## Remaining hold contracts

These eight holds were rechecked against current consumer and packaging evidence. The following contracts are required before a hold is reconsidered; none is cleared by a successful Gitlink/ownership test alone.

| Held directory | Evidence and required follow-up |
|---|---|
| `agent_abilities` | Scripts carries nested Gitlinks `refs/agentskills` (`7f094a2f794fbf6ccf805f601cdc497110b8a8cd`) and `refs/openai-skills` (`894d404ce8df5fa06ffa4ae2cb7352e06f8b2abc`); canonical toolkit packages do not carry those Gitlinks. Both commits are recoverable from their upstream repositories, but ownership, required content, and fresh-checkout initialization must be assigned before removal. Do not move or delete either nested repository here. |
| `agent_skills` | Same two nested Gitlinks and recovery requirement as `agent_abilities`; toolkit source has no corresponding nested pointers. Decide whether references belong in toolkit metadata/docs or remain scripts-owned, and test submodule initialization from a clean clone before retirement. |
| `agent_memory` | Source defaults differ: scripts uses `~/scripts/modules/agent_memory/notes`; toolkit prefers `AGENT_MEMORY_ROOT`, preserves the legacy path only if it exists, then falls back to platform application data. The tracked SQLite index matches, but primary checkout has untracked `-wal`/`-shm` sidecars. Required: an explicit shared storage path contract, backup/checkpoint procedure, legacy-path discovery/migration plan, and validation preserving DB plus WAL/SHM. No runtime-data movement is authorized. |
| `llm_local` | The only continuing scripts consumer found is Agent Memory's optional classifier (`classify.py` catches `ImportError` and skips classification); Agent Sync is proposed for removal in PR #35. No published/installable `llm-local` distribution was verified. Required: canonical package/install contract or an explicitly accepted optional-feature fallback with tests; keep source until then. |
| `llm_monitor` | Runmux dynamically imports Monitor APIs and Resource Coordinator uses Monitor APIs/state. Toolkit source exists, but no independently installable application distribution/API contract was verified. Required: canonical package or coordinated optional integration contract, versioned API compatibility tests, and explicit external state location/retention behavior before removing the scripts copy. |
| `resource_coordinator` | H4 commits include `afee9c772205d4d918a129a40259ad2026820e79` and bundle work `1b71f5c4cfa0ea6c09a9d0f294400c26d7415960`. Registered worktree `.worktrees/resource-coordinator-phase-d` has modifications to four H4 handoff/status documents plus untracked `INFERENCE_DURABLE_STATE_DESIGN.md` and an inference crash-recovery plan. Required: reconcile recent H4 changes into the canonical toolkit implementation, qualify the preserved bundle/artifacts, and inventory configuration and runtime state. Do not alter active worktrees or migrate data. |
| `resource_metrics` | H4's bundle builder stages `resource-metrics==0.2.0` from `scripts/modules/resource_metrics` and exports that source with `resource_coordinator`; the shared wheel is `mxc-resource-metrics==0.3.0`. Required: update the bundle contract/artifact to the canonical distribution/source and requalify the H4 bundle before the scripts copy can be retired. |
| `orchestrator_web_viewer` | The qualified TermDash wheel's `TERMDASH_WEB_ATTACH` path imports `orchestrator_web_viewer.api.termdash.register_dashboard`. The scripts viewer metadata has an `mxc-termdash` optional extra at version 0.3.0, while canonical toolkit metadata does not yet expose the same contract. Required: coordinate canonical optional dependency/API and CLI behavior, test the feature with both packages installed, or explicitly decide to retire that integration before removing the scripts copy. |

No canonical repository was modified. PR #34 and PR #35 remain independently reviewable; the qualification refs are for evidence only. Recommended sequence remains: review/qualify PR #35; keep PR #34 pending full wheelhouse/bootstrap and, later, clean-index dependency qualification; retain all eight holds until their contracts are resolved. Do not merge either PR without separate approval.

## Rollback and integration sequence

Before either PR merges, restore any directory with `git restore --source=b60155b94efb54da703ed166fb9a01bb8982d1d4 -- modules/<directory>` in the corresponding worktree, then commit the restoration. After merge, use a normal revert commit; do not reset or rewrite history. No primary checkout synchronization or local data cleanup is authorized in this assignment.

1. Review the toolkit-only retirement PR first; it does not depend on package publication.
2. Keep shared-source retirement pending public clean-index qualification for all five packages (or another explicitly approved ordinary install source). Wheelhouse qualification is staged and reversible but does not establish default bootstrap availability.
3. After any merge, use the repository's approved local synchronization procedure only on a clean compatible main checkout. Preserve `diagnostics/`, `modules/ytaedl/`, Agent Memory sidecars, ignored data, and all historical evidence for separate inventory before any cleanup.
4. Re-run post-removal setup, launcher, `pip check`, consumer, and Ubuntu HTTP qualification after reconciliation; do not merge the historical 2026-11-19 retirement branch wholesale.

## Primary-checkout synchronization and local residual plan (not applied)

- The primary checkout is already at current `main` snapshot `b60155b94efb54da703ed166fb9a01bb8982d1d4`. Candidate directories remain tracked source files; their removal should arrive only by reviewing and later merging the two replacement PRs.
- A read-only `git ls-files` inventory counted 1,319 tracked files across the 25 candidate trees, two untracked Agent Memory SQLite sidecars, and at least 34,657 ignored paths. The ignored count is incomplete: enumeration reported permission denied under `cross_platform/.pytest_tmp`, `knowledge_manager/tests/.pytest_tmp`, and `termdash/.pytest_cache`. Treat every ignored item and inaccessible subtree as protected; do not use a clean checkout status as evidence that those contents are disposable.
- Preserve primary untracked `diagnostics/`, untracked `modules/ytaedl/`, Agent Memory SQLite `-wal`/`-shm` runtime sidecars, ignored caches, and denied-enumeration Ytaedl pytest-temp descendants. None is part of the PR diffs.
- After separately authorized PR merges, verify exact merge SHAs and run the repository synchronization utility only against a clean compatible `main`. Because the primary checkout contains user-owned untracked state, do not run `git clean`, broad reset, or recursive cleanup. If a fast-forward could collide with any untracked path, synchronize a fresh worktree instead and leave primary untouched.
- Git removes only tracked paths from the active tree. Before any later local residual quarantine, inventory each candidate path with tracked/untracked/ignored listings, reparse-point checks, and hashes; classify runtime databases, credentials, configuration, and logs; then use the persistent quarantine process under separate authorization. Do not infer that merged PRs authorize removal of ignored/untracked data.
- Outstanding holds: `agent_abilities` and `agent_skills` (nested Gitlinks `refs/agentskills` at `7f094a2f794fbf6ccf805f601cdc497110b8a8cd` and `refs/openai-skills` at `894d404ce8df5fa06ffa4ae2cb7352e06f8b2abc`; canonical nested ownership/recoverability is unresolved); `agent_memory` (tracked index plus active WAL/SHM and divergent defaults); `llm_local` (Agent Memory's optional classification still uses it; Agent Sync also references it in current main but is included in the toolkit-only retirement proposal); `llm_monitor` (Runmux has direct optional runtime imports and monitor state); `resource_coordinator` (active H4 work/config/state); `resource_metrics` (H4 bundle builder exports the scripts source and pins the old distribution); and `orchestrator_web_viewer` (documented TermDash opt-in integration).

The two replacement branches have been pushed; PR #35 is open, PR #34 is draft, and stale PRs #27/#28 are closed. No merge, package publication, local inference, primary checkout cleanup, or runtime-data removal has occurred in this checkpoint.

## Continuation checkpoint — 2026-11-24

- Ownership protection draft PR #36 uses branch `feat/source-ownership-protection-20261124`, commit `80f4c23e`; its GitHub ownership check passed. It remains a draft pending review and the remaining ownership/launcher audit.
- GitHub authentication recovered. Hosted Linux qualification was dispatched on the preserved exact refs: toolkit-only run 45321529713 at `526af4aafda829013f246c6b13e0947fe62806b0`, and combined run 45321531381 at `f4a06aab3a24fe2bb672f5b63ba0b06d8e2e752a`. Both were in progress when recorded; no bootstrap or post-removal HTTP result is claimed yet.
- PR #33 head `72dbf8370cf98ee8422dd946a84c1f177581d3d1`, PR #34 head `f7b119a0b37024624ed6299c0247c213ff93a1e7`, and PR #35 pre-ledger head `56db781dc9de6f248d87682457609b7836457a72` were verified open. The qualification refs remain the existing tested compositions; this ledger-only change does not alter them.
- All eight holds remain open. No runtime data, primary checkout, or active H4, root-setup, or dispatcher worktree was changed. Toolkit main was observed at `167a77f25e9b3d187be2fee72c95853467e1e83e`; canonical viewer metadata declares the `mxc-termdash` extra, but installed integration has not yet been qualified.
