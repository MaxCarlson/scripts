# Tmux Manager Tests

Comprehensive test suite for the tmux_manager module.

## Running Tests

### Run all tests:
```bash
cd ~/scripts/modules/tmux_manager
pytest
```

### Run specific test file:
```bash
pytest tests/test_window_manager.py
pytest tests/test_cli.py
```

### Run tests with coverage:
```bash
pytest --cov=tmux_manager --cov-report=html
```

### Run specific test class:
```bash
pytest tests/test_window_manager.py::TestWindowSpecParsing
```

### Run specific test:
```bash
pytest tests/test_window_manager.py::TestWindowSpecParsing::test_single_index
```

## Test Structure

### `test_window_manager.py`
Tests for the `TmuxWindowManager` class:
- **TestWindowSpecParsing**: Tests for parsing window specifications (ranges, comma-separated, negative indices)
- **TestNegativeIndexResolution**: Tests for resolving negative indices to actual window numbers
- **TestWindowOperations**: Tests for window operations (move, swap, close)
- **TestSessionAndWindowQueries**: Tests for querying sessions and windows
- **TestErrorHandling**: Tests for error conditions and edge cases
- **TestFuzzySelection**: Tests for fzf integration

### `test_cli.py`
Tests for the CLI interface:
- **TestCLICommands**: Tests for all CLI commands (closew, mvw, sww, mvws, swws)
- **TestCLIErrorHandling**: Tests for CLI error handling and exit codes
- **TestCLIArgumentParsing**: Tests for argument parsing
- **TestIntegrationScenarios**: Integration tests for common usage scenarios

### `conftest.py`
Shared pytest fixtures:
- `mock_tmux_command`: Mock tmux command execution
- `mock_env_tmux`: Mock TMUX environment variable
- `mock_env_no_tmux`: Mock environment without tmux
- `sample_window_indices`: Sample window indices for testing
- `sample_sessions`: Sample session names for testing
- `mock_fzf_selection`: Mock fzf selection

## Test Coverage

The test suite covers:
- ✅ Window specification parsing (all formats)
- ✅ Negative index resolution
- ✅ Window operations (move, swap, close)
- ✅ Session and window queries
- ✅ Error handling and edge cases
- ✅ FZF integration
- ✅ CLI command execution
- ✅ CLI argument parsing
- ✅ Exit codes and error messages

## Dependencies

Tests require:
- pytest
- unittest.mock (standard library)

Optional:
- pytest-cov (for coverage reports)

## Notes

- Tests use mocking to avoid requiring actual tmux installation
- Tests are designed to run quickly without external dependencies
- Integration tests can be added by removing mocks and testing with real tmux
