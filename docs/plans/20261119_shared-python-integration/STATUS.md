# Scripts Shared-Package Integration Status

Updated: 2026-11-19

## Checkpoint

- Integration worktree: `.worktrees/scripts-shared-package-integration-20261119`
- Branch: `feat/scripts-shared-packages-20261119`
- Base: `f57b22652dfc8cd67823a2a0d1d2792b3f09a320`
- Local checkpoint before this qualification: `908bec8d` (`docs(scripts): record shared cutover preflight`).
- All implementation changes are scoped to the scripts integration branch.
- Primary `scripts/main` is unchanged. Retirement branch `audit/post-p6-source-retirement-20261119` remains at the supplied `cc3273f0` checkpoint; its quarantines, manifests, five raw JSON evidence files, and seven holds were not modified.
- No source directories were removed, no quarantine was changed, and nothing was pushed or merged.

## Artifact qualification

All five wheels matched the shared repository `dist/SHA256SUMS.txt` and were copied into a separate wheelhouse before installation. Wheel metadata confirmed the supplied names and versions:

| Distribution | Version | Wheel SHA-256 |
|---|---:|---|
| `resource-metrics` | 0.3.0 | `dee0f067de04c0fff4f16e4d2c5db19732dc13bf1e23f0e9a68e4f039c704164` |
| `script-logging` | 0.1.1 | `dae0ec9b58eb03ae97e6f5c54187944c80578cb698d2efe260241bf1964d7a56` |
| `web-ui-tools` | 0.2.0 | `4ffe9b92fa93765294ae990264bf6b955b317c040daeb15d4c303c45cb7513d0` |
| `termdash` | 0.10.0 | `f7ba9bbfbbdef68d8a46c6ff3b02aeb39b18c1c10f18862ace9c8beba951fdc6` |
| `cross-platform` | 0.9.0 | `5d9f39a1be8eaacfb872f00205586e7d648654b3a4f54fa5c9f3059c00e6bf40` |

Installed wheel provenance was verified through each distribution's `direct_url.json`; imports resolve under this worktree's `.venv\Lib\site-packages`, with no toolkit/shared source checkout URL. `python -I -m pip check` passed after installation and again after test-only dependencies were added.

Metadata requirements were confirmed: resource-metrics (Python >=3.8, psutil>=5.9), script-logging (Python >=3.8), web-ui-tools (Python >=3.10, FastAPI, Uvicorn, wsproto), termdash (Python >=3.9, Windows curses marker), and cross-platform (Python >=3.9, psutil, pyperclip, Rich). Later read-only Git inspection succeeded: `shared-python-modules` is clean at `feat/dev-bootstrap-20261119` / `a5602e565e9d8a9ad0a381ff39cfa725ea619b7f`; its `main` remains `ff134131d8615e9c68111551ccf1cdf972a66ef4`. The `packages/` and `dist/` trees are unchanged between that branch and `main`, and the five wheel hashes below still match. The toolkit is clean at `feat/shared-packages-migration-20261119` / `0462cf49421d4536ca4efddf86899aa1e2cab6d7`, matching the supplied checkpoint. No files in those repositories were changed. A read-only GitHub query found no open scripts PR and one unrelated toolkit Dependabot PR (`#2`, Black update under `modules/llm_local`). The shared repository PR query returned GitHub API 422 (repository unavailable or not permitted to this connector), so its open-PR state remains unverified before integration.

## Implementation completed

- Added scripts-owned shared distribution requirements and provenance detection in `scripts_setup/shared_packages.py`. It replaces both direct source installs and compatibility wheel installs originating in `llm-agent-toolkit` or `shared-python-modules`.
- Root setup and latest bootstrap ensure the five distributions through ordinary pip requirements, detect and replace legacy source-directory installs, and keep shared source directories out of source installation and discovery.
- Kept the historical P6 transferred-module/CLI exclusion registry intact; shared distribution ownership is checked separately and first.
- Preserved installed TermDash console script discovery after excluding repository source copies.
- Generated launchers now use the scripts `.venv` and a scripts-owned adapter; toolkit checkout/environment fallback was removed. The adapter refreshes scripts manifest data then delegates execution and invocation history to shared `script-logging`.
- Updated scripts-owned dependency metadata for compatible shared distribution ranges and aligned package `__version__` values with six version bumps.
- Added focused ownership, bootstrap helper, wrapper generation, argument/Unicode/CWD/stdio/exit-code, and disposable invocation-history tests.
- Bumped the generated wrapper signature to 0.3.0 so the launcher template change is identifiable.

## Verification performed

