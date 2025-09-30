# Pytest Freezing Issue - Fixed

## Problem

Pytest would intermittently freeze on the second test, making it difficult to cancel even with Ctrl+C. The freeze occurred approximately 50% of the time when running:

```bash
pytest modules/vdedup/
```

## Root Cause

The issue was caused by three **interactive UI test scripts** located in the root `vdedup/` directory:

1. `test_debug_ui.py`
2. `test_enhanced_ui.py`
3. `test_simple_ui.py`

These files:
- Are meant for **manual/interactive testing**, not automated unit tests
- Spawn background threads for the dashboard UI
- Use long `time.sleep()` calls (3-5 seconds)
- Don't properly clean up background threads in pytest context
- Make processes Ctrl+C resistant due to background thread handling

Pytest was collecting these as tests because they matched the `test_*.py` pattern, even though they were in the root directory (not `tests/`).

## Solution

### 1. Renamed Files
Renamed the interactive test scripts to use `manual_test_` prefix:
- `test_debug_ui.py` → `manual_test_debug_ui.py`
- `test_enhanced_ui.py` → `manual_test_enhanced_ui.py`
- `test_simple_ui.py` → `manual_test_simple_ui.py`

### 2. Updated pytest Configuration
Modified `pyproject.toml` to explicitly ignore these files:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py", "*_test.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
# Exclude manual/interactive UI test scripts (renamed with manual_ prefix)
addopts = "--ignore=manual_test_*.py"
timeout = 30
```

### 3. Added Documentation
Created `MANUAL_TESTS.md` with instructions for:
- How to run the manual tests
- Why they're separate from unit tests
- How to troubleshoot if issues occur

## Verification

After the fix, pytest:
- **Collects**: 52 tests (only from `tests/` directory)
- **Ignores**: 3 manual test scripts
- **Runs**: Consistently without freezing
- **Performance**: ~1.36 seconds

```bash
$ cd modules/vdedup
$ pytest tests/ -q
....................................................                [100%]
52 passed, 1 warning in 1.36s
```

## Running Manual Tests

To run the interactive UI tests manually:

```bash
# Debug test (no UI)
python manual_test_debug_ui.py

# Enhanced UI test
python manual_test_enhanced_ui.py

# Simple UI test
python manual_test_simple_ui.py

# Test different layouts
python manual_test_enhanced_ui.py --layouts
```

## Best Practices

1. **Never put interactive tests in `tests/` directory**
2. **Use `manual_test_` prefix for interactive test scripts**
3. **Configure pytest to ignore manual tests explicitly**
4. **Document manual tests separately**
5. **Mock UI components in actual unit tests**

## Related Files

- `pyproject.toml`: Pytest configuration
- `MANUAL_TESTS.md`: Documentation for manual tests
- `tests/`: Directory containing actual unit tests
- `manual_test_*.py`: Interactive test scripts (3 files)

## Future Prevention

To prevent similar issues:
1. Keep interactive tests in a separate `manual_tests/` directory, or
2. Always use non-`test_` prefixes for manual scripts
3. Add pytest timeouts to catch hanging tests
4. Document which files are for manual testing
