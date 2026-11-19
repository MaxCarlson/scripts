# Scripts Shared-Package Integration Status

Updated: 2026-11-19

## Checkpoint

- Integration worktree: `.worktrees/scripts-shared-package-integration-20261119`
- Branch: `feat/scripts-shared-packages-20261119`
- Base: `f57b22652dfc8cd67823a2a0d1d2792b3f09a320`
- Local checkpoint: `6348b3bc` (`feat(scripts): install shared packages independently`); a follow-up documentation-only checkpoint records the final state.
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

Metadata requirements were confirmed: resource-metrics (Python >=3.8, psutil>=5.9), script-logging (Python >=3.8), web-ui-tools (Python >=3.10, FastAPI, Uvicorn, wsproto), termdash (Python >=3.9, Windows curses marker), and cross-platform (Python >=3.9, psutil, pyperclip, Rich). The shared and toolkit Git worktree status could not be independently read because the sandbox denies external worktree access. Their supplied refs/commit objects were visible, but this is not a dirty-state audit; report the limitation before integration.

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
- Runmux browser `TestClient` tests collected after installing test-only `httpx2` but blocked on the first request and were interrupted; direct Runmux FastAPI application construction from the installed `web-ui-tools` wheel passed. No persistent service was started.
- TermDash installed CLI `--help` passed and exposed expected command groups.
- A noninteractive TermDash `SimpleBoard` model build/update/read smoke passed under `python -I`; its renderer was not started.
- Shared imports under `python -I` resolve only from this worktree `.venv`; `pip check` passed.
- Both setup scripts' `--help` commands passed.
- Latest bootstrap dry-run exited 0; it did not install packages or mutate wrappers. It omitted all five shared source directories from source-install candidates and discovered TermDash's installed CLI entry point. The clean worktree environment reports 56 missing applications and notes that the `pscripts` submodule would be initialized in a real install. Full bootstrap was not run to avoid submodule/network and broad application installation side effects.
- One setup utility test remains unavailable because the clean worktree has no `pscripts/modules/setup.py` submodule checkout.
- Linux/Ubuntu was unavailable and remains unqualified. No GPU tests, LLM inference, production services, backups, or live workloads were run.

## Remaining gates

1. Complete a clean full scripts installation in a controlled environment with the authorized `pscripts` checkout and qualified wheelhouse; then run `pip check`, launcher resolution, and targeted consumers.
2. Diagnose the Runmux TestClient hang with the normal supported Windows test environment; current direct app construction and CLI/adapter tests do not replace HTTP request coverage.
3. Validate on Linux/WSL2.
4. Independently review shared/toolkit dirty worktree and open-PR state when repository access is available.
5. Reconcile the completed integration branch with the retirement checkpoint after validation. Keep all seven ownership/data holds and do not merge quarantined `resource_metrics` or `script_logging` deletions.
6. Do not retire any primary checkout shared source directory until the separate cleanup gates and authorization in the handoff are met.

## Rollback

- Revert only the integration commit on `feat/scripts-shared-packages-20261119`, or restore selected files with `git restore --source=<pre-integration-commit> -- <paths>` in this worktree.
- The integration branch starts at the clean main commit above; the primary checkout remains unchanged.
- For a disposable test venv, remove this worktree's ignored `.venv` only after confirming no test process uses it; no external environment was modified.
- If a future authorized integration removes source copies, use the existing checksum-verified quarantine restore instructions. Do not restore by copying over the primary checkout without checking its current state.
