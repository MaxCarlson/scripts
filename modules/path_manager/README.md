<!-- version: 0.1.6 -->
# Path Manager

Cross-platform PATH utilities with Windows registry support.

Legacy entry point: `pwsh/pwsh_pathmgr.py` remains available, but `pathmgr` is the new preferred CLI.

## CLI

Mutating commands default to dry-run. Use `-a/--apply` to write changes.

- `pathmgr list -m lines`
- `pathmgr add -p C:\\Tools -y`
- `pathmgr restore -i PATH-ALL-20240101-120000.json -a -y`
- `pathmgr check -t C:\\Tools`
- `pathmgr duplicates`
- `pathmgr promote -c git -p C:\\Program Files\\Git\\cmd -a -y`

Run `pathmgr -h` for full usage.
