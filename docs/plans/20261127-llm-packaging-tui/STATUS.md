# LLM Packaging TUI Status

## Goal

Add an opt-in interactive packaging workflow backed by the same selection snapshot used by CLI preview and packaging writers.

## Branch and base

- Branch: `codex/llm-packaging-tui`
- Worktree: `C:\Users\mcarls\.codex\worktrees\llm-packaging-preview\scripts`
- Base: `08e38fd673e92fb235ae225c050ddee1b20fb381`

## Decisions

- Keep curses and the `cli_tui` application imports lazy and optional.
- Keep packaging policy and snapshot models independent from terminal rendering.
- Do not change `cli_tui` or introduce generic shell/process execution.
- Preserve existing public function signatures and JSON fields while adding snapshot data.
- TUI only generates output after the user explicitly approves the review screen.

## Baseline evidence

- Packaging tests: 46 passed; one pre-existing `test_text_file_mode_hierarchy_and_content` tree assertion failed.
- `cli_tui` full test collection is blocked by pre-existing `ModuleNotFoundError: sysmon.sampler` in `test_telemetry.py`.
- Fetch from this linked worktree was denied because Git's `FETCH_HEAD` is in protected worktree metadata; branch refs already matched remote at base.

## Status

- Phase 0: complete. The linked worktree fetch was denied by protected Git metadata, but local and remote refs matched at the base SHA.
- Phase 1: partial. Added metadata-only `Inventory` snapshots with lazy scans below newly unpruned directories, cancellation, deterministic ordering, error tracking, and cache-backed reevaluation. The TUI and package writers share `Exclusion` semantics; legacy CLI preview and text traversal have not been fully refactored onto `Inventory`.
- Phase 2: partial. Added opt-in `-i/--tui`, optional source defaulting to the current directory, editable source/output settings, mode/flatten/dry-run controls, a worker-backed scan, and a headless `process_key`/virtual renderer. Curses remains lazy and failure exits without packaging.
- Phase 3: partial. Added rule listing with default/preset/user provenance, add/remove, undo/redo, and direct tree/group actions. Rule-origin toggles, cursor identity preservation, and search are not complete.
- Phase 4: partial. Added directory basename, extension, filename, and largest-entry groups; count/size sorting; group members; and group/member exclusion actions. Broad aggregation/performance qualification is still needed.
- Phase 5: partial. Added review, dry-run generation blocking, overwrite confirmation, flatten collision/marker checks, output-in-source warnings, and a pre-generation inventory comparison. Writers still reselect after validation, leaving a small filesystem race.
- Phase 6: partial. Ruff and focused tests pass. The full packaging suite retains one baseline tree-renderer assertion failure. Windows interactive acceptance, cross-platform checks, performance measurements, and full `cli_tui` suite are outstanding.

## Verification

- `python -m pytest pyscripts/tests/zip_for_llms_test.py -k 'tui_ or inventory_is_metadata_only or preview_' -q -p no:cacheprovider --basetemp C:\Users\mcarls\src\.llm-tui-pytest` — 11 passed.
- `python -m pytest pyscripts/tests/zip_for_llms_test.py -q -p no:cacheprovider --basetemp C:\Users\mcarls\src\.llm-tui-pytest` — 51 passed, 1 pre-existing failure (`test_text_file_mode_hierarchy_and_content`, also failing at baseline).
- `python -m ruff check pyscripts/llm_packaging pyscripts/zip_for_llms.py pyscripts/tests/zip_for_llms_test.py` — passed after removing two unused imports; rerun after final edits.
- Python AST parsing, CLI help inspection, and `git diff --check` passed before the latest worker/documentation edits; rerun before handoff.

## Next action

Finish focused verification and review the scoped diff. Manual Windows/WSL interactive and large-tree performance qualification remain necessary before calling the full plan complete.
