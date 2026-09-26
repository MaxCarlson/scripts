# Stage 1: Scheduler Module Implementation (Planned)

## Tasks

1. **Package Setup**:
   - `modules/scheduler/pyproject.toml`
   - `modules/scheduler/scheduler/__init__.py`
   - Setup in `setup.py` / editable install support

2. **Data Models and Storage**:
   - `modules/scheduler/scheduler/models.py`
   - `modules/scheduler/scheduler/config.py` (auto-detection of shells)
   - `modules/scheduler/scheduler/storage.py` (persistent JSON at `modules/scheduler/scheduler_data.json`)

3. **Execution and Timing**:
   - `modules/scheduler/scheduler/timing.py` (intervals, daily, weekly, monthly, cron, catch-up logic)
   - `modules/scheduler/scheduler/executor.py` (pwsh, powershell, terminal, admin/non-admin, cross-platform)
   - `modules/scheduler/scheduler/service.py` (orchestration, daemon loop, single-pass evaluation)

4. **Logging and Notifications**:
   - `modules/scheduler/scheduler/logger.py` (strict central log format, task run log retention)
   - `modules/scheduler/scheduler/notifier.py` (cross-platform notifications)

5. **CLI and TUI**:
   - `modules/scheduler/scheduler/cli.py` (exact `file-util` structural pattern with subparsers and flags)
   - `modules/scheduler/scheduler/tui.py` (arrow-key navigable curses menu, $EDITOR shell-out, orphan warnings)

6. **Registry and Validation**:
   - Update `modules/scripts_help/scripts_help/registry/registry.py`
   - Add validation target to `validation-targets.json`
   - Comprehensive test suite in `modules/scheduler/tests/`
