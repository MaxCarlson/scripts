# Checklist

- [x] Inspect constructor/run/JSON event flow and test helpers in both modules.
- [x] Add ordered scene ID extraction, metadata validation, and timeline count validation in aebndl.
- [x] Add ID lookup, mutual exclusion, structured result, and CLI failure behavior in aebndl.
- [x] Add fixture-backed mapping cases for all supplied IDs, unknown/duplicate/malformed/missing IDs, and network/HTTP errors.
- [x] Add strict fragment parser and explicit ID command path in ytaedl.
- [x] Verify legacy ordinal behavior, manager/worker fragment preservation, dry run, and zero subprocess on invalid selection.
- [x] Bump both package minor versions.
- [x] Run focused pytest suites for both modules and inspect failures.
- [x] Attempt metadata-only live verification; the browser source could not access the AEBN page. No media downloads attempted.
- [x] Review final diff, branch/worktree, status, and update this handoff.
