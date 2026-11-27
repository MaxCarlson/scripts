# Checklist

- [x] Test node ID, file, module, and named affected-consumer selection.
- [x] Prove selective execution does not invoke bootstrap/uninstall/install or unrelated named-validation stages.
- [x] Verify selected import origins, editable identity, and forbidden retired-source roots.
- [x] Verify source/dependency/selection changes invalidate successful evidence reuse; test root contents and import identities are fingerprinted.
- [x] Make reuse opt-in; hash in-repository editable source content and disable reuse for external or unidentifiable editable dependencies.
- [x] Detect in-run source changes, including content restored after a transient write, and prevent cacheable success.
- [x] Verify configured imports inside pytest's subprocess and distinguish source-level checks from installed-distribution qualification.
- [x] Redact `Authorization: Bearer TOKEN` when that line is retained in failure evidence.
- [x] Accept an explicit temporary root and normalize manifest `PYTHONPATH` with the active platform separator.
- [x] Verify collision-resistant temp roots and concurrent atomic report isolation.
- [x] Add a real pytest subprocess regression covering runtime provenance and external-root evidence generation.
- [x] Record exact commands, interpreter, worktree/revision, dependencies/import identities, duration, exit status, and concise failure details.
- [x] Document Agent-Environment `test-verify` usage without changing skill/policy files.
- [x] Run focused tests, Python lint, manifest parsing, PowerShell parser validation, and real subprocess provenance regression.
- [x] Review task-only diff, commit, and push feature branch.
- [x] Fast-forward current Scripts main, push direct integration, and verify native CLI availability.
