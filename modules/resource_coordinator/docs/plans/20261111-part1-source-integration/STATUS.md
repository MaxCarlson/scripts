# Part 1 Integration Status

## Checkpoints

- Current base: `6467edc6e82ce22b18ac3fd869188243af6085f7` (`origin/main`, refreshed during the assignment on 2026-11-11).
- Earlier base when the worktree was created: `10420e971f4215986c49d2f247cf38a558795e7d`.
- RC feature: `737bc6b2db7b68c041abffb66017164f3c883228`.
- Merge base: `0022c4fe9cab8a1c9cc2c03b346efbde0e69881a`.
- RC integration branch: `integration/rc-v014-h3-baseline-20261111`.
- RC first merge checkpoint: `e2c3d1825ecba9e3f260c093d06c8fb5f2ab3a6c`.
- RC latest-main merge checkpoint: `1316dd1674687a75d21782da79220f5742dddea2`.
- RC source integration checkpoint: `1316dd1674687a75d21782da79220f5742dddea2`; documentation/evidence commits follow without source changes.
- Mining base: `4b1f2a57b0bac536d250a7018df1f8a20c78e1c5` (`origin/master`).
- Mining candidate: `deea3e019b35615f4d95e6f510450f7f392fb82a`.
- Mining integration branch: `integration/mining-rc-h3-baseline-20261111`, fast-forwarded to the same H3 commit.

## Integration review

