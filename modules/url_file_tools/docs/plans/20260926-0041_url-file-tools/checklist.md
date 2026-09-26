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
- [x] Stop for user manual validation or receive explicit merge approval.
- [x] Receive explicit user approval to merge Stage 1 into `main`.
- [ ] Stage 2: integrate `urls match` into mangadl and ytaedl after API validation.

## Verification evidence

- `./Invoke-Tests.ps1 -Target url-file-tools` - PASS
- Dispatcher sections: editable install, compile, ruff, module help, installed entry point, pytest - PASS
- `python -m pytest tests -q -o addopts="" --basetemp .pytest_tmp_root/url-file-registry` from `modules/scripts_help` - 42 passed (cache warning only)
- `url-files --version` - `url-files 1.0.0`
- Root-level imports of `build_merge_plan`, `match_archive_urls`, and `registered_domain` - PASS
