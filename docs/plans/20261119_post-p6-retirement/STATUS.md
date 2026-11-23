# Post-P6 source retirement — fresh reconciliation

Date: 2026-11-23
Branch: `retire/toolkit-sources-20261123`
Base: scripts `main` at `c87db5b68ae14ce5398c4a8cd16ed23289bcfacf`
Reconciled with current scripts `main` at `7b9f596ac1abebd5be8395962bfb8124379b082e`; that advance changed only Runmux chart rendering and its JavaScript test, both retained unchanged.
Historical checkpoint: `audit/post-p6-source-retirement-20261119` at `cc3273f0e1571816de4864af17ab2e1d36bde58e`

## Summary

This branch is a fresh retirement proposal from current `scripts/main`. It does not merge or alter the historical retirement branch, its 16 verified quarantines, its seven raw ownership/data holds, its five untracked evidence JSON files, or the preserved quarantine archive. It removes nine toolkit-only duplicate source trees from this branch after confirming their canonical toolkit paths and current installation exclusions. Four additional candidates were retained after direct optional-consumer references were confirmed. The primary checkout remains unchanged.

PR #22 remains the shared-library integration prerequisite. It is open and unmerged at `8d4a00b38090b700c5328419b5cb06df2bde4e28`, base `main` at `c87db5b68ae14ce5398c4a8cd16ed23289bcfacf`. Its hosted Ubuntu qualification run `45185412715` passed. Shared-library retirement is proposed separately on a branch based on PR #22, not included here.

## Candidate dispositions

The source catalogs contain 23 toolkit-transferred names and five shared-package names. Their overlap is `resource_metrics`, `script_logging`, and `web_ui_tools`, yielding 25 unique directories.

| Directory | Canonical owner | Current source comparison / dependency | Disposition |
|---|---|---|---|
| `agent_abilities` | llm-agent-toolkit | Canonical package exists; two tracked Gitlinks reference nested repositories whose complete contents/ownership are not retired here. | HOLD — nested Gitlinks |
| `agent_benchmark` | llm-agent-toolkit | Canonical package exists; preserve benchmark history, artifacts, and the prior explicit ownership/data hold. | HOLD — benchmark data/consumer |
| `agent_memory` | llm-agent-toolkit | Canonical package exists; tracked SQLite index and differing default data paths require separate data migration decision. | HOLD — database/data paths |
| `agent_skills` | llm-agent-toolkit | Canonical package exists; two tracked Gitlinks reference nested repositories whose complete contents/ownership are not retired here. | HOLD — nested Gitlinks |
| `agent_sync` | llm-agent-toolkit | 49 files; all source paths exist canonically; 47 identical and two toolkit adaptations (`adapters/local.py`, `config.py`). Its database discovery entry is retained read-only for legacy data. | RETIRED in this branch |
| `agt` | llm-agent-toolkit | 27 files; all source paths exist canonically; 25 identical and two canonical updates (`client.py`, `probe_webapi.py`). | RETIRED in this branch |
| `ai_orchestrator` | llm-agent-toolkit | 11 files; all source paths exist canonically; only packaging metadata differs. `modules/xinstall/advisor.py` imports its optional CLI manager and uses it when available. | HOLD — optional XInstall advisor |
| `benchmark_core` | llm-agent-toolkit | Canonical package exists; preserve prior benchmark dependency/data hold pending coordinated consumer disposition. | HOLD — benchmark consumer |
| `interactive_reports` | llm-agent-toolkit | 14 files; source tree identical to canonical toolkit tree. Held `benchmark_core` imports it for optional HTML report generation. | HOLD — held benchmark consumer |
| `knowledge_manager` | llm-agent-toolkit | 71 source files are present canonically; canonical implementation/metadata/docs include newer updates and one additional test. No module-local database is moved; `db_manager` keeps its read-only legacy database discovery entry. | RETIRED in this branch |
| `llm-interface` | llm-agent-toolkit | 42 files; all source paths exist canonically; changes are canonical API-parser/module/metadata adaptations. | RETIRED in this branch |
| `llm_local` | llm-agent-toolkit | Six files; source tree identical to canonical toolkit tree. Held `agent_memory` optionally imports it for note classification. | HOLD — held Agent Memory consumer |
| `llm_monitor` | llm-agent-toolkit | 176 files; all source paths exist canonically; toolkit metadata and TUI test are newer. Runmux, `agent_benchmark`, `benchmark_core`, and `resource_coordinator` optionally import monitor APIs. | HOLD — active optional consumers |
| `llm-models` | llm-agent-toolkit | Five files; all source paths exist canonically; only packaging metadata differs. | RETIRED in this branch |
| `llm-patcher` | llm-agent-toolkit | 15 source files are present canonically; toolkit package entry points differ. Both help registries now use the installed module invocation, not the retired file path. | RETIRED in this branch |
| `lmstui` | llm-agent-toolkit | 31 files; all source paths exist canonically; one documentation file differs. | RETIRED in this branch |
| `local_agent_bridge` | llm-agent-toolkit | 123 files; all source paths exist canonically; toolkit setup scripts, metadata, and tests contain newer adaptations. The scripts help entry is removed. | RETIRED in this branch |
| `orchestrator_web_viewer` | llm-agent-toolkit | Canonical package exists, but active optional integrations remain in `modules/termdash` and `modules/ytaedl`. | HOLD — active consumer API |
| `resource_coordinator` | llm-agent-toolkit | Canonical package exists; preserve the explicit H4/runtime-state hold and configuration/data. | HOLD — runtime state/H4 |
| `resource_metrics` | shared-python-modules | Shared distribution is `mxc-resource-metrics`; retirement belongs to the dependent PR #22 source tree and qualified-wheel validation. | PR B candidate; not in this branch |
| `script_logging` | shared-python-modules | Shared distribution is `mxc-script-logging`; preserve existing telemetry data and retire only in dependent PR #22 after wheel/import checks. | PR B candidate; not in this branch |
| `termdash` | shared-python-modules | Shared distribution is `mxc-termdash`; consumers are covered by PR #22 and dependent wheel qualification. Optional viewer imports remain an independent viewer hold. | PR B candidate; not in this branch |
| `cross_platform` | shared-python-modules | Shared distribution is `mxc-platform-utils`; retirement belongs to PR #22 and wheel/import validation. | PR B candidate; not in this branch |
| `web_ui_tools` | shared-python-modules | Shared distribution is `mxc-web-ui-tools`; ownership is coordinated through PR #22 and the dependent shared-source retirement branch. | PR B candidate; not in this branch |
| `web_ai_automator` | llm-agent-toolkit | 15 files; all source paths exist canonically; 13 identical and two canonical API/metadata updates. No recent source activity; historical changes are preserved by Git and canonical toolkit. | RETIRED in this branch |

