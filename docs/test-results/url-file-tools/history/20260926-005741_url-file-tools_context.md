# Validation Context: url-file-tools

Generated: 2026-09-26T00:57:43.1008880-07:00
Branch: url-file-tools-20260926-0041
Commit: f0a4d5d331ceaad4e7276e6f5dd0eb08a49f74b9
Validation report: docs\test-results\url-file-tools\LATEST.txt

## Validation Highlights

- RESULT: PASS - Compile URL file tools package and tests
- RESULT: PASS - Lint URL file tools package and tests
- RESULT: PASS - URL file tools CLI help contract
- RESULT: PASS - Installed URL file tools entry point
- RESULT: PASS - URL file tools pytest suite
- TARGET RESULT: PASS

## Working Tree

```text
 M modules/scripts_help/scripts_help/registry/registry.py
 M validation-targets.json
?? docs/test-results/url-file-tools/
?? modules/url_file_tools/
```

## Project Status Sources

### `docs/plans/20260926-0041_url-file-tools/STATUS.md`

# Status

- State: awaiting manual validation
- Stage: 1 - implementation and validation
- Branch: `url-file-tools-20260926-0041`
- Last updated: 2026-09-26 01:00 PDT
- Verification: `./Invoke-Tests.ps1 -Target url-file-tools` passed; compile, ruff, installed CLI help/version, and 11 tests passed
- Additional verification: `python -m pytest tests -q -o addopts="" --basetemp .pytest_tmp_root/url-file-registry` in `modules/scripts_help` passed (42 tests; cache warning only)
- Packaging check: `url-files --version` and root-level public imports passed
- Archive boundary: ytaedl archive URLs match directly; mangadl uses `.mangadl/state.sqlite3`; gallery-dl media-key archives are rejected rather than guessed
- Next: user manual validation; Stage 2 adds thin mangadl/ytaedl `urls match` commands after API acceptance

### `docs/plans/20260926-0041_url-file-tools/checklist.md`

# Checklist

- [x] Choose a standalone module boundary and record safety invariants.
- [x] Implement source discovery and manifest containment checks.
- [x] Implement numbered-prefix and mobile-host normalization.
- [x] Implement duplicate provenance and interactive/explicit policies.
- [x] Implement single-file and registered-domain split plans.
- [x] Implement read-only ytaedl and mangadl-state archive adapters.
- [x] Expose stable importable planning and archive-match APIs.
- [x] Implement dry-run summaries, backups, and atomic writes.
- [x] Add focused tests for normal, edge, and failure paths.
- [x] Document CLI examples and behavior.
- [x] Register the CLI and dispatcher target.
- [x] Run exact verification commands and record results.
- [x] Stop for user manual validation.
- [ ] Stage 2: integrate `urls match` into mangadl and ytaedl after API validation.

## Verification evidence

- `./Invoke-Tests.ps1 -Target url-file-tools` - PASS
- Dispatcher sections: editable install, compile, ruff, module help, installed entry point, pytest - PASS
- `python -m pytest tests -q -o addopts="" --basetemp .pytest_tmp_root/url-file-registry` from `modules/scripts_help` - 42 passed (cache warning only)
- `url-files --version` - `url-files 1.0.0`
- Root-level imports of `build_merge_plan`, `match_archive_urls`, and `registered_domain` - PASS

### `docs/plans/20260926-0041_url-file-tools/00_implementation-plan.md`

# URL File Tools Implementation Plan

## Goal

Create a cross-platform, dry-run-first Python CLI that supersedes the supplied
PowerShell URL-list cleanup workflow and adds safe merge, domain-split, and
downloader-archive matching modes. The same behavior is exposed as an importable
library for future mangadl and ytaedl CLI integration.

## Invariants

- No input or output file is changed without `--apply`.
- Duplicate removal is explicitly prompted or selected by policy.
- File-list selections cannot escape the target folder.
- Domain splitting uses registered domains, not a naive last-two-label rule.
- Only an exact leading `m.` hostname label is removed.
- Output and report paths are excluded from future source discovery.
- Source locations and summary statistics make every planned data loss visible.
- Archive adapters are read-only and distinguish direct URL evidence from
  gallery-dl's per-media keys.

## Stage 1

Implement package metadata, normalization, merge, and archive-match engines,
CLI, tests, documentation, help-registry integration, and repository dispatcher
validation.

## Stage 2

After Stage 1 manual validation, add thin `mangadl urls match` and
`ytaedl urls match` integrations that import the stable library API. Version,
test, and document both downstream CLIs without duplicating matcher logic.

## Acceptance

- Numbered prefixes and optional duplicates are handled with preserved text encoding.
- Folder, explicit file names, and manifest selection work.
- Single-file and registered-domain split output work.
- Dry-run reports sources, URLs, duplicates, domains, mobile rewrites, invalid rows, and outputs.
- Apply mode prompts for duplicate removal by default and supports automation policies.
- Focused tests, compile, lint, help, and dispatcher validation pass.
- ytaedl text archives and mangadl URL-level state databases classify downloaded
  and not-downloaded URLs without writing to archive storage.
