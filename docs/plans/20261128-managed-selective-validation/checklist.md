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

## Parallel validation expansion — 2026-11-27

- [x] Add explicit PowerShell `-Workers` 0–16, pass it to the existing runner, and keep nonzero workers selective-only.
- [x] Preserve worker evidence identity, provenance, temp-root isolation, local-only execution and evidence reuse details.
- [x] Exercise the helper subprocess at 12 workers and public wrapper at 12 and 16 workers using synthetic consumers.
- [x] Compare serial/12/16 elapsed time and record worker process fan-out plus the lack of peak-memory sampling.
- [x] Keep the stale editable-environment block as local evidence; do not alter the installed environment.
- [x] Report only actually observed runtime worker receipts and exercise missing/unexpected receipt rejection.
- [x] Preflight native pytest addopts, prevent ambient xdist/basetemp overrides, reject remote execution, and verify the effective temporary root in pytest.
- [x] Promote unhandled thread-exception warnings to fatal and verify real serial/xdist subprocess failures.
- [x] Fetch current Scripts main and reconcile the accepted integration candidate.
- [x] Correct the serial mock receipt shape and pass the complete managed-validator suite on canonical main.
- [x] Push and synchronize the authorized Scripts main integration while preserving unrelated checkout state.
