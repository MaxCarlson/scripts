# argparse-enforcer

Lightweight argparse wrapper that enforces strict argument naming conventions.

## Conventions

- **Abbreviated form**: Single dash + single character (e.g., `-f`, `-F`)
- **Full form**: Double dash + words separated by dashes (e.g., `--full-length`)
- **Two-char abbreviated**: Allowed when >15 args or all single chars exhausted

## Usage

```python
from argparse_enforcer import EnforcedArgumentParser

# argcomplete is automatically setup when parse_args() is called
parser = EnforcedArgumentParser(description="Example CLI")

# Valid arguments - both forms required
parser.add_argument("-f", "--full-length", help="Example argument")
parser.add_argument("-F", "--full", help="Another argument")
parser.add_argument("-o", "--output-file", help="Output file")

# argcomplete is automatically configured if installed
args = parser.parse_args()
```

## Disable autocomplete

```python
parser = EnforcedArgumentParser(
    description="Example CLI",
    enable_autocomplete=False  # Disable automatic argcomplete setup
)
```

## Setup Instructions

To enable tab completion:
```bash
# Install argcomplete
pip install argcomplete

# View platform-specific setup instructions
python -m argparse_enforcer

# Check if argcomplete is installed
python -c "from argparse_enforcer import print_quick_status; print_quick_status()"
```

## Examples

Valid:
- `-f, --full-length`
- `-F, --full`
- `-o, --output-file`

Invalid:
- `-foo, --full` (abbreviated too long before threshold)
- `-f, --Full` (full form must be lowercase)
- `-f, --full_length` (must use dashes not underscores)
- `-1, --full` (abbreviated must be alphabetic)

## Cross-Platform Support

Tested on:
- Windows 11 with PowerShell 7+
- Windows with PowerShell 5.1
- Ubuntu Linux (bash/zsh)
- macOS (bash/zsh)

See `example.py` for a complete working example.
