# Checklist

- [x] Test node ID, file, module, and named affected-consumer selection.
- [x] Prove selective execution does not invoke bootstrap/uninstall/install or unrelated named-validation stages.
- [x] Verify selected import origins, editable identity, and forbidden retired-source roots.
- [x] Verify source/dependency/selection changes invalidate successful evidence reuse; test root contents and import identities are fingerprinted.
- [x] Verify collision-resistant temp roots and concurrent atomic report isolation.
- [x] Record exact commands, interpreter, worktree/revision, dependencies/import identities, duration, exit status, and concise failure details.
- [x] Document Agent-Environment `test-verify` usage without changing skill/policy files.
- [x] Run focused tests, Python lint, manifest parsing, PowerShell parser validation, and a live import-origin probe.
- [ ] Review task-only diff, commit, and push feature branch.
