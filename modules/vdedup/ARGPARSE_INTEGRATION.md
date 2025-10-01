# Argparse Enforcer Integration

## Overview

The vdedup module has been integrated with the `argparse_enforcer` module to provide:
- Consistent argument naming conventions
- Automatic tab completion support (when argcomplete is installed)
- Better cross-platform compatibility

## Changes

### Import Changes

```python
# New import with fallback
try:
    from argparse_enforcer import EnforcedArgumentParser
    ENFORCER_AVAILABLE = True
except ImportError:
    EnforcedArgumentParser = argparse.ArgumentParser
    ENFORCER_AVAILABLE = False
```

### Parser Creation

```python
# Old
p = argparse.ArgumentParser(...)

# New
p = EnforcedArgumentParser(...)
```

## Argument Naming Conventions

All arguments already follow the enforced conventions:

### Abbreviated Form
- Single dash + single character: `-p`, `-r`, `-q`, `-o`, `-t`, `-g`, `-L`

### Full Form
- Double dash + lowercase + dash-separated: `--pattern`, `--recursive`, `--quality`, `--output-dir`, `--threads`, `--gpu`, `--live`

## Tab Completion

### Installation

```bash
pip install argcomplete
```

### Setup Instructions

Run to see platform-specific instructions:
```bash
python -m argparse_enforcer
```

### For Bash

Add to `~/.bashrc`:
```bash
eval "$(register-python-argcomplete video-dedupe)"
```

### For Zsh

Add to `~/.zshrc`:
```bash
autoload -U bashcompinit
bashcompinit
eval "$(register-python-argcomplete video-dedupe)"
```

### For PowerShell 7+

Add to `$PROFILE`:
```powershell
Register-ArgumentCompleter -Native -CommandName video-dedupe -ScriptBlock {
    param($wordToComplete, $commandAst, $cursorPosition)
    $env:_ARGCOMPLETE = 1
    $env:_ARGCOMPLETE_SHELL = 'powershell'
    $env:_ARGCOMPLETE_SUPPRESS_SPACE = 1
    $env:COMP_LINE = $commandAst.ToString()
    $env:COMP_POINT = $cursorPosition
    python -m vdedup.video_dedupe 8>&1 9>&1 |
        ForEach-Object { [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterValue', $_) }
}
```

## Backward Compatibility

- If `argparse_enforcer` is not installed, the module falls back to standard `argparse.ArgumentParser`
- All existing command-line arguments remain unchanged
- No breaking changes to the API

## Testing

Test the integration:

```bash
# Help text (should show argcomplete note if not installed)
python video_dedupe.py --help

# Valid command
python video_dedupe.py /path/to/videos -q 2 -t 4 -o /output

# Tab completion (if argcomplete installed)
python video_dedupe.py --<TAB>
```

## Benefits

1. **Consistent naming**: All arguments follow `-x, --full-name` convention
2. **Tab completion**: Automatic support when argcomplete is installed
3. **Cross-platform**: Works on Windows, Linux, and macOS
4. **User-friendly**: Shows helpful messages if argcomplete is not installed
5. **No breaking changes**: Fully backward compatible
