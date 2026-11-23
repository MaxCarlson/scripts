# Post-P6 source retirement — shared-source proposal

Date: 2026-11-23
Branch: `retire/shared-sources-20261123`
Base: PR #22 branch `reconcile/scripts-mxc-main-20261120` at `8d4a00b38090b700c5328419b5cb06df2bde4e28`
Historical checkpoint preserved: `audit/post-p6-source-retirement-20261119` at `cc3273f0e1571816de4864af17ab2e1d36bde58e`

## Summary

This is a dependent source-retirement proposal based on scripts PR #22, which is open, unmerged, and currently reported mergeable. It stages three obsolete shared-library source trees for removal: `script_logging`, `termdash`, and `cross_platform` (140 tracked files; 20,524 lines). Their qualified `mxc-*` wheels install and import from the isolated environment after those paths are absent.

Two shared-library trees remain: `resource_metrics` is still read by Resource Coordinator H4 bundle qualification as the pinned in-repository `resource-metrics==0.2.0` snapshot; `web_ui_tools` remains on explicit ownership hold. A Git safety review rejected an attempted stage operation containing `web_ui_tools` because the prior user instruction required retaining it. No retry or indirect removal was made.

PR #27 proposes nine toolkit-owned removals separately and remains open. Together, the two proposals retire 12 of the 25 unique catalogued directories. The primary scripts checkout, PR #22 worktree, historical retirement branch, quarantine data, `.tmp_build/`, and primary diagnostics were not modified.

## Complete directory dispositions

The 23 transferred names overlap with the five shared-library names at `resource_metrics`, `script_logging`, and `web_ui_tools`, for 25 unique directories.

| Directory | Canonical owner | Source / consumer evidence | Disposition |
|---|---|---|---|
| `agent_abilities` | llm-agent-toolkit | Two tracked nested Gitlinks; complete nested ownership/content is not part of this change. | HOLD — nested Gitlinks |
| `agent_benchmark` | llm-agent-toolkit | Benchmark history/artifacts and active benchmark consumers remain protected. | HOLD — benchmark data/consumer |
| `agent_memory` | llm-agent-toolkit | Tracked SQLite index and differing default data paths require coordinated data review. | HOLD — database/data paths |
| `agent_skills` | llm-agent-toolkit | Two tracked nested Gitlinks; complete nested ownership/content is not part of this change. | HOLD — nested Gitlinks |
| `agent_sync` | llm-agent-toolkit | Canonical package paths verified; 47/49 files identical, two toolkit adaptations; legacy DB discovery stays read-only. | PR #27 removal |
| `agt` | llm-agent-toolkit | Canonical paths verified; 25/27 files identical, canonical client/probe updates retained. | PR #27 removal |
| `ai_orchestrator` | llm-agent-toolkit | Optional XInstall advisor imports its CLI manager. | HOLD — active optional consumer |
| `benchmark_core` | llm-agent-toolkit | Preserve protected benchmark consumer and its artifacts. | HOLD — benchmark consumer |
| `interactive_reports` | llm-agent-toolkit | Held Benchmark Core optionally imports HTML report generation. | HOLD — held benchmark consumer |
| `knowledge_manager` | llm-agent-toolkit | Canonical implementation is newer; legacy DB discovery remains read-only. | PR #27 removal |
| `llm-interface` | llm-agent-toolkit | Canonical API/parser and metadata adaptations verified. | PR #27 removal |
| `llm_local` | llm-agent-toolkit | Held Agent Memory optionally imports its classifier. | HOLD — held Agent Memory consumer |
| `llm_monitor` | llm-agent-toolkit | Optional imports remain in Runmux and protected benchmark/coordinator consumers. | HOLD — active optional consumers |
| `llm-models` | llm-agent-toolkit | Canonical source paths verified; package metadata differs. | PR #27 removal |
| `llm-patcher` | llm-agent-toolkit | Canonical source and entry points verified; help now references installed module command. | PR #27 removal |
| `lmstui` | llm-agent-toolkit | Canonical source paths verified; only historical documentation differs. | PR #27 removal |
| `local_agent_bridge` | llm-agent-toolkit | Canonical setup/metadata/tests include newer adaptations. | PR #27 removal |
| `orchestrator_web_viewer` | llm-agent-toolkit | Optional viewer API imports remain in TermDash/Ytaedl consumers. | HOLD — active optional consumer |
| `resource_coordinator` | llm-agent-toolkit | H4/runtime state and configuration remain protected. | HOLD — runtime state/H4 |
| `resource_metrics` | shared-python-modules | `resource_coordinator/tools/h4_qualification/bundle_builder.py` exports this source tree into the versioned H4 bundle and records `resource-metrics==0.2.0`; deleting it breaks bundles for post-retirement commits. | HOLD — active H4 source snapshot |
| `script_logging` | shared-python-modules | `mxc-script-logging==0.1.1` wheel hash and metadata verified; import uses installed distribution. Legacy `db_manager` history discovery paths remain unchanged for existing user data. | PR B removal |
| `termdash` | shared-python-modules | `mxc-termdash==0.10.0` wheel verified; CLI help and consumer tests use installed package. | PR B removal |
| `cross_platform` | shared-python-modules | `mxc-platform-utils==0.9.0` wheel verified; installed import and consumer tests pass. | PR B removal |
| `web_ui_tools` | `mxc-web-ui-tools` package is in shared-python-modules; scripts source ownership remains unresolved | Prior explicit instruction says to retain the scripts source pending ownership review; Runmux consumes the web API. The removal attempt was rejected by automatic review. | HOLD — ownership review |
| `web_ai_automator` | llm-agent-toolkit | Canonical paths verified; 13/15 files identical, two canonical API/metadata adaptations. | PR #27 removal |

