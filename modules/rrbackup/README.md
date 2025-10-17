# RRBackup – Restic + Rclone Backup System

**Cross-platform backup solution using Restic for encrypted, deduplicated snapshots and Rclone for remote storage connectivity.**

## Features

- **Encrypted & Deduplicated**: Uses Restic for secure, efficient backups
- **Flexible Storage**: Support for local repos, rclone remotes (Google Drive, etc.)
- **Cross-Platform**: Windows 11 (PowerShell 7+), WSL2/Ubuntu, Android Termux
- **Config-Driven**: Simple TOML configuration for backup sets and retention policies
- **Observability**: Timestamped logs, PID tracking, progress monitoring
- **Easy Restore**: Built on Restic's proven restore capabilities

## Requirements

- **Python 3.9+**
- **Restic** binary on PATH ([install guide](https://restic.readthedocs.io/en/stable/020_installation.html))
- **Rclone** binary on PATH ([install guide](https://rclone.org/install/))

### Installation

#### Quick Install (from repository)

```bash
cd ~/Repos/scripts/modules/rrbackup
pip install -e .
```

#### Verify Installation

```bash
rrb --version
```

## Quick Start

### 1. Run Setup Wizard

Kick things off with the guided setup. It walks through configuration, password management, rclone connectivity, and restic repository initialization. Existing setups can be inspected or updated step by step.

```bash
rrb setup --wizard
```

Prefer to manage only the configuration file? You can still run the focused configuration wizard:

```bash
rrb config wizard
```

Prefer to edit manually? Create your config file at the platform-specific location:

- **Windows**: `%APPDATA%\rrbackup\config.toml`
- **Linux/WSL**: `~/.config/rrbackup/config.toml`
- **Termux**: `~/.config/rrbackup/config.toml`

See [examples/config.toml](examples/config.toml) for a complete example.

### 2. Setup Repository Password

Create a password file (recommended for security):

```bash
# Linux/WSL/Termux
mkdir -p ~/.config/rrbackup
echo "your-secure-password" > ~/.config/rrbackup/restic_password.txt
chmod 600 ~/.config/rrbackup/restic_password.txt
```

```powershell
# Windows PowerShell
$configDir = "$env:APPDATA\rrbackup"
New-Item -ItemType Directory -Force -Path $configDir
"your-secure-password" | Out-File -FilePath "$configDir\restic_password.txt" -NoNewline
```

### 3. Configure Rclone for Google Drive (Optional)

If using Google Drive as your backup destination:

```bash
rclone config
# Follow prompts:
# n) New remote
# name> gdrive
# Storage> drive (Google Drive)
# ... follow OAuth flow ...
```

Test connectivity:

```bash
rclone ls gdrive:
```

### 4. Initialize Repository

```bash
rrb setup
```

With remote connectivity check:

```bash
rrb setup --remote-check
```

### 5. Run Your First Backup

```bash
rrb backup --set local-c
```

## Configuration

### Minimal config.toml

```toml
[repository]
url = "rclone:gdrive:/backups/rrbackup"
password_file = "~/.config/rrbackup/restic_password.txt"

[retention]
keep_daily = 7
keep_weekly = 4
keep_monthly = 6
keep_yearly = 2

[[backup_sets]]
name = "documents"
include = [
  "~/Documents",
  "~/Pictures",
]
exclude = [
  "**/.cache",
  "**/node_modules",
]
tags = ["important"]
schedule = "daily 02:00"
backup_type = "incremental"
max_snapshots = 30
encryption = "repository-default"
compression = "auto"
```

See [examples/config.toml](examples/config.toml) for comprehensive options.

## Usage

### Commands

#### Setup and Initialize

```bash
# Initialize repository
rrb setup

# Initialize with connectivity check
rrb setup -r
```

#### Backup

```bash
# Run backup for a configured set
rrb backup --set documents

# Dry run (no changes)
rrb backup --set documents --dry-run

# Add extra tags
rrb backup --set documents -t "pre-upgrade"

# Add extra excludes
rrb backup --set documents -e "*.tmp" -e "*.log"
```

#### List Snapshots

```bash
# List all snapshots
rrb list

# Filter by path
rrb list --path ~/Documents

# Filter by tag
rrb list -t important

# Filter by host
rrb list -H win11-laptop
```

#### Repository Stats

```bash
# Show restore size and other stats
rrb stats
```

#### Integrity Check

```bash
# Verify repository integrity
rrb check
```

#### Prune (Apply Retention)

```bash
# Apply retention policy and prune old snapshots
rrb prune
```

#### Monitor Progress

```bash
# Show in-progress backups and locks
rrb progress
```

#### Restore (Manual)

Restic restore is powerful - use it directly:

```bash
# List snapshots to find ID
rrb list

# Restore specific snapshot
restic -r rclone:gdrive:/backups/rrbackup restore <snapshot-id> --target ~/restore

# Restore specific files
restic -r rclone:gdrive:/backups/rrbackup restore latest --target ~/restore --include "Documents/**"
```

## Configuration Reference

### Repository Backends

#### Google Drive (via rclone)

```toml
[repository]
url = "rclone:gdrive:/backups/rrbackup"
```

#### Local Directory

```toml
[repository]
url = "/mnt/backup-drive/restic-repo"
```

#### SFTP

```toml
[repository]
url = "sftp:user@host:/path/to/repo"
```

### Backup Sets

```toml
[[backup_sets]]
name = "critical-data"
include = [
  "~/Documents",
  "~/Projects",
]
exclude = [
  "**/.git",
  "**/.venv",
  "**/node_modules",
  "**/__pycache__",
]
tags = ["tier:critical", "host:laptop"]
one_fs = false            # Don't cross filesystem boundaries
dry_run_default = false   # Force dry-run by default
schedule = "weekdays 22:00"
backup_type = "incremental"
max_snapshots = 40
encryption = "repository-default"
compression = "max"
```

### Retention Policy

```toml
[retention]
keep_last = 5      # Keep last N snapshots
keep_hourly = 24   # Keep hourly for N hours
keep_daily = 7     # Keep daily for N days
keep_weekly = 4    # Keep weekly for N weeks
keep_monthly = 6   # Keep monthly for N months
keep_yearly = 2    # Keep yearly for N years
```

## Platform-Specific Notes

### Windows 11

- Use `%APPDATA%\rrbackup\config.toml` for configuration
- Logs stored in `%LOCALAPPDATA%\rrbackup\logs`
- Use PowerShell 7+ for best experience

### WSL2/Ubuntu

- Config: `~/.config/rrbackup/config.toml`
- Logs: `~/.cache/rrbackup/logs`
- Can backup both Linux and Windows files (via `/mnt/c/`)

### Android Termux

- Install dependencies: `pkg install python restic rclone`
- Config: `~/.config/rrbackup/config.toml`
- Note: Some filesystem features may not work (hardlinks, etc.)

## Troubleshooting

### Repository Already Exists

If `rrb setup` fails with "repository already exists", your repo is already initialized. Skip to `rrb backup`.

### Password Issues

Ensure your password file is readable and contains no trailing newlines:

```bash
# Check file
cat ~/.config/rrbackup/restic_password.txt | od -c

# Fix if needed
echo -n "your-password" > ~/.config/rrbackup/restic_password.txt
```

### Rclone Connectivity

Test rclone separately:

```bash
# Test list
rclone ls gdrive:/backups

# Test with verbose
rclone -vv ls gdrive:/backups
```

### Logs

Check timestamped logs in your state directory:

- Windows: `%LOCALAPPDATA%\rrbackup\logs`
- Linux: `~/.cache/rrbackup/logs`

```bash
# View latest log
ls -lt ~/.cache/rrbackup/logs | head -5
tail ~/.cache/rrbackup/logs/backup-documents-20250114-123456.log
```

## Development

### CLI Helpers

`rrb` includes interactive tooling to avoid editing TOML or shell scripts by hand:

```bash
rrb setup --wizard              # Full guided setup (config, passwords, rclone, restic)
rrb config wizard                 # Interactive setup wizard
rrb config show                   # Print current configuration
rrb config add-set --name docs \
    --include ~/Documents --include ~/Pictures \
    --schedule "daily 02:00" --max-snapshots 30
rrb config set --repo-url rclone:gdrive:/backups/rrbackup
rrb config retention --use-defaults
```

### Running Tests

```bash
pytest tests/ -v
```

### Installing in Development Mode

```bash
pip install -e .
```

## License

MIT

## Related Projects

- [Restic](https://restic.net/) - Fast, secure backup program
- [Rclone](https://rclone.org/) - Rsync for cloud storage
