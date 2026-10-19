# Independent bridge audit - 2026-10-19

Reviewed on scripts `main`, initially clean with pscripts excluded. Starting
points were a617d29e, 002668ee, 28ef5435 and dotfiles e5f739f; source, tests,
packaged assets and current host state were checked independently. No work was
delegated. No worker/model request, host setup apply, commit, push or merge ran.

## Confirmed defects fixed in 3.0.0

| Finding | Change and regression coverage |
| --- | --- |
| Removal erased a profile before detecting missing/corrupt original backups, leaving recovery required | Validate backup fingerprints before the transaction and again before restoration; preserve installed profiles on either failure |
| Renaming onto an existing alias overwrote its model definition | Reject collisions before mutations or LM Studio calls |
| Deleting the last alias deleted the whole OpenCode file if no providers remained | Preserve unrelated settings and use the atomic config writer |
| Unknown alias deletion could unload/switch unrelated configuration; inactive alias operations changed active MCP defaults | Validate first and synchronize defaults only when the selected alias changes |
| Runtime-added bridge model keys were absent from receipt ownership and survived removal | Record newly added bridge fields with their original state; remove the orphan contribution correctly |
| Setup reset custom runtime ports; runtime ignored CODEX_HOME/XDG_CONFIG_HOME used by setup | Preserve receipt-recorded base URLs and honor the same runtime config locations |
| Codex model inventory called disabled connections enabled | Respect the enabled flag; configuration presence still does not establish service readiness |
| Shell forwarding split paths containing spaces | Preserve positional arguments without eval or unquoted expansion |
| PowerShell ignored DOTFILES_DRY_RUN=1 | Use plan for either that environment flag or WhatIf |
| Shell grep inferred local mode from any quoted local string; hooks could convert mixed client modes silently | Parse receipt modes, honor selected clients, reject ambiguous mixed modes unless explicitly overridden |
| Installer treated seeded defaults as permanently enforced fields | Preserve later user choices, release their ownership and preserve them on uninstall; bridge-owned connection drift still conflicts |
| Five Codex root settings were accidentally nested under history in the copied template | Add a corrected authored template and plan reversible migration of recognized misplaced fields; explicit root values win |
| Existing unhealthy server was treated as ready; stale server caused a kill by port without process ownership | Refuse those existing services with an actionable error; no automatic termination of unowned servers |
| Historical migration hashes did not describe all current packaged bytes | Preserve historical source/copied hashes and add normalized current packaged hashes; validate all 26 in tests and the wheel |

The two historical copy-hash content mismatches are README.md and symlinks.sh;
six other mismatches are CRLF only. Archived file contents were not changed by
the audit. Current hashes explicitly normalize CRLF to LF for portability.

The requested primary CLI is now `local-agent`; `local_agent` remains an alias.
The `local-agent-bridge` console entry point is removed. This requires version
3.0.0 under repository entry-point rules. Setup/run examples appear in help.
The repository virtualenv was reinstalled without dependency changes; its modern
entry points and repository wrapper were refreshed. The obsolete generated
wrapper was checked and removed. `python -m local_agent_bridge` retains the
legacy loader interface. The scripts-help registry was synchronized (0.5.1).

## Current host findings - read only

- Original status returned 3: approval_policy differed from its receipt
  (`on-request` now, originally seeded as `untrusted`), and two skill copies
  needed updating. This was not the zero-drift state claimed in the handoff.
- All five misplaced keys are still present in the live Codex history table:
  file_opener, hide_agent_reasoning, show_raw_agent_reasoning,
  project_doc_max_bytes and project_doc_fallback_filenames.
- With corrected code, the saved plan has no conflicts or warnings and proposes
  exactly codex.config, codex.skill and agy.skill. Its Codex preview preserves
  approval_policy = on-request, keeps only persistence under history and moves
  the five settings to the root. Status still returns 3 for pending updates.