### Historical seven holds

`agent_abilities`, `agent_skills`, `agent_benchmark`, `benchmark_core`, `agent_memory`, and `resource_coordinator` remain held for the reasons above. The former `web_ui_tools` ownership hold is carried forward as a dependent PR #22 shared-distribution candidate; this branch does not alter it. `orchestrator_web_viewer` is an additional consumer hold newly confirmed during this reconciliation.

## Filesystem and Git evidence

Before removal, each of the nine selected directories was enumerated in this isolated worktree. The inventory matched Git's tracked file count and byte total; each had zero untracked files, zero ignored-status entries, zero symlinks/reparse points, and zero enumeration errors. No SQLite databases, credentials, user configuration, logs, or runtime state were found in the selected source trees. Primary checkout ignored state was not modified. A fresh isolated worktree from current main avoids carrying over historical quarantine artifacts.

The toolkit `main` tree contains every tracked source-relative path for all nine removed candidates. Compared source counts and path-specific differences are listed above. No module-specific source-side commit exists in the five-day window before the audit cutoff. The existing installer and launcher ownership boundary excludes transferred modules; tests continue to verify those exclusions. The two `db_manager` candidates (`modules/agent_sync/sync.db` and `modules/knowledge_manager/knowledge.db`) are retained as read-only discovery locations so legacy user databases remain discoverable if present.

Source-path consumers found and handled:

- Scripts Help and compatibility help registry no longer advertise removed modules as scripts programs. Their `llm-patcher` file-path invocation was replaced first with `python -m llm_patcher`, then the obsolete menu entry was removed from both registries.
- The `agent_sync` and `knowledge_manager` database discovery entries remain intentionally read-only and never initialize or move a database.
- XInstall's LLM advisor imports `ai_orchestrator` optionally; retained until its optional backend has a post-retirement contract.
- Agent Memory's classifier imports `llm_local` optionally; retained with the protected Agent Memory source.
- Held Benchmark Core and Agent Benchmark import `interactive_reports` and `llm_monitor` for optional report/monitor functions; Runmux also imports monitor APIs. These source trees are retained to preserve those active consumers.
- `orchestrator_web_viewer` stays present because TermDash and Ytaedl import its optional API.

Historical plan and cutover reports remain historical evidence and were not rewritten to change their as-of-date findings.

## Validation

- Pre-removal ownership test was observed failing specifically because `agent_sync` still existed; after staging removals, the new absence assertions pass.
- `python -m pytest -q scripts_setup/tests/transferred_modules_test.py modules/scripts_help/tests/scripts_help_test.py` — 49 passed with `PYTHONPATH` explicitly selecting this worktree's Scripts Help package.
- `python -m pytest -q -k 'not test_pscripts_duplicate_aebndl_skips_when_canonical_module_exists' scripts_setup/tests modules/setup_utils/tests modules/scripts_help/tests/scripts_help_test.py` with `SKIP_VENV_BOOTSTRAP=1` and worktree `PYTHONPATH` — 62 passed, one deselected. The deselected test requires the uninitialized private `pscripts` submodule; no submodule or checkout was modified.
- `python bootstrap_latest.py --dry-run` — 61 installed packages, zero missing packages, zero failures; this fresh worktree has 69 script wrappers and 90 console-command wrappers absent (159 total) and the dry-run would generate them. It also reported that the missing `pscripts` submodule would be initialized; dry-run performed no setup changes.
- Existing scripts `.venv` `python -I -m pip check` — no broken requirements found.
- A first broader setup-test attempt without `SKIP_VENV_BOOTSTRAP=1` failed because importing `setup.py` invoked `uv` and the sandbox denied writes to its default AppData cache. Re-running with the repository's supported skip-bootstrap test flag passed the applicable selection above.
- Full bootstrap, dependent wheelhouse validation, and broader post-removal consumer checks remain in progress and must pass before proposing this branch as ready for review.

## Rollback and next steps

This is staged Git removal only in the isolated branch. Restore a directory by running `git restore --source=c87db5b68ae14ce5398c4a8cd16ed23289bcfacf -- modules/<directory>` in this worktree before commit, or after commit by applying the same path restore and committing a revert. No quarantine or primary checkout content was purged. Do not merge the historical retirement branch.

Next: finish PR A validation and submit it against `main`. PR A removes nine directories and retains 11 of 20 toolkit-only source trees because of the six original holds, viewer API consumer, and four optional consumers above. Separately base PR B on PR #22, remove the five shared-package source directories, install the committed qualified `mxc-*` wheels in a clean environment, verify imports and `pip check`, and run targeted setup/Runmux/TermDash/cross-platform tests. PR B remains dependent on PR #22; package-index production readiness remains a separate gate.
