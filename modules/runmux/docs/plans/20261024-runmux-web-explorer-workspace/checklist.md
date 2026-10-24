# Phase 3 Checklist

- [x] Verify merged Phase 2/5B base, clean original checkout, and dedicated branch.
- [x] Read Phase 3 handoff, module instructions, current UI/API fields, and metadata privacy boundary.
- [x] Capture actual browser screenshots of the empty-registry and large synthetic registry states.
- [x] Add explorer grouping, status filtering, supported sorts, full-list search, and bounded paging regressions.
- [x] Restore safe session preferences and Run-ID tabs; prune missing IDs.
- [x] Distinguish duplicate-name runs and preserve scrollable tab navigation.
- [x] Reconcile selected detail state and registry connectivity consistently.
- [x] Add accessible explorer collapse/resize and improve header/details using only authorized metadata.
- [x] Verify 450 synthetic records, desktop/tablet/mobile sizes, keyboard use, browser console, safe output rendering, reload restore, and close-view state invariants.
- [x] Update phase status and roadmap; run focused JavaScript and whitespace checks.
- [ ] Backend pytest is blocked on this Windows host: bounded `python -m pytest tests/web_test.py -q` produced no output for 15 seconds and was interrupted; see STATUS.
- [ ] Commit and push the dedicated Phase 3 branch; do not merge without explicit authorization.