Historical seven holds are all preserved: `agent_abilities`, `agent_skills`, `agent_benchmark`, `benchmark_core`, `agent_memory`, `resource_coordinator`, and `web_ui_tools`. Five additional toolkit holds remain for active consumers: `ai_orchestrator`, `interactive_reports`, `llm_local`, `llm_monitor`, and `orchestrator_web_viewer`.

## Source inventories and preservation

The pre-removal PR B inventory on the isolated branch recorded:

| Directory | Files | Bytes | Links/reparse points | Untracked/ignored/errors |
|---|---:|---:|---:|---:|
| `resource_metrics` (retained) | 9 | 31,508 | 0 | 0 |
| `script_logging` (removed) | 33 | 167,021 | 0 | 0 |
| `web_ui_tools` (retained) | 16 | 49,359 | 0 | 0 |
| `termdash` (removed) | 51 | 289,462 | 0 | 0 |
| `cross_platform` (removed) | 56 | 327,750 | 0 | 0 |

For all five inventoried directories, filesystem files matched Git-tracked files; no ignored/untracked files or reparse points were present in this isolated PR B worktree. No database, credentials, configuration, runtime state, or user artifacts were found in the three removed directories. The deletions are ordinary reversible Git changes based on PR #22; the primary checkout still retains its source directories. No telemetry database was moved or modified. `modules/db_manager/db_manager/discover.py` retains its two legacy `modules/script_logging/history*.sqlite3` discovery paths so a user-held historical database can still be found if present after integration.

## Reference audit

Active path references were reduced to intentional compatibility and protected-consumer cases:

- `resource_coordinator` H4 bundle builder/tests reference `modules/resource_metrics` as a pinned bundled source snapshot. This is the technical reason `resource_metrics` stays.
- `db_manager` retains only the legacy read-only `script_logging` database discovery paths; the runtime library import is through `mxc-script-logging`.
- `web_ui_tools` remains intact by ownership decision.
- Validation targets no longer set source `PYTHONPATH`s or editable-install any removed shared directory. RRBackup, Compresser, and MangaDL validation bootstrap from the qualified wheelhouse. Shared library test ownership moves to the canonical shared repository; scripts targets check installed metadata and import provenance.
- Both Scripts Help registries no longer advertise the retired TermDash source directory. The `termdash` console entry point remains supplied by `mxc-termdash`.
- Historical plans, handoffs, and audit notes retain their original paths as historical evidence.

## Artifact provenance

The five wheelhouse hashes were recomputed and match `.github/qualified-wheelhouse/SHA256SUMS.txt`:

| Distribution | Version | Wheel SHA-256 |
|---|---:|---|
| `mxc-resource-metrics` | 0.3.0 | `1512d9e9ab1a1d603c2dc244d1459baff1abcc738d82c4ee2a5fac835a04189a` |
| `mxc-script-logging` | 0.1.1 | `7554f367067123e23e2369b12996af2593adb4437a79667b53528d2e7bdd90b7f45` |
| `mxc-web-ui-tools` | 0.2.0 | `0171dfa984eb9d521bb340a0d0241056fdea8be685fe0c3a26bc7cc2c7f54341` |
| `mxc-termdash` | 0.10.0 | `34c69cd508753001cda19882c99aea17fcac558679c4274e6d68874065081c9b` |
| `mxc-platform-utils` | 0.9.0 | `8d64a0553776065a12d1fd3342199e9f68d13bb6a18e834a4c39b6d6c41df7dc` |

