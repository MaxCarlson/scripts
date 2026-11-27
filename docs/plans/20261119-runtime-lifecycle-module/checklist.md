# V3 Checklist

- [x] Task 1: principal/SID and trigger models, validated TaskSpec, canonical UTF-16 XML, parser, semantic diff, and tests. (**Passed**)
- [x] Task 2: ownership-aware task CRUD/control, status, drift detection, snapshots/restores, audit/list, elevation checks, CLI, mutex, and process helpers. (**Passed**)
- [x] Task 3: snips ensure-runtime, detached recovery, task lifecycle CLI, migration ordering, status/doctor, dependency/version/docs/help registry, and tests. (**Passed**)
- [x] Task 4 local validation: focused pytest, Ruff/format, compileall, and generated task definition review (58 `runtime_lifecycle` tests + 35 `snips` tests = 93 passed, 0 skipped). (**Passed**)
- [x] Task 4 live user-session setup: preview/apply, XML round-trip compatibility, process recovery, disable/stop/enable controls, and legacy Run migration verified on Windows Task Scheduler (`\Scripts\snips-runtime`). (**Passed**)
- [x] Acceptance Test A: interactive desktop hotkey verification (`Ctrl+Alt+V` and `Ctrl+Alt+B`). (**Passed — manual user verification**; prior agent `SendInput` attempt blocked by Win32 `ERROR_ACCESS_DENIED (5)`)
- [ ] Acceptance Test B: fresh Windows login trigger verification. (**Pending** — active user session not signed out/rebooted; `LogonTrigger` verified in registered task XML)
- [x] Final code and integration review: diff, ownership/XML safeguards, registry integration, and `main` merge readiness verified. (**Passed**)
- [x] Final local check: `git diff --check` and branch status on `codex/startup-lifecycle-20261119`. (**Passed**)
- [x] No commit, push, or merge without explicit authorization. (**Passed**)
