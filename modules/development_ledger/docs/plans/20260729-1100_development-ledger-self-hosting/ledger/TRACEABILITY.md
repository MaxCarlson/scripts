# Traceability: Development Ledger Self-Hosting

> Generated. Plan items declare expected evidence; normalized results report actual evidence.

## Item to Evidence

### `AC-S1-001` — The dispatcher adapter treats a successfully written failed-test event as recording success while preserving actual recording failures.

- Kind: `criterion`
- Architecture role: `foundation`
- Priority: `10`
- Depends on: (none)
- Implementation: `implemented`
- Verification: `unverified`
- Expected test patterns: `pytest:tests/dispatcher_record_test.py::test_dispatcher_record_preserves_recording_failures*`
- Matched tests: (none)
- Manual checks: (none)
- Relevant files: `development_ledger/dispatcher_record.py`, `tests/dispatcher_record_test.py`

### `AC-S1-002` — The repository root dispatcher exposes a development-ledger target that validates the module, emits JUnit XML, and records a plan event last.

- Kind: `criterion`
- Architecture role: `integration`
- Priority: `10`
- Depends on: `AC-S1-001`
- Implementation: `implemented`
- Verification: `unverified`
- Expected test patterns: `pytest:tests/scripts_repository_integration_test.py::test_validation_manifest_self_hosts_development_ledger`
- Matched tests: (none)
- Manual checks: `MC-S1-001`
- Relevant files: `../../validation-targets.json`, `tests/scripts_repository_integration_test.py`

## Test to Item

