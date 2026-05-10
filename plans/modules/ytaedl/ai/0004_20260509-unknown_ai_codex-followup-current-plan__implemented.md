---
plan_index: 0004
origin: ai
status: implemented
source_file: current_plan.md
---

# ytaedl Current Plan

Status date: 2026-05-09

## Summary

Current work continues from the committed Claude plan set:

- `latest_plan_claude.md`
- `99_xx_percent_stuck_plan.md`
- `versioning_and_scripts_cohesion_plan.md`

Those source plans are retained for history. This file is the current concise
execution plan.

## Implementation Targets

- Harden the already-added `ytaedl run watcher|grid|webview|disable` CLI shape.
- Keep multi-root duplicate checks and ensure hidden worker flags have both
  short and long forms.
- Prevent stale near-complete progress from surviving into simulate and
  fallback phases by using per-worker attempt generation and phase state.
- Keep `MODULE_STANDARDS.md` as the single standards source for Codex, Claude,
  Gemini, and Copilot instructions.
- Keep all durable plans in `plans/`, retaining older plans with their original
  content.

## Validation

Use the repo venv:

```powershell
.\.venv\Scripts\python.exe -m py_compile modules\ytaedl\ytaedl\manager.py modules\ytaedl\ytaedl\downloader.py
.\.venv\Scripts\python.exe -m pytest modules\ytaedl\tests -q -p no:cacheprovider
```

If Windows temp ACL errors appear, set `YTAEDL_PYTEST_TEMPROOT` to a writable
workspace-local directory and rerun.
