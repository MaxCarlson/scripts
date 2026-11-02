# Feature & Verification Checklist: Server Status & Stop Commands

- [x] **Stage 1: Server Descriptor, Filesystem Security Model, and Process Identity**
  - [x] Write failing tests for descriptor serialization, security ACLs/modes, and process checking
  - [x] Implement `ServerDescriptor` and helper methods in `server_lifecycle.py`
  - [x] Verify Stage 1 tests pass cleanly

- [x] **Stage 2: Zero-Knowledge Verification and Authenticated Shutdown Protocol**
  - [x] Write failing tests for HMAC challenge verification and signed shutdown request
  - [x] Implement HMAC signing, validation, and ASGI control routes in `server_lifecycle.py`
  - [x] Verify Stage 2 tests pass cleanly

- [x] **Stage 3: Graceful Request Draining, Durable Recorder Flush, and Forced Termination**
  - [x] Write failing tests for request draining, recorder flush failure aborts, dry-run preview, and forced termination
  - [x] Implement request rejection on shutdown in `gateway.py`, recorder flush handling, preview mode, and force termination in `server_lifecycle.py`
  - [x] Verify Stage 3 tests pass cleanly

- [x] **Stage 4: Web Server Runner Integration, Pre-bound Socket, and Status Command**
  - [x] Write failing tests for `status_server`, socket pre-binding, and `run_web` integration
  - [x] Implement `bind_loopback_socket`, `LLMMonitorWebServer`, `status_server`, and update `web.py`
  - [x] Verify Stage 4 tests pass cleanly

- [x] **Stage 5: CLI Command Syntax Integration & Regression Tests**
  - [x] Write failing tests for CLI syntax (`status`, `stop`, `-x`, `-f/--force`, compatibility)
  - [x] Implement CLI argument handling in `cli.py`
  - [x] Verify Stage 5 tests pass cleanly

- [x] **Stage 6: Full Verification, Documentation, and Handoff**
  - [x] Adversarial security & code quality review completed via research subagent
  - [x] Remediate review findings: Windows ACL checks, strict `process_create_time` requirement, async exit response flush scheduling, pre-auth nonce replay DoS protection, and instance ID matching
  - [x] Run full test suite (253 passed, 2 skipped)
  - [x] Run Ruff linter (0 errors across `modules/llm_monitor`)
  - [x] Update `README.md`, `STATUS.md`, `HANDOFF.md`
