# Testing Documentation

## Running Tests

```bash
# Run all tests
cd argparse_enforcer
python -m pytest tests/ -v

# Run specific test class
python -m pytest tests/test_enforcer.py::TestArgumentNamingConventions -v

# Run with coverage
python -m pytest tests/ --cov=argparse_enforcer --cov-report=html
```

## Test Coverage

The test suite includes 37 comprehensive tests covering:

### 1. Argument Naming Conventions (12 tests)
- Valid single-char abbreviated forms
- Valid full-length formats
- Rejection of missing forms
- Rejection of invalid characters
- Duplicate character detection
- Positional argument passthrough

### 2. Two-Character Abbreviated Rules (4 tests)
- Rejection before threshold
- Allowance after threshold
- Allowance when all single chars exhausted
- Custom threshold configuration

### 3. Argument Parsing (6 tests)
- Simple argument parsing
- Boolean flags
- Choices validation
- Default values
- Multiple values (nargs)
- Positional + optional arguments

### 4. Argcomplete Integration (4 tests)
- Default enabled state
- Disabled state
- parse_args() with autocomplete
- parse_known_args() with autocomplete

### 5. Cross-Platform Compatibility (3 tests)
- Parser creation
- Help generation
- Clear error messages

### 6. Edge Cases (6 tests)
- Empty parser
- Help-only parser
- Metavar support
- Custom dest support
- Mutually exclusive groups
- Subparsers support

### 7. Real-World Scenarios (2 tests)
- File processor CLI
- Server configuration CLI

## Cross-Platform Testing

The module has been designed and tested for:

### Windows 11 / PowerShell 7+
```powershell
# Run tests
python -m pytest tests/ -v

# Test example
python example.py -f test.txt -v --format json

# View setup instructions
python -m argparse_enforcer
```

### Windows / PowerShell 5.1
- Limited argcomplete support
- Core functionality works
- Consider upgrading to PowerShell 7+ for full features

### Ubuntu Linux (bash/zsh)
```bash
# Run tests
python3 -m pytest tests/ -v

# Test example
python3 example.py -f test.txt -v --format json

# View setup instructions
python3 -m argparse_enforcer
```

### macOS (bash/zsh)
```bash
# Run tests
python3 -m pytest tests/ -v

# Test example
python3 example.py -f test.txt -v --format json

# View setup instructions
python3 -m argparse_enforcer
```

## Manual Testing Checklist

- [ ] Parser creation with default settings
- [ ] Parser creation with custom threshold
- [ ] Adding arguments with valid conventions
- [ ] Error handling for invalid conventions
- [ ] Help text generation
- [ ] Argument parsing (abbreviated form)
- [ ] Argument parsing (full form)
- [ ] Setup instructions display for your platform
- [ ] Example script execution
- [ ] Tab completion (if argcomplete installed)

## Known Limitations

1. **PowerShell 5.1**: Limited argcomplete support. Use PowerShell 7+ or WSL.

2. **Help argument conflict**: Built-in `-h/--help` is exempt from naming conventions to avoid conflicts with argparse's default help.

3. **Subparsers**: Subparser commands return regular ArgumentParser instances and don't enforce conventions on subcommands.

## Continuous Integration

For CI/CD pipelines, use:

```yaml
# Example GitHub Actions
- name: Run tests
  run: |
    pip install pytest pytest-cov
    cd modules/argparse_enforcer
    pytest tests/ --cov=argparse_enforcer --cov-report=xml
```

## Troubleshooting

### Tests fail with "argcomplete not installed"
This is expected. The module gracefully handles missing argcomplete. Tests suppress this warning via conftest.py.

### Tests fail with `-h` conflicts
Make sure you're using `add_help=False` in tests when using `-h` for custom arguments.

### Import errors
Ensure you're in the correct directory and the module is installed or the parent directory is in PYTHONPATH:
```bash
export PYTHONPATH=/path/to/scripts/modules:$PYTHONPATH
```