- `pytest:tests.analysis_test::test_evaluate_items_separates_automated_and_manual_state` → (regression-only) — **passed**
- `pytest:tests.analysis_test::test_build_event_detects_persistent_failure_and_loop` → (regression-only) — **passed**
- `pytest:tests.analysis_test::test_environment_failure_escalates_immediately` → (regression-only) — **passed**
- `pytest:tests.analysis_test::test_recommend_local_model_uses_sol_for_security` → (regression-only) — **passed**
- `pytest:tests.analysis_test::test_all_items_verified_produces_ready` → (regression-only) — **passed**
- `pytest:tests.analysis_test::test_conflicting_request_stops_before_implementation` → (regression-only) — **passed**
- `pytest:tests.analysis_test::test_batch_candidates_favor_foundational_prerequisites` → (regression-only) — **passed**
- `pytest:tests.analysis_test::test_architecture_review_becomes_due_after_configured_run_backstop` → (regression-only) — **passed**
- `pytest:tests.cli_test::test_validate_plan_cli` → (regression-only) — **passed**
- `pytest:tests.cli_test::test_record_cli_writes_ledger_and_projections` → (regression-only) — **passed**
- `pytest:tests.cli_test::test_init_plan_defaults_to_preview` → (regression-only) — **passed**
- `pytest:tests.cli_test::test_init_plan_write_creates_file` → (regression-only) — **passed**
- `pytest:tests.cli_test::test_main_returns_two_for_invalid_plan` → (regression-only) — **passed**
- `pytest:tests.cli_test::test_manual_and_summarize_cli` → (regression-only) — **passed**
- `pytest:tests.dispatcher_record_test::test_dispatcher_record_preserves_recording_failures[0-0]` → (regression-only) — **passed**
- `pytest:tests.dispatcher_record_test::test_dispatcher_record_preserves_recording_failures[1-0]` → (regression-only) — **passed**
- `pytest:tests.dispatcher_record_test::test_dispatcher_record_preserves_recording_failures[2-2]` → (regression-only) — **passed**
- `pytest:tests.event_id_test::test_automatic_event_ids_are_unique_for_same_timestamp_and_commit` → (regression-only) — **passed**
- `pytest:tests.ledger_test::test_append_event_writes_compact_jsonl_and_rejects_duplicates` → (regression-only) — **passed**
- `pytest:tests.ledger_test::test_read_events_rejects_invalid_json` → (regression-only) — **passed**
- `pytest:tests.plan_test::test_load_plan_parses_items_and_manual_checks` → (regression-only) — **passed**
- `pytest:tests.plan_test::test_parse_plan_rejects_missing_markers` → (regression-only) — **passed**
- `pytest:tests.plan_test::test_parse_plan_rejects_duplicate_item_ids` → (regression-only) — **passed**
- `pytest:tests.plan_test::test_parse_plan_rejects_unknown_manual_check_reference` → (regression-only) — **passed**
- `pytest:tests.plan_test::test_render_plan_template_round_trips` → (regression-only) — **passed**
- `pytest:tests.plan_test::test_plan_rejects_invalid_implementation_state` → (regression-only) — **passed**
- `pytest:tests.plan_test::test_plan_rejects_manual_check_unknown_item` → (regression-only) — **passed**
- `pytest:tests.pytest_plugin_test::test_pytest_plugin_registers_marker_and_exports_properties` → (regression-only) — **passed**
- `pytest:tests.pytest_plugin_test::test_marker_ids_ignores_empty_values` → (regression-only) — **passed**
- `pytest:tests.render_test::test_render_progress_is_compact_orientation_document` → (regression-only) — **passed**
- `pytest:tests.render_test::test_write_projections_creates_all_expected_files` → (regression-only) — **passed**
- `pytest:tests.render_test::test_local_handoff_contains_attempt_history_when_escalated` → (regression-only) — **passed**
- `pytest:tests.render_test::test_architecture_review_projection_explains_due_review` → (regression-only) — **passed**
- `pytest:tests.render_test::test_render_progress_without_events_and_inactive_handoff` → (regression-only) — **passed**
- `pytest:tests.results_test::test_parse_junit_xml_extracts_status_and_requirement` → (regression-only) — **passed**
- `pytest:tests.results_test::test_parse_script_results_preserves_explicit_ids` → (regression-only) — **passed**
- `pytest:tests.results_test::test_parse_transcript_extracts_commands_pytest_counts_and_coverage` → (regression-only) — **passed**
- `pytest:tests.results_test::test_failure_fingerprint_normalizes_paths_and_addresses` → (regression-only) — **passed**
- `pytest:tests.results_test::test_parse_script_results_rejects_bad_status` → (regression-only) — **passed**
- `pytest:tests.results_test::test_parse_transcript_without_summary_returns_zero_metrics` → (regression-only) — **passed**
- `pytest:tests.schema_test::test_all_shipped_json_schemas_are_valid_json` → (regression-only) — **failed**
- `pytest:tests.scripts_repository_integration_test::test_validation_manifest_self_hosts_development_ledger` → (regression-only) — **passed**
- `pytest:tests.setup_cli_test::test_setup_cli_dry_run_then_write` → (regression-only) — **passed**
- `pytest:tests.setup_cli_test::test_setup_cli_json_output` → (regression-only) — **passed**
- `pytest:tests.setup_cli_test::test_dedicated_setup_entrypoint_prepends_subcommand` → (regression-only) — **passed**
- `pytest:tests.setup_preservation_test::test_existing_docs_readmes_and_handoff_are_preserved` → (regression-only) — **passed**
- `pytest:tests.setup_preservation_test::test_existing_agent_file_with_broken_marker_blocks_application` → (regression-only) — **passed**
- `pytest:tests.setup_test::test_setup_dry_run_is_non_mutating_and_targets_multiple_scopes` → (regression-only) — **passed**
- `pytest:tests.setup_test::test_apply_setup_creates_native_files_docs_and_config` → (regression-only) — **passed**
- `pytest:tests.setup_test::test_existing_agents_content_is_preserved_and_setup_is_idempotent` → (regression-only) — **passed**
- `pytest:tests.setup_test::test_nested_claude_and_gemini_import_scoped_agents_and_root_workflow` → (regression-only) — **passed**
- `pytest:tests.setup_test::test_copilot_scope_file_has_apply_to_pattern` → (regression-only) — **passed**
- `pytest:tests.setup_test::test_unmarked_managed_document_conflicts_unless_forced` → (regression-only) — **passed**
- `pytest:tests.setup_test::test_missing_module_and_scope_escape_are_rejected` → (regression-only) — **passed**
- `pytest:tests.setup_test::test_all_modules_discovers_immediate_module_directories` → (regression-only) — **passed**
- `pytest:tests.writer_test::test_write_script_results_round_trips` → (regression-only) — **passed**
- `pytest:tests.writer_test::test_script_check_rejects_invalid_status` → (regression-only) — **passed**
- `command:clean-stale-development-ledger-editable-metadata` → (regression-only) — **passed**
- `command:install-development-ledger-editable-development-dependencies` → (regression-only) — **passed**
- `command:compile-development-ledger-package-and-tests` → (regression-only) — **passed**
- `command:lint-development-ledger-package-and-tests` → (regression-only) — **passed**
- `command:validate-development-ledger-active-plan` → (regression-only) — **passed**
- `command:development-ledger-cli-help-contract` → (regression-only) — **passed**
- `command:development-ledger-pytest-and-coverage-suite` → (regression-only) — **failed**