- Shared ownership/bootstrap/launcher tests plus setup utility tests excluding the `pscripts`-checkout-only test: 28 passed, 1 deselected.
- Consumer selection spanning backup_module, compresser, rrbackup, system_manager, scheduler: 61 passed.
- sysmon sampler: 4 passed.
- vdedup GPU capability/CLI selection: 19 passed, 1 real-GPU availability test deselected.
- Runmux web CLI and read-only adapter tests: 22 passed.
- Runmux browser `TestClient` coverage remains blocked by a reproducible Windows event-loop/socketpair stall, not an observed application regression. In the integration environment, a minimal FastAPI `TestClient` stalled before entering the test context; the stack was in Starlette/AnyIO portal setup, asyncio Proactor loop creation, `_fallback_socketpair`, and `socket.accept`. A minimal FastAPI TestClient probe in the pre-integration primary scripts environment also stalled in the same socketpair fallback. On this continuation, Runmux app construction completed, but an in-process HTTPX `ASGITransport` probe could not create its asyncio Proactor loop and stalled at the same fallback before sending a request. The probe was interrupted after a faulthandler dump. No application fix was justified, and no service was started. This remains an environment-limited HTTP qualification gate; rerun the existing request tests in a normal Windows environment where asyncio socket pairs work.
- TermDash installed CLI `--help` passed and exposed expected command groups.
- A noninteractive TermDash `SimpleBoard` model build/update/read smoke passed under `python -I`; its renderer was not started.
- Shared imports under `python -I` resolve only from this worktree `.venv`; `pip check` passed.
- Both setup scripts' `--help` commands passed.
- Full `bootstrap_latest.py` completed with exit code 0 in a representative clean export of integration commit `908bec8d`. The export was assembled from committed scripts plus the exact clean `pscripts` submodule commit `70ba27dd9259eea44d3710691fb276573c26789a` and nested `aebn-vod-downloader-custom` commit `af6bb8b1db14c8434c0a9da446ec49bbf067ab9b`; the primary checkout was not modified. A separate Python 3.12.10 environment and qualified wheelhouse were used. The log reports 62 packages, 157 launchers, and 0 failures; `agent-continuity==0.2.0` installed successfully, resolving the earlier clean-worktree missing-package baseline. `python -I -m pip check` passed. All five shared distributions import from that environment's `site-packages`; `termdash --help`, `runmux --help`, and generated `bin/termdash.cmd` and `bin/runmux.cmd` passed. The resulting manifest contained 153 commands and no collisions with transferred toolkit module names or CLI command names. This is a representative Windows installation, not a clean-room/PyPI release test: dependencies could resolve from the configured package index while the five qualified wheels were available in `PIP_FIND_LINKS`.
- The five wheel hashes were rechecked against the shared repository's `dist/SHA256SUMS.txt` during this continuation and matched. Their import locations are under the representative environment's `site-packages`. Their wheel metadata has no `direct_url.json`, as expected for find-links installation; the isolated integration installation's prior recorded provenance checks remain documented above.
- Linux/Ubuntu remains unqualified. `wsl --list --verbose` showed Ubuntu and docker-desktop stopped. Starting Ubuntu could initialize system services; their startup state cannot be established without starting the distro, so no distro or Docker service was started. Use a dedicated Linux CI runner or an explicitly safe WSL environment for qualification.
- `.tmp_build/` is untracked in the integration worktree and contains the representative export, exact submodule archives, qualified wheelhouse, bootstrap log, and bounded Runmux diagnostic probes. It has been reviewed as generated test evidence; it remains unstaged and must not be broadly added. No raw retirement evidence was copied or changed.
- No GPU tests, LLM inference, production services, backups, or live workloads were run.

## Remaining gates

1. Rerun Runmux HTTP request coverage on a Windows host/environment where asyncio Proactor socket-pair creation works; this environment stalls before request dispatch, including with a baseline minimal FastAPI app.
2. Run Linux/Ubuntu qualification on an approved isolated Linux runner; no stopped WSL distro was started here.
3. Review shared repository open-PR state before integration; the connected GitHub query could not access that repository. Scripts had no open PR in the read-only query; the only open toolkit PR observed was unrelated Dependabot PR #2. Their current local Git state was inspected: shared is clean on `feat/dev-bootstrap-20261119` at `a5602e56` (package source and artifacts match `main` at `ff134131`); toolkit is clean on the supplied feature checkpoint `0462cf49`.
4. After the integration branch is accepted, create a separate reconciliation branch from the accepted scripts integration commit. Compare each retired source tree against its quarantine manifest and current scripts `main`; apply only specifically approved module removals from the retirement branch, not a broad merge that could bring unrelated evidence or changes.
5. Keep all seven ownership/data holds and the 16 verified quarantines intact. `resource_metrics` and `script_logging` remain present in the primary checkout; their old retirement-branch removals must not be integrated until shared-package acceptance and consumer gates are approved. Also keep `web_ui_tools`, `termdash`, and `cross_platform` under their existing ownership review gates.
6. After any future source-removal integration, rerun independent bootstrap, `pip check`, affected consumer selections, launcher generation, shared import provenance, and Runmux HTTP request coverage. Restore any failed module from the existing checksum-verified quarantine before proceeding.
7. No primary checkout source retirement, merge, push, or publish was performed or authorized in this phase.

## Rollback

- Revert only the integration commit on `feat/scripts-shared-packages-20261119`, or restore selected files with `git restore --source=<pre-integration-commit> -- <paths>` in this worktree.
- The integration branch starts at the clean main commit above; the primary checkout remains unchanged.
- For a disposable test venv, remove this worktree's ignored `.venv` only after confirming no test process uses it; no external environment was modified.
- If a future authorized integration removes source copies, use the existing checksum-verified quarantine restore instructions. Do not restore by copying over the primary checkout without checking its current state.
