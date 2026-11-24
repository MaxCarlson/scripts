# Post-P6 source retirement — current-main reconciliation

Audit date: 2026-11-24

Current scripts base: `main` / `b60155b94efb54da703ed166fb9a01bb8982d1d4`

Historical checkpoint preserved: `audit/post-p6-source-retirement-20261119` / `cc3273f0e1571816de4864af17ab2e1d36bde58e`

## Decision and branch layout

The fresh audit covers the 23 directories in `scripts_setup/transferred_modules.py` and the five in `scripts_setup/shared_packages.py`; three overlap, so the unique inventory is 25 directories. Eighteen are proposed for Git-tracked source retirement across the existing toolkit/shared review units and this Monitor follow-up; seven remain protected.

Count reconciliation: PR #35 proposes 13 toolkit-source removals, PR #34 proposes four shared-source removals, and this stacked proposal adds `llm_monitor`; `25 - 13 - 4 - 1 = 7` holds. A continuation handoff referred to “13 remaining holds,” which conflicts with the verified registries and current PR diffs; no additional five candidate directories were found outside the 25-directory inventory. The per-directory table and seven remaining hold contracts below are the audited disposition.

- `retire/toolkit-sources-current-main`: 13 toolkit-owned source directories. This PR can be reviewed independently of PyPI publication.
- `retire/llm-monitor-after-harbor-20261124`: stacked on the toolkit-source proposal; removes `llm_monitor` after rechecking its canonical source, optional Runmux dependency behavior, and out-of-tree telemetry state following the Harbor transfer.
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
| `llm_monitor` | The toolkit branch contains all 176 scripts source-relative paths; six files differ for canonical packaging, TUI, and Harbor integration updates. Harbor/Monitor contract and qualification evidence are present in toolkit. | Runmux integration is optional and guarded: without the package it reports `unavailable` / `package_missing`; scripts `.venv` has no `llm-monitor` distribution. No Monitor process was found. The telemetry DB is `%LOCALAPPDATA%\\llm-monitor\\telemetry.sqlite3`, outside the source tree, and remains untouched. Historical gateway-timing evidence matches toolkit. | RETIRE — stacked toolkit-source proposal |
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

Hosted qualification had not run at the initial audit checkpoint. The later 2026-11-24 continuation dispatched and completed hosted Linux runs `45321529713` and `45321531381` on the preserved toolkit-only and combined refs; both passed the recorded post-removal checks. PR #33 run `45302927058` remains only the workflow-correction baseline and is not post-removal evidence. The new stacked Monitor-removal follow-up is not covered by those runs.

Fresh local checks on the exact refs:

- Toolkit-only ref: `python -m pytest -q -p no:cacheprovider scripts_setup/tests/transferred_modules_test.py scripts_setup/tests/shared_packages_test.py modules/scripts_help/tests/scripts_help_test.py scripts_setup/tests/gitlink_validation_test.py` — 62 passed.
- Combined ref: the same command — 65 passed.
- Combined ref with the qualified `.retirement-site` on `PYTHONPATH`: `python -m pytest -q -p no:cacheprovider modules/runmux/tests/web_cli_test.py modules/llm_monitor/tests/package_metadata_test.py modules/orchestrator_web_viewer/tests/orchestrator_viewer_package_metadata_test.py` — 13 passed.
- Refreshed on the combined ref, the isolated import-provenance probe confirmed all five imports (`resource_metrics`, `script_logging`, `web_ui_tools`, `termdash`, `cross_platform`) resolve from `.retirement-site`; all five legacy distribution names are absent. This is wheel-content/import-path evidence only.
- The five combined-ref wheel files still match `.github/qualified-wheelhouse/SHA256SUMS.txt`: `mxc_resource_metrics-0.3.0` `1512d9e9ab1a1d603c2dc244d1459baff1abcc738d82c4ee2a5fac835a04189a`; `mxc_script_logging-0.1.1` `7554f367067123e23e2369b12996af2593adb4437a79667b53528d2e7bdd90b7f45`; `mxc_web_ui_tools-0.2.0` `0171dfa984eb9d521bb340a0d0241056fdea8be685fe0c3a26bc7cc2c7f54341`; `mxc_termdash-0.10.0` `34c69cd508753001cda19882c99aea17fcac558679c4274e6d68874065081c9b`; `mxc_platform_utils-0.9.0` `8d64a0553776065a12d1fd3342199e9f68d13bb6a18e834a4c39b6d6c41df7dc`.
- The shared worktree has untracked `.retirement-site/` and `.retirement-venv/` validation artifacts. They remain untouched and are not included in either qualification ref.

