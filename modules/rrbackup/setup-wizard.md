# RRBackup Setup Wizard — Unified Specification

This document defines the **complete design and behavior** of the RRBackup system and its **interactive setup wizard**.  
It serves as the single source of truth for both human developers and LLM collaborators working on the project.

---

## Table of Contents
1. [Overview](#1-overview)
2. [Setup Wizard Flow](#2-setup-wizard-flow)
3. [Repository & Tool Setup (Restic + rclone)](#3-repository--tool-setup-restic--rclone)
4. [Backup Set Configuration](#4-backup-set-configuration)
5. [Scheduling](#5-scheduling)
6. [Retention & Size Budgets](#6-retention--size-budgets)
7. [Error Handling & Logging](#7-error-handling--logging)
8. [Configuration Schema](#8-configuration-schema)
9. [CLI Surface](#9-cli-surface)
10. [Implementation Notes for the LLM](#10-implementation-notes-for-the-llm)
11. [Appendix: Example Commands & Outputs](#11-appendix-example-commands--outputs)

---

## 1. Overview

**RRBackup** is a cross-platform, automated backup system built on **Restic** (for encrypted, deduplicated storage) and **rclone** (for cloud synchronization).  
It provides an interactive setup wizard to configure everything automatically—no manual repository or password setup required.

The system:
- Runs on **Windows 11**, **WSL2/Linux**, and **Termux**.
- Supports **Google Drive** (via `rclone`) and **local backup targets**.
- Manages **incremental, encrypted backups** using Restic.
- Automatically applies **retention policies** (daily/weekly/monthly/yearly + max size).
- Schedules recurring backups with system-native schedulers.
- Logs all operations and supports dry-run verification.

---

## 2. Setup Wizard Flow

The wizard must guide users through every step to create a functioning backup environment.  
It should be **fully interactive**, **idempotent**, and **safe by default**.

### Flow Overview

```
Welcome Screen
→ Verify Required Tools
→ Configure Repository Destination
→ Configure Restic Password File
→ Initialize Repository
→ Add Backup Sets (Loop)
→ Configure Schedule & Retention
→ Review & Save
→ Optional Initial Backup
→ Exit
```

### Step-by-Step Behavior

#### Step 1 — Welcome
Display a greeting and explain that RRBackup will:
- Configure all required tools (Restic, rclone)
- Create a secure encrypted repository
- Schedule automated incremental backups

Prompt: continue or exit.

---

#### Step 2 — Verify Required Tools
Check if `restic` and `rclone` executables exist (via `which`/`Get-Command`).
If missing:
- Offer auto-install:
  - Windows: `winget install restic.restic && winget install Rclone.Rclone`
  - Linux: `apt install restic rclone`
- Verify successful installation by running `restic version` and `rclone version`.

---

#### Step 3 — Configure Repository Destination
Prompt:
```
Where should backups be stored?
1) Google Drive (via rclone)
2) Local folder or drive
```

##### Option 1: Google Drive
1. Ask for rclone remote name (default: `gdrive`).
2. Verify access:
   ```bash
   rclone about gdrive:
   ```
3. If unauthorized:
   ```bash
   rclone config reconnect gdrive:
   ```
4. Ask for folder path (default `/backups/rrbackup`), then:
   ```bash
   rclone mkdir gdrive:/backups/rrbackup
   ```
5. Construct repository URL:
   ```
   rclone:gdrive:/backups/rrbackup
   ```

##### Option 2: Local Repository
Ask for path (e.g., `D:/Backups/rrbackup` or `/mnt/data/backups/rrbackup`).
Create folder if missing.  
Repository URL becomes that path.

---

#### Step 4 — Configure Restic Password File

- Auto-generate strong random password:
  ```python
  import uuid
  password = uuid.uuid4().hex
  ```
- Write to:
  - Windows: `%AppData%\rrbackup\restic_password.txt`
  - Linux/Termux: `~/.config/rrbackup/restic_password.txt`
- Set restrictive permissions:
  - Windows: `icacls <file> /inheritance:r /grant:r "<user>:R" /c`
  - Linux: `chmod 600 <file>`
- Do not log or display the password unless user explicitly requests.

---

#### Step 5 — Initialize Repository

Attempt:
```bash
restic -r <repo_url> snapshots
```

If the repository does not exist:
```bash
restic -r <repo_url> init
```

If initialization fails, log the error and retry once after 5 seconds.

---

#### Step 6 — Add Backup Sets (Loop)

Allow the user to define multiple backup jobs interactively.

**Prompt Sequence:**
1. Name of the backup set (e.g., “UserProfile”, “Pictures”).
2. Include directories (comma or newline separated).
3. Choose **exclusion profiles** (can combine multiple):
   - Developer cache/build
   - Common temp/cache
   - Media previews
   - Custom globs
4. Tags (default adds `host:<hostname>` automatically).
5. Cross-filesystem restriction (`--one-file-system` flag).
6. Retention counts and size limit (see section 6).
7. Scheduling (see section 5).
8. Ask to run dry-run immediately.

Repeat until the user declines to add more sets.

---

#### Step 7 — Review & Save Configuration

Display summary:
```
Repository: rclone:gdrive:/backups/rrbackup
Password file: C:/Users/mcarls/AppData/Roaming/rrbackup/restic_password.txt
Backup sets:
  - Pictures → D:/Pictures/, daily 02:00, keep 7/4/6/2, max 512GB
  - UserProfile → C:/Users/mcarls/, weekly Sun 03:00, keep 3/3/6/2, max 1TB
```

Ask:  
`Save configuration and create schedules? (Y/N)`

Write `config.toml` under state directory:
- Windows: `%AppData%\rrbackup\config.toml`
- Linux: `~/.config/rrbackup/config.toml`

---

#### Step 8 — Optional Initial Backup
Prompt:
```
Run an initial dry-run backup to verify configuration? (Y/N)
```

If yes:
```bash
restic -r <repo_url> backup <includes> --dry-run [--exclude ...]
```
If successful, offer to run a real first backup.

---

## 3. Repository & Tool Setup (Restic + rclone)

### Restic
- Handles encryption, deduplication, and incremental backups.
- Requires a password file for key derivation.
- Commands used:
  - `init`, `backup`, `snapshots`, `stats`, `forget`, `prune`, `check`, `unlock`.

### rclone
- Provides cloud storage interface.
- Must have an authenticated remote (`rclone config` or `rclone config reconnect`).
- Command verification:
  - `rclone about <remote>:`
  - `rclone mkdir <remote>:<folder>`
  - `rclone ls <remote>:<folder>`

The wizard must validate both before repository creation.

---

## 4. Backup Set Configuration

Each backup set defines:
- Name (unique key)
- Include paths
- Exclude patterns (chosen from templates or custom)
- Tags
- Retention (daily/weekly/monthly/yearly + size)
- Schedule (time/frequency)
- one_fs and dry-run defaults

Default exclusion templates include:

**Developer Cache/Build**
```
**/.git
**/.venv
**/node_modules
**/__pycache__
**/.pytest_cache
**/.mypy_cache
**/build
**/dist
**/*.egg-info
**/*.pyc
```

**Common Cache/Temp**
```
**/.cache/**
**/*.tmp
**/*.log
Thumbs.db
```

**Media Previews**
```
**/.thumbnails/**
**/*.lrdata/**
**/*.lrprev/**
```

**Windows User Caches**
```
C:/Users/<USER>/AppData/Local/**
C:/Users/<USER>/AppData/Temp/**
```

---

## 5. Scheduling

RRBackup must schedule backups automatically per set.

| Platform | Scheduler | Notes |
|-----------|------------|-------|
| Windows | Task Scheduler (`schtasks`) | Example:<br>`schtasks /Create /TN RRBackup\Pictures /TR "pwsh -NoProfile -File rrbackup.ps1 --run Pictures" /SC DAILY /ST 02:00` |
| Linux/WSL | `systemd --user` timers | Write `.service` + `.timer` files to `~/.config/systemd/user/` |
| Termux | `cronie` or Tasker integration | Use cron-style scheduling |

User can choose:
- Hourly (every N hours)
- Daily (time of day)
- Weekly (day + time)
- Monthly (day + time)
- Manual (no schedule)

All scheduler entries should call the program with:
```
rrbackup --run <setName>
```

---

## 6. Retention & Size Budgets

After each backup or on demand:
```bash
restic -r <repo> forget --prune --keep-daily N --keep-weekly N --keep-monthly N --keep-yearly N
```

Then check total size:
```bash
restic -r <repo> stats --json
```

If above configured max:
- List snapshots (`restic snapshots --json`).
- Delete oldest snapshots until below limit.
- Log which were removed.

The wizard should let users define both **count-based** and **size-based** policies interactively.

---

## 7. Error Handling & Logging

### Common Recovery Logic
| Condition | Response |
|------------|-----------|
| rclone 401/403 | Run `rclone config reconnect <remote>:` |
| Restic lock error | Run `restic unlock` and retry once |
| Network failure | Retry 3 times with exponential backoff |
| Disk full | Abort, log, and recommend pruning |

### Logging
- Store logs under `<state_dir>/logs/<setName>/YYYY/MM/DD/`.
- Record:
  - Timestamps
  - Executed commands (without secrets)
  - Duration, changed files, bytes added
  - Snapshot IDs, retention results
- Optional JSON logs for automation.

---

## 8. Configuration Schema

Example `config.toml`:
```toml
[repository]
url = "rclone:gdrive:/backups/rrbackup"
password_file = "C:/Users/<USER>/AppData/Roaming/rrbackup/restic_password.txt"

[restic]
bin = "restic"

[rclone]
bin = "rclone"

[retention_defaults]
keep_daily = 7
keep_weekly = 4
keep_monthly = 6
keep_yearly = 2
max_total_size = "1024GB"

[[backup_sets]]
name = "UserProfile"
include = ["C:/Users/<USER>/"]
exclude = ["**/.git", "**/.venv", "**/node_modules", "C:/Users/<USER>/AppData/Local/**"]
tags = ["host:<hostname>", "tier:important"]
schedule = { type = "daily", time = "02:00" }
retention = { keep_daily=7, keep_weekly=4, keep_monthly=6, keep_yearly=2, max_total_size="512GB" }
dry_run_default = false
```

---

## 9. Example Basic CLI Surface

| Flag | Long Form | Description |
|------|------------|-------------|
| `-w` | `--wizard` | Launch interactive setup wizard |
| `-c` | `--config` | Path to config file |
| `-a` | `--add-set` | Add a new backup set |
| `-l` | `--list-sets` | List configured sets |
| `-r` | `--run` | Run specific backup set |
| `-A` | `--run-all` | Run all sets |
| `-S` | `--schedule` | Install/update scheduler entries |
| `-R` | `--retention` | Apply pruning/retention now |
| `-n` | `--dry-run` | Simulate backup only |
| `-v` | `--verbose` | Verbose logs |
| `-j` | `--json-logs` | Emit structured JSON logs |
| `-p` | `--password-file` | Override password file |
| `-u` | `--repo` | Override repo URL |
| `-t` | `--tags` | Add extra tags to a run |

---

## 10. Implementation Notes for the LLM

1. Use `subprocess.run([...], env=custom_env, capture_output=True, text=True)` — never `shell=True`.
2. Normalize paths with `pathlib.Path` and `expanduser()`.
3. Convert human sizes (“512GB”, “1TB”) → bytes for comparison.
4. Wrap all subprocess calls in retry logic and safe error handling.
5. Log all activity to per-set logs.
6. Support both **interactive wizard** (`--wizard`) and **non-interactive** configuration file bootstrapping (`--config` only).
7. Ensure the wizard can rerun safely:
   - Detect existing repos/configs.
   - Skip redundant setup.
   - Update changed fields instead of overwriting entire files.
8. Secrets (passwords/tokens) must **never** appear in logs.

---

## 11. Appendix: Example Commands & Outputs

### Probe or Initialize Repository
```powershell
$env:RESTIC_PASSWORD_FILE="C:/Users/mcarls/AppData/Roaming/rrbackup/restic_password.txt"; restic -r rclone:gdrive:/backups/rrbackup snapshots || restic -r rclone:gdrive:/backups/rrbackup init
```

### Backup Example
```powershell
$env:RESTIC_PASSWORD_FILE="C:/Users/mcarls/AppData/Roaming/rrbackup/restic_password.txt"; restic -r rclone:gdrive:/backups/rrbackup backup "C:/Users/mcarls/" --exclude "**/.git" --exclude "**/.venv" --tag "host:Slice" --tag "tier:important"
```

### Apply Retention
```powershell
$env:RESTIC_PASSWORD_FILE="C:/Users/mcarls/AppData/Roaming/rrbackup/restic_password.txt"; restic -r rclone:gdrive:/backups/rrbackup forget --prune --keep-daily 7 --keep-weekly 4 --keep-monthly 6 --keep-yearly 2
```

### Expected Wizard End Message
```
✅ Restic repository created: rclone:gdrive:/backups/rrbackup
✅ Password stored at: C:/Users/mcarls/AppData/Roaming/rrbackup/restic_password.txt
✅ Config saved to: C:/Users/mcarls/AppData/Roaming/rrbackup/config.toml
✅ 2 backup sets created and scheduled
🕑 Daily backups start at 2:00 AM
🎉 Setup complete. Your backups will now run automatically!
```

---

**Deliverable:**  
A single wizard (`--wizard`) that performs **automated environment setup, repository creation, backup configuration, scheduling, and retention enforcement**—producing a fully functional, self-contained backup system after one interactive run.