- RC feature diff is 22 paths, all within Resource Coordinator. `scripts/main` advanced from `10420e9` to `6467edc` during the assignment and changed 27 paths across Notifications, scheduler, shared docs, and ignore files. It changed no RC source or test paths. Two notification docs changed on both histories; the candidate copies matched its `10420e9` parent, and the current main versions were preserved by the second merge.
- RC package source, tests, and `pyproject.toml` are byte-identical to H3-pinned RC source `737bc6b2`; `git diff --quiet 737bc6b2...HEAD -- modules/resource_coordinator/resource_coordinator modules/resource_coordinator/tests modules/resource_coordinator/pyproject.toml` exited 0. The integration does not alter H2C verification or H3 protocol handlers.
- H3 remains accepted from its recorded machine-readable result: 8/8 passed, tested Mining `9cdaf80d9507c4c91ef5b1e45a9441c93969f45d` and RC `737bc6b2db7b68c041abffb66017164f3c883228`; JUnit/summary: `C:\Users\mcarls\AppData\Local\Temp\h3-cross-repo-740030829aa04623b0ef1a4cfa770832\`. Mining `deea3e0` differs from `9cdaf80` only in H3 docs/status files. No full H3 rerun was needed.
- A prior exploratory RC whole-module run (v0.13 candidate) recorded 729 passed, 7 skipped, 1 deselected, 6 failed. The failures were two stale CLI architecture expectations, an occupied live listener on port 1235, one test cooldown window later lengthened, one acceptance temp-lock/timing issue that passed independently, and a live-mode safety guard refusing the already-running `krig-miner.exe`. No live miner was started or stopped by the guard. These are historical findings, not a current full-suite pass.

## Validation evidence

Windows 11; CPython 3.12.10 x64; pytest 9.0.3; Ruff 0.14.8. RC imports from this worktree as version `0.14.0`. The sandboxed bare `asyncio.run(asyncio.sleep(0))` smoke timed out after 8 seconds before importing RC; the same smoke outside the sandbox passed in 0.46 seconds. The exact async maintenance test then passed out of sandbox, and suites were run in the scoped normal-permission context.

| Command / evidence | Result |
|---|---|
| `python -m pytest tests/test_maintenance.py tests/test_restoration.py tests/test_durable_state.py tests/test_leases.py tests/test_admission.py tests/test_gateway.py tests/test_factory_gateway_integration.py tests/test_phase1_request_arbitration.py -q -o addopts='' --basetemp <unique-temp> --junitxml <unique-temp>.xml` | **130 passed**, exit 0. JUnit: `C:\Users\mcarls\AppData\Local\Temp\rc-part1-core-final-388afd3f5774442badceb56d8b5de46b.xml`. |
| Process, miner adapter, lifecycle, CLI/architecture, installation, credentials, runtime identity, and Windows task transport group (`test_processes.py`, `test_miner_adapter.py`, `test_phase2_miner_lifecycle.py`, `test_service_lifecycle.py`, `test_cli.py`, `test_cli_architecture.py`, `test_installation.py`, `test_operator_credentials.py`, `test_runtime_identity.py`, `test_windows_task_transport_integration.py`) | **327 passed, 3 skipped, 1 failed**, exit 1. JUnit: `C:\Users\mcarls\AppData\Local\Temp\rc-part1-system-ed5a456bc5a14b13be76774131b4c955.xml`. The 3 skipped cases are opt-in Windows Task Scheduler/installation/UAC acceptance. |
| Isolated `test_gpu_idle_pause_persists_across_restart_and_resumes_after_complete_window` on integration candidate | **1 failed**, exit 1. Fake miner remains stopped after service restart; warning: `manual override is active`. JUnit: `C:\Users\mcarls\AppData\Local\Temp\rc-part1-candidate-idle-final-20261111.xml`. |
| Same isolated test on unchanged `origin/main` (`10420e9`, import from primary checkout) | **1 failed**, exit 1, same assertion and reason. The lifecycle test file is byte-identical between baseline and candidate. This is a baseline lifecycle/test-state issue, not an RC maintenance integration regression. |
| `tests/test_config.py` | **15 passed**, exit 0. |
| Ruff on all 14 RC Python paths changed against current `origin/main` | Passed, exit 0. |
| `python -m compileall -q modules/resource_coordinator/resource_coordinator modules/resource_coordinator/tests` | Passed, exit 0. |
| `git diff --check origin/main...HEAD` | Passed, exit 0. |

The staged whitespace check passes when excluding the three verbatim roadmap copies. The full staged git diff --check reports trailing whitespace present in those copied source documents (many lines use Markdown hard-break spacing); the copies are byte-identical to the original untracked files and were not normalized.

The core suite initially timed out only in the sandbox due to the standalone asyncio issue. After the bounded external smoke succeeded, the named async test and the complete core suite passed. No source changes were made to accommodate the environment.

Mining integration worktree imports `mining_optimizer` and `program_optimizer` from its own source directories using the recorded H3 Python 3.12.10 venv. `pytest tests/optimizer -q -o addopts=''` passed **190** tests (exit 0; JUnit `C:\Users\mcarls\AppData\Local\Temp\mining-part1-opt-a2418ce8d1c64168a40f7e1bb4521a3e.xml`). `pytest modules/program_optimizer/tests -q -o addopts=''` passed **13** (exit 0; JUnit `C:\Users\mcarls\AppData\Local\Temp\mining-part1-shared-5cb6e5eecdc147c4a62325a14e9f08e9.xml`). Existing H3 summary reports **8 passed** at Mining `9cdaf80...` / RC `737bc6...`; summary/JUnit path is given above. Ruff on all 18 changed Python paths found 37 diagnostics, all with matching path/code/message in the clean `origin/master` baseline; baseline had 42, candidate had zero new findings and fixed five. Ruff on all added H2B/H2D/H3 files passed. Compilation and `git diff --check origin/master..HEAD` passed.

## Preservation

The original RC feature worktree remains on `agent/resource-coordinator-v013-integration-restoration-20261111`; its roadmap files were not edited or tracked there. Per the user clarification, the entire directory is copied into this integration candidate and tracked byte-for-byte. `MASTER_IMPLEMENTATION_PLAN.md` SHA-256: `F465FDA2E2F048D49BD0C62C0A54846C3F33F3B6E0A3A82D1CB664498F48F3E9`; V2: `E62477D4E58C09C49DBF4259A465ADE09AB3C8610267E4DC3E55286CD7361E07`; V3: `BA842936C9DE945EE8463FD41C3E60491A5714DCA1CF481064DC915DBF516F46`. V3 changed from `C3D089DF...` during the assignment while the original worktree remained untouched; the final copy matches the source current hash. The original scripts checkout remains dirty only with pre-existing unrelated work. Original Mining master, H3, and safety-recovery worktrees were not modified.

## Integration decision

**READY WITH DOCUMENTED LIMITATIONS** for source integration review. RC source matches the validated v0.14.0/H3-pinned source, targeted tests pass, and the one lifecycle failure reproduces on current main. Mining H3 candidate and its 190 optimizer / 13 shared-package regressions pass. Elevated Windows upgrade, target hardware qualification, and first controlled optimizer acceptance remain open. This is not production readiness.