Full dependency-resolved bootstrap, `pip check` against the complete installed application set, authenticated submodule checkout on the retirement refs, post-removal Ubuntu Runmux HTTP tests, and the owning agent's Windows root bootstrap remain unverified. An earlier `pip check` against the empty/incomplete retirement venv is not evidence of a qualified full dependency set. Do not characterize PR #33's earlier Ubuntu HTTP/consumer tests as post-removal qualification.

## Remaining hold contracts

These seven holds were rechecked against current consumer and packaging evidence. The following contracts are required before a hold is reconsidered; none is cleared by a successful Gitlink/ownership test alone.

| Held directory | Evidence and required follow-up |
|---|---|
| `agent_abilities` | Scripts carries nested Gitlinks `refs/agentskills` (`7f094a2f794fbf6ccf805f601cdc497110b8a8cd`) and `refs/openai-skills` (`894d404ce8df5fa06ffa4ae2cb7352e06f8b2abc`); canonical toolkit packages do not carry those Gitlinks. Both commits are recoverable from their upstream repositories, but ownership, required content, and fresh-checkout initialization must be assigned before removal. Do not move or delete either nested repository here. |
| `agent_skills` | Same two nested Gitlinks and recovery requirement as `agent_abilities`; toolkit source has no corresponding nested pointers. Decide whether references belong in toolkit metadata/docs or remain scripts-owned, and test submodule initialization from a clean clone before retirement. |
| `agent_memory` | Source defaults differ: scripts uses `~/scripts/modules/agent_memory/notes`; toolkit prefers `AGENT_MEMORY_ROOT`, preserves the legacy path only if it exists, then falls back to platform application data. The tracked SQLite index matches, but primary checkout has untracked `-wal`/`-shm` sidecars. Required: an explicit shared storage path contract, backup/checkpoint procedure, legacy-path discovery/migration plan, and validation preserving DB plus WAL/SHM. No runtime-data movement is authorized. |
| `llm_local` | The only continuing scripts consumer found is Agent Memory's optional classifier (`classify.py` catches `ImportError` and skips classification); Agent Sync is proposed for removal in PR #35. No published/installable `llm-local` distribution was verified. Required: canonical package/install contract or an explicitly accepted optional-feature fallback with tests; keep source until then. |
| `resource_coordinator` | H4 commits include `afee9c772205d4d918a129a40259ad2026820e79` and bundle work `1b71f5c4cfa0ea6c09a9d0f294400c26d7415960`. Registered worktree `.worktrees/resource-coordinator-phase-d` has modifications to four H4 handoff/status documents plus untracked `INFERENCE_DURABLE_STATE_DESIGN.md` and an inference crash-recovery plan. Required: reconcile recent H4 changes into the canonical toolkit implementation, qualify the preserved bundle/artifacts, and inventory configuration and runtime state. Do not alter active worktrees or migrate data. |
| `resource_metrics` | H4's bundle builder stages `resource-metrics==0.2.0` from `scripts/modules/resource_metrics` and exports that source with `resource_coordinator`; the shared wheel is `mxc-resource-metrics==0.3.0`. Required: update the bundle contract/artifact to the canonical distribution/source and requalify the H4 bundle before the scripts copy can be retired. |
| `orchestrator_web_viewer` | The qualified TermDash wheel's `TERMDASH_WEB_ATTACH` path imports `orchestrator_web_viewer.api.termdash.register_dashboard`. The scripts viewer metadata has an `mxc-termdash` optional extra at version 0.3.0, while canonical toolkit metadata does not yet expose the same contract. Required: coordinate canonical optional dependency/API and CLI behavior, test the feature with both packages installed, or explicitly decide to retire that integration before removing the scripts copy. |