- Existing removal preview returns 3 until the old receipt's policy ownership is
  reconciled through apply. Do not edit the receipt or revert the user's policy
  merely to force a clean status. No host plan has been applied in this audit.
- LM Studio HTTP on 1234 responds, but inventory reported no loaded models.
  OpenCode 4096 refuses connections. Worker tools are exposed in this Codex
  session; their backing runtime is not ready for delegation.
- The active alias qwen38_23GB currently describes qwen38-27b-q4km, not the Q6
  model claimed by the historical report. Do not infer quantization from aliases.
- Dotfiles main is ahead of origin by one commit and has an unrelated untracked
  .codex-remote-attachments directory; both were preserved. Claude/Cursor/central
  resource links and rollback dependencies still require the legacy llms tree.

The host plan is saved at
`modules/local_agent_bridge/.pytest_tmp_root/audit-host-plan.json` (fingerprints
and operation metadata, not configuration contents). Regenerate it if inputs
change. Applying host resources is a separate next action, not part of resource
authoring under this module's AGENTS.md.

## Validation

Commands run from the scripts root:

```powershell
.venv/Scripts/python.exe -m pytest modules/local_agent_bridge/tests -q --basetemp modules/local_agent_bridge/.pytest_tmp_root/audit-release --tb=short
.venv/Scripts/python.exe -m build --no-isolation --wheel --outdir modules/local_agent_bridge/.pytest_tmp_root/audit-dist modules/local_agent_bridge
.venv/Scripts/python.exe modules/local_agent_bridge/.pytest_tmp_root/audit_artifact_check.py
.venv/Scripts/local-agent.exe --help
.venv/Scripts/local-agent.exe run --help
.venv/Scripts/python.exe -m local_agent_bridge.commands model list
pwsh -NoProfile -File C:/Users/mcarls/src/dotfiles/setup/symlinks.ps1 -WhatIf
```

Results: **47 passed, 1 skipped** (Windows file-symlink privilege). Regression
checks reproduced failures before fixes. Final wheel entry points, all 26 current
archived hashes, JSON and skill links passed. An isolated `python -I` process
imported the extracted wheel and passed generic/local/generic/apply/status/remove.
The actual CLI help and dotfiles preview succeeded; the preview showed three
updates rather than falsely claiming everything unchanged.

Sandbox ACLs initially blocked pytest temporary-directory access and the host
receipt. Each was diagnosed once; subsequent relevant checks used the approved
outside-sandbox route. These denials do not establish a local-worker permission
problem. Pip also reported pre-existing invalid distributions in the virtualenv;
the reinstall succeeded. Setuptools emits data-directory discovery warnings, but
the final artifact's required resources and isolated lifecycle were verified.

## Remaining limits and next actions

The prior benchmark overstated its evidence. Scenario B used coordinator edits,
so actual local-worker scope, recursion and honest execution evidence remain
untested. A/C/D are historical reported observations without independently
reproduced traces here. Token percentages used a character proxy rather than
measured control trials; the old VRAM-headroom arithmetic was unsupported.
[BENCHMARK.md](BENCHMARK.md) now distinguishes those limits.

Tool permissions are not a filesystem sandbox. Custom tools, MCP capabilities,
permission prompts, follow-ups and actual worker edits require a permitted live
evaluation against the merged configuration. Runtime model operations update
multiple config files sequentially; the receipt-backed setup transaction does
not make model loading or all runtime writes one atomic operation. The audit did
not exercise live loading, unloading, cancellation or service startup/shutdown.

Next: review/apply the concrete host migration when authorized, verify clean
status, start the intended OpenCode/model runtime, and separately authorize the
worker evaluation with retained traces and an executable disposable fixture.
Keep legacy dotfiles paths. No telemetry-hook failure occurred here; the unrelated
Google IDE plugin configuration was not changed.

## Primary references

- [Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference):
  the five settings are root keys; history.persistence is nested.
- [OpenCode permissions](https://opencode.ai/docs/permissions/): per-tool rules,
  agent overrides, permissive defaults and external-directory prompts.
