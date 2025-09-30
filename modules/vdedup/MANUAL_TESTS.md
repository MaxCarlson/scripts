# Manual/Interactive Tests

## Overview

The files `manual_test_*.py` are **interactive test scripts** for the UI components, not unit tests. They spawn background threads and use real-time displays, which can cause pytest to freeze.

## Available Manual Tests

### 1. Debug UI Test (`manual_test_debug_ui.py`)
Tests the ProgressReporter without UI enabled (debug mode).

```bash
python manual_test_debug_ui.py
```

**Purpose**: Verify that reporter updates work correctly without a UI.

### 2. Enhanced UI Test (`manual_test_enhanced_ui.py`)
Full interactive test of the enhanced UI with simulated pipeline stages.

```bash
# Default test
python manual_test_enhanced_ui.py

# Test different layouts
python manual_test_enhanced_ui.py --layouts
```

**Purpose**: Visually verify the complete UI experience including:
- File scanning stage
- Hashing stage with cache hits
- Metadata analysis
- pHash computation
- Final results display

### 3. Simple UI Test (`manual_test_simple_ui.py`)
Basic UI test with verbose logging.

```bash
python manual_test_simple_ui.py
```

**Purpose**: Debug UI updates with step-by-step logging.

## Why These Are Not Unit Tests

1. **Interactive**: Require visual inspection of the UI
2. **Long-running**: Use `time.sleep()` for realistic simulation
3. **Background threads**: Spawn dashboard threads that may not clean up in pytest
4. **Ctrl+C resistant**: Background threads can ignore interrupts

## Running Unit Tests

To run the actual unit tests (which don't include these files):

```bash
# Run all unit tests
pytest tests/

# Or from the modules directory
pytest modules/vdedup/tests/

# Verbose output
pytest tests/ -v
```

## Configuration

The `pyproject.toml` file is configured to exclude these manual tests:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "--ignore=manual_test_*.py"
timeout = 30
```

This ensures pytest only runs the actual unit tests in the `tests/` directory.

## Troubleshooting

### If pytest still freezes:
1. Ensure you're running pytest from the vdedup directory
2. Check that the manual test files start with `manual_test_` prefix
3. Run explicitly from tests directory: `pytest tests/`
4. Use timeout: `timeout 60 pytest tests/`

### If manual tests freeze:
1. Press Ctrl+C (may need multiple times)
2. Close the terminal window as last resort
3. Check that no background Python processes are running

## Development Notes

When developing new UI features:
1. Test manually with these scripts first
2. Then create unit tests in `tests/` that mock the UI
3. Never create interactive tests in the `tests/` directory
4. Always prefix manual test files with `manual_test_`