No canonical repository was modified. PR #34 and PR #35 remain independently reviewable; the qualification refs are for evidence only. The Harbor/Monitor transfer is on toolkit branch `feat/harbor-monitor-integration-20261123` at `d18675a5139ef4686bf3574a38b7c84ec2093089`; its seven source commits and 29 paths are accounted for, and its original scripts branch/worktree remain preserved. This removes source-preservation as a reason to retain the scripts Monitor copy; it does not claim live route or benchmark qualification.

The Monitor runtime/dependency recheck found no active Monitor process, no `llm-monitor` distribution in scripts `.venv`, no hard Resource Coordinator import, and an existing Runmux `package_missing` fallback. Runmux remains optional and reports the integration unavailable when its Python environment lacks the toolkit-owned package; its README now gives the canonical installation path. The telemetry DB at `%LOCALAPPDATA%\\llm-monitor\\telemetry.sqlite3` is outside the module and untouched. All 176 tracked source-relative paths exist in the toolkit branch; nine historical gateway timing JSONL files and two Agent Benchmark experiment records compared byte-identically. Only tracked source is removed in the stacked follow-up.

Recommended sequence remains: review/qualify PR #35 and its stacked Monitor follow-up; keep PR #34 pending full wheelhouse/bootstrap and, later, clean-index dependency qualification; retain the seven other holds until their contracts are resolved. Do not merge any PR without separate approval.

## Rollback and integration sequence

Before either PR merges, restore any directory with `git restore --source=b60155b94efb54da703ed166fb9a01bb8982d1d4 -- modules/<directory>` in the corresponding worktree, then commit the restoration. After merge, use a normal revert commit; do not reset or rewrite history. No primary checkout synchronization or local data cleanup is authorized in this assignment.

1. Review the toolkit-only retirement PR first; it does not depend on package publication.
2. Keep shared-source retirement pending public clean-index qualification for all five packages (or another explicitly approved ordinary install source). Wheelhouse qualification is staged and reversible but does not establish default bootstrap availability.
3. After any merge, use the repository's approved local synchronization procedure only on a clean compatible main checkout. Preserve `diagnostics/`, `modules/ytaedl/`, Agent Memory sidecars, ignored data, and all historical evidence for separate inventory before any cleanup.
4. Re-run post-removal setup, launcher, `pip check`, consumer, and Ubuntu HTTP qualification after reconciliation; do not merge the historical 2026-11-19 retirement branch wholesale.

## Primary-checkout synchronization and local residual plan (not applied)