## Validation

- Pre-removal regression test was observed failing specifically because `modules/termdash` was still advertised; after registry cleanup and path removal, setup/ownership plus Scripts Help tests passed: **53 passed**.
- `Invoke-Tests.ps1 -Target @('cross-platform','script-logging')` — both installed-wheel metadata/import-provenance targets passed; both `pip check` steps passed.
- Compresser target — **61 passed**; MangaDL validation target passed.
- RRBackup full test suite with only the two external-binary availability cases deselected — **321 passed, 7 skipped, 2 deselected**. The unfiltered suite had one `rclone` subprocess failure from Windows `WinError 623` (“Illegal System DLL Relocation”). Its validation-target editable-install step also could not complete in this disposable environment: initial attempt lacked build tools/network access; after installing declared tools, Setuptools failed with `ValueError: invalid variable '<temporary UUID>'`. This is isolated to the disposable target install; the direct RRBackup suite uses worktree source and installed wheel dependencies and passes.
- Scheduler analytics/history tests with `mxc-script-logging` imported from the disposable venv — **13 passed**.
- Runmux CLI `--help` passed with `mxc-resource-metrics` source intentionally retained and shared wheels installed. The previous Ubuntu hosted run on PR #22 (`45185412715`) passed its Runmux HTTP selection before source removals. Windows HTTP remains a known host socket-pair issue; no post-removal Ubuntu run has been triggered on this dependent branch.
- Disposable environment: all five imports resolve to that environment's `site-packages`; old shared distribution names are absent; `pip check` reports no broken requirements; `termdash --help` passes.
- `bootstrap_latest.py --dry-run` completed with zero failures. In the clean disposable environment it reported 59 scripts-owned packages and 70 launchers missing (expected because this venv was provisioned only with shared wheels), and previewed `termdash` console launcher creation; no installation, submodule init, or launcher write occurred. The transferred toolkit applications did not re-enter the scripts package inventory.
- `validation-targets.json` parses as JSON; all configured working directories exist; the active manifest has no retired-source path dependency.
- Primary scripts checkout status was inspected using `git -c submodule.recurse=false status --ignore-submodules=all`; only its pre-existing untracked `diagnostics/` remains. Its shared source copies were not touched.

## PR and integration state

- PR #22 is open, unmerged, and currently reported mergeable at `8d4a00b38090b700c5328419b5cb06df2bde4e28`; its base remains `main` at `c87db5b68ae14ce5398c4a8cd16ed23289bcfacf`.
- PR #27 is open and currently reported mergeable; it proposes the nine toolkit-only removals listed above.
- PR #28 is open and currently reported mergeable; it is based on PR #22's branch. The source-removal implementation is commit `6fe4d814d3c842e8300db4fbfeb5ba39e62d38db`; a documentation-only checkpoint follows it on the PR branch.
- This PR B must target PR #22's branch and remain dependent on it. Do not merge it to main independently. PR #27 can be reviewed separately and does not depend on PyPI publication; merge only with separate approval.
- The historical retirement branch, quarantine directory/manifests, five raw JSON evidence files, primary diagnostics, PR #22 `.tmp_build/`, and all other worktrees remain preserved.

## Rollback

To restore only the three removed source paths before commit, use:

```powershell
git restore --source=8d4a00b38090b700c5328419b5cb06df2bde4e28 --staged --worktree -- modules/script_logging modules/termdash modules/cross_platform
```

To cancel the full proposal before commit, restore the exact staged and edited task paths from the PR #22 base commit on this branch. After commit, revert the PR B commit. Do not restore or alter `resource_metrics` or `web_ui_tools` as part of this rollback; they remain present. The source directories remain available in PR #22 history and canonical `shared-python-modules`.

## Next steps

1. Push the isolated PR B branch and open it against `reconcile/scripts-mxc-main-20261120`.
2. Review PR B with PR #22; do not merge either without approval.
3. Keep `resource_metrics` until H4 tooling can consume an independently pinned canonical artifact/source snapshot.
4. Keep `web_ui_tools` pending a direct ownership decision; do not attempt removal unless the user revises the explicit hold.
5. After PR #22 integration, reconcile retirement proposals on a fresh branch from updated scripts/main; source removal from the main tree requires the separately guarded integration process.