- The primary checkout is already at current `main` snapshot `b60155b94efb54da703ed166fb9a01bb8982d1d4`. Candidate directories remain tracked source files; their removal should arrive only through the reviewed toolkit/shared retirement proposals and this dependent Monitor follow-up. The primary checkout is unchanged.
- A read-only `git ls-files` inventory counted 1,319 tracked files across the 25 candidate trees, two untracked Agent Memory SQLite sidecars, and at least 34,657 ignored paths. The ignored count is incomplete: enumeration reported permission denied under `cross_platform/.pytest_tmp`, `knowledge_manager/tests/.pytest_tmp`, and `termdash/.pytest_cache`. Treat every ignored item and inaccessible subtree as protected; do not use a clean checkout status as evidence that those contents are disposable.
- Preserve primary untracked `diagnostics/`, untracked `modules/ytaedl/`, Agent Memory SQLite `-wal`/`-shm` runtime sidecars, ignored caches, and denied-enumeration Ytaedl pytest-temp descendants. None is part of the PR diffs.
- After separately authorized PR merges, verify exact merge SHAs and run the repository synchronization utility only against a clean compatible `main`. Because the primary checkout contains user-owned untracked state, do not run `git clean`, broad reset, or recursive cleanup. If a fast-forward could collide with any untracked path, synchronize a fresh worktree instead and leave primary untouched.
- Git removes only tracked paths from the active tree. Before any later local residual quarantine, inventory each candidate path with tracked/untracked/ignored listings, reparse-point checks, and hashes; classify runtime databases, credentials, configuration, and logs; then use the persistent quarantine process under separate authorization. Do not infer that merged PRs authorize removal of ignored/untracked data.
- Outstanding holds: `agent_abilities` and `agent_skills` (nested Gitlinks `refs/agentskills` at `7f094a2f794fbf6ccf805f601cdc497110b8a8cd` and `refs/openai-skills` at `894d404ce8df5fa06ffa4ae2cb7352e06f8b2abc`; canonical nested ownership/recoverability is unresolved); `agent_memory` (tracked index plus active WAL/SHM and divergent defaults); `llm_local` (Agent Memory's optional classification still uses it; Agent Sync also references it in current main but is included in the toolkit-only retirement proposal); `resource_coordinator` (active H4 work/config/state); `resource_metrics` (H4 bundle builder exports the scripts source and pins the old distribution); and `orchestrator_web_viewer` (documented TermDash opt-in integration).

The two replacement branches have been pushed; PR #35 is open, PR #34 is draft, and stale PRs #27/#28 are closed. No merge, package publication, local inference, primary checkout cleanup, or runtime-data removal has occurred in this checkpoint.

## Continuation checkpoint — 2026-11-24

- Ownership protection draft PR #36 is on `feat/source-ownership-protection-20261124` at `b5ef925e`; its initial GitHub ownership check passed, with the updated head check and remaining ownership/launcher audit pending. This Monitor follow-up does not modify that branch.
- Hosted Linux qualification completed on the preserved exact refs: toolkit-only run `45321529713` at `526af4aafda829013f246c6b13e0947fe62806b0`, and combined run `45321531381` at `f4a06aab3a24fe2bb672f5b63ba0b06d8e2e752a`. Both passed wheel verification, isolated imports, synthetic Runmux HTTP tests, selected consumer regressions, Gitlink validation, authenticated private checkout, clean bootstrap, launcher checks, and final pip health.
- PR #35 was verified clean against main at head `217ba2ab8c22ebb3c493bfaae13341a686e04925`. PR #34 remains draft. The existing hosted runs validate their preserved compositions, not this additional Monitor-removal follow-up.
- Seven other ownership/data/runtime holds remain open. No runtime data, primary checkout, original Harbor source feature worktree, or active H4/root-setup/dispatcher worktree was changed. Toolkit main was observed at `167a77f25e9b3d187be2fee72c95853467e1e83e` in the retirement continuation ledger.

## Continuation checkpoint — 2026-11-24 combined Monitor qualification composition

The Monitor-removal follow-up is now reconciled with the existing qualified PR #33/#34/#35 validation composition in a disposable branch. No PR branch or primary checkout was changed.

| Role | Exact revision included |
|---|---|
| Current scripts base | `main` / `b60155b94efb54da703ed166fb9a01bb8982d1d4` |
| PR #33 qualification corrections | `72dbf8370cf98ee8422dd946a84c1f177581d3d1` (workflow plus parent-tree Gitlink validator) |
| PR #35 current retirement branch | `f4f8e158554e5b84e3eb7cf45921c9d855247d1c` |
| Monitor follow-up removal | `99ef8af352eb58b5befd3011667e0dd7444bc7ee`, parent `f4f8e158554e5b84e3eb7cf45921c9d855247d1c` |
| PR #34 shared-source branch | `f7b119a0b37024624ed6299c0247c213ff93a1e7` |
| Final qualification composition | `d21a159327dea15b6032c61bad7e11f36ad6f1f7` (merge parents `7d50c6b324801fe6ab7fbf03e31015997d1cd60e` and `f4a06aab3a24fe2bb672f5b63ba0b06d8e2e752a`) |

The final composition has `b60155b94efb54da703ed166fb9a01bb8982d1d4` as its merge base with main, and ancestry checks confirm it contains PR #33 `72dbf83`, PR #35 `f4f8e15`, Monitor follow-up `99ef8af`, PR #34 `f7b119a`, and the earlier combined qualification ref `f4a06aa`. The PR #33 workflow blob is present at `11191e541f9b4aea5df828b814f3dce2ccdf89db`. The qualification workflow's push trigger is limited to the two original migration branches; this qualification ref requires an authorized manual dispatch.

### Reconciliation details

PR #34's prior overlap with the Monitor deletion was resolved without restoring the module: `modules/llm_monitor/pyproject.toml` and `modules/llm_monitor/tests/conftest.py` remain deleted, and the PR #34-only `modules/llm_monitor/tests/package_metadata_test.py` was not retained. The two retirement documents auto-merged. The Scripts Help registry and test plus transferred-module ownership test were reconciled to cover the combined removals. Merging the prior PR #33/#34/#35 qualification ref then produced a Modify/Delete conflict on the Monitor `conftest.py` and a competing Scripts Help test name/assertion; resolution kept the Monitor file deleted and retained the broader test covering both toolkit and shared source directories. The transfer ownership test retains the `llm_monitor` source-absence assertion alongside the other retirement assertions.

The resulting tree has all 18 proposed directories absent (`13` toolkit-only, `4` shared-source, and `llm_monitor`), with all seven protected directories present. `git ls-files modules/llm_monitor` returns no tracked paths. The seven holds remain `agent_abilities`, `agent_skills`, `agent_memory`, `llm_local`, `resource_coordinator`, `resource_metrics`, and `orchestrator_web_viewer`; their data, Gitlink, active H4, package, and optional-integration contracts above remain unresolved. Harbor feature branches/worktrees and live benchmark artifacts were preserved; no live benchmark or local inference was run or required for this source-copy decision.

### Fresh local validation on the combined composition

The following Windows command used the already-qualified local wheel install directory from the preserved PR #34 worktree; it did not install packages or mutate an application environment:

```powershell
$env:PYTHONPATH = "$PWD\modules\scripts_help;$PWD;C:\Users\mcarls\src\scripts\.worktrees\retire-shared-postmerge\.retirement-site"
python -m pytest -q -p no:cacheprovider `
  scripts_setup/tests/transferred_modules_test.py `
  scripts_setup/tests/shared_packages_test.py `
  scripts_setup/tests/gitlink_validation_test.py `
  modules/scripts_help/tests/scripts_help_test.py `
  modules/runmux/tests/llm_monitor_integration_test.py `
  modules/runmux/tests/web_cli_test.py `
  modules/orchestrator_web_viewer/tests/orchestrator_viewer_package_metadata_test.py
```

Result: **86 passed in 5.17s**. The selection covers ownership/bootstrap exclusion, shared distribution configuration, parent-tree Gitlink validation, both Scripts Help registries, Runmux's package-missing/integration behavior, web CLI, and viewer package metadata. The 18/7 directory-presence check also passed. This local run does not establish a full dependency-resolved bootstrap or hosted HTTP qualification.

Hosted runs `45321529713` and `45321531381` remain valid for their earlier exact refs, but neither covers `99ef8af` or final composition `d21a159`. No hosted run was produced for this delta. A fresh `gh auth status` reports the saved `MaxCarlson` CLI token is invalid and DNS resolution for `api.github.com` fails; the available GitHub connector has no workflow-dispatch operation. This is an authentication/network dispatch blocker, not a test failure. Dispatch the existing workflow manually on `qualify/retirement-monitor-pr34-pr35-20261124` after GitHub authentication and runner access are restored. Required hosted gates remain authenticated submodule checkout, full bootstrap, post-bootstrap launchers/consumers, `pip check`, and Ubuntu synthetic Runmux HTTP tests. Windows HTTP retains its already documented host socket-pair limitation; Windows root-setup qualification remains with its owning agent.

No merge, source cleanup, runtime-data movement, release, live benchmark, or local inference occurred. PR #34 and PR #35 remain unmerged; the new qualification branch is evidence only and is not a replacement PR.

### PR and branch snapshot after qualification push

A current read-only GitHub PR metadata fetch reported PR #34 open/draft/mergeable at `f7b119a0b37024624ed6299c0247c213ff93a1e7` and PR #35 open/non-draft/mergeable at `f4f8e158554e5b84e3eb7cf45921c9d855247d1c`. The Monitor follow-up commit `99ef8af` and qualification commits are not on either PR branch; no follow-up PR was opened. PR #35's current description still lists `llm_monitor` as held, which is accurate for PR #35 alone but must be coordinated with the separate Monitor follow-up before review/merge sequencing is finalized. The new evidence branch was pushed as `qualify/retirement-monitor-pr34-pr35-20261124`; it is not a retirement PR.
