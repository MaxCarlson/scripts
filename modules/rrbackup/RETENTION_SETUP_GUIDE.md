# Backup Retention Setup Guide

## Your Retention Strategy

**Goal**: Keep different snapshot frequencies for long-term backup coverage
- **5 weekly backups** - Last 5 weeks of weekly snapshots
- **12 monthly backups** - Last year of monthly snapshots
- **10 yearly backups** - Last 10 years of yearly snapshots

This gives you:
- Recent history (weeks) for quick recovery
- Medium-term history (months) for project milestones
- Long-term archive (years) for historical reference

---

## Method 1: Using the Config Wizard (Easiest)

### Step 1: Run Interactive Setup

```bash
rrb config wizard --initialize-repo
```

The wizard will ask:
1. **Repository location**: Choose local path or Google Drive
   - Local (faster): `C:/Users/mcarls/restic-backup-repo`
   - Google Drive: `rclone:gdrive:/backups/rrbackup`

2. **Password file**: Create password file first (see below)
   - Windows: `C:/Users/mcarls/AppData/Roaming/rrbackup/restic_password.txt`

3. **Retention policy**: Enter your values
   - Weekly: `5`
   - Monthly: `12`
   - Yearly: `10`
   - Daily/Hourly: Leave blank or `0` (we're keeping weekly/monthly/yearly only)

4. **Backup sets**: Define what to back up
   - Name: `documents`
   - Paths: `C:/Users/mcarls/Documents`, `C:/Users/mcarls/Pictures`
   - Schedule: `daily 02:00` (human-readable, for reference)
   - Max snapshots: `30` (keeps last 30 snapshots regardless of age)

### Step 2: Create Password File

**Before running the wizard**, create your password file:

```powershell
# PowerShell - creates directory and password file
$configDir = "$env:APPDATA\rrbackup"
New-Item -ItemType Directory -Force -Path $configDir | Out-Null

# Generate secure random password or use your own
$password = "your-very-secure-backup-password-here"
$password | Out-File -FilePath "$configDir\restic_password.txt" -NoNewline -Encoding utf8

Write-Host "Password file created: $configDir\restic_password.txt"
Write-Host "IMPORTANT: Save this password in your password manager!"
```

**CRITICAL**: Store this password securely! Without it, your backups are unrecoverable.

---

## Method 2: Manual Configuration

### Step 1: Create Config File

Edit: `C:\Users\mcarls\AppData\Roaming\rrbackup\config.toml`

```toml
[repository]
# Choose ONE repository type:

# Option A: Local repository (faster backups)
url = "C:/Users/mcarls/restic-backup-repo"

# Option B: Google Drive (requires rclone setup)
# url = "rclone:gdrive:/backups/rrbackup"

password_file = "C:/Users/mcarls/AppData/Roaming/rrbackup/restic_password.txt"

[restic]
bin = "restic"

[rclone]
bin = "rclone"

[retention]
# Your retention strategy: 5 weekly, 12 monthly, 10 yearly
keep_weekly = 5
keep_monthly = 12
keep_yearly = 10

# Optional: Keep last N snapshots regardless of date
# keep_last = 30

[[backup_sets]]
name = "documents"
include = [
    "C:/Users/mcarls/Documents",
    "C:/Users/mcarls/Pictures",
]
exclude = [
    "**/.git",
    "**/.venv",
    "**/node_modules",
    "**/__pycache__",
    "**/.cache",
    "**/*.tmp",
    "**/*.log",
]
tags = ["tier:important", "host:win11"]
one_fs = false
dry_run_default = false
schedule = "daily 02:00"
max_snapshots = 30

[[backup_sets]]
name = "repos"
include = [
    "C:/Users/mcarls/Repos",
]
exclude = [
    "**/.git",
    "**/.venv",
    "**/node_modules",
    "**/__pycache__",
    "**/.cache",
    "**/build",
    "**/dist",
    "**/*.egg-info",
]
tags = ["tier:code", "host:win11"]
one_fs = false
dry_run_default = false
schedule = "weekdays 23:00"
max_snapshots = 14
```

### Step 2: Create Repository Directory (if local)

```bash
mkdir -p "C:/Users/mcarls/restic-backup-repo"
```

### Step 3: Initialize Repository

```bash
rrb setup
```

---

## Understanding Retention Policy

### How Restic Retention Works

When you run `rrb prune`, restic keeps:
1. **Weekly snapshots**: One snapshot per week for the last 5 weeks
2. **Monthly snapshots**: One snapshot per month for the last 12 months
3. **Yearly snapshots**: One snapshot per year for the last 10 years

**Example timeline** (assuming daily backups):
```
Today:        All snapshots kept (within 5 weeks)
5 weeks ago:  Only 1 snapshot per week kept
12 months ago: Only 1 snapshot per month kept
10 years ago: Only 1 snapshot per year kept
10+ years:    Deleted
```

### Your Retention Schedule

With `keep_weekly=5, keep_monthly=12, keep_yearly=10`:

| Time Range      | Snapshots Kept          | Example                           |
|-----------------|-------------------------|-----------------------------------|
| Last 5 weeks    | 1 per week (5 total)    | Oct 13, Oct 6, Sep 29, Sep 22...  |
| Last 12 months  | 1 per month (12 total)  | Oct 2024, Sep 2024, Aug 2024...   |
| Last 10 years   | 1 per year (10 total)   | 2024, 2023, 2022, ..., 2015       |
| Older than 10y  | Deleted by prune        | —                                 |

**Total snapshots**: Roughly 27 snapshots retained (5 + 12 + 10, minus overlaps)

---

## Running Your First Backups

### 1. Test Configuration

```bash
# Verify config is valid
rrb config show

# List configured backup sets
rrb config list-sets
```

### 2. Dry Run First

```bash
# Test documents backup (no actual changes)
rrb backup --set documents --dry-run

# Test repos backup
rrb backup --set repos --dry-run
```

### 3. Run Actual Backups

```bash
# Backup documents
rrb backup --set documents

# Backup repos
rrb backup --set repos
```

### 4. Verify Snapshots

```bash
# List all snapshots
rrb list

# Show repository stats
rrb stats

# Check repository integrity
rrb check
```

---

## Understanding max_snapshots

The `max_snapshots` field in each backup set provides an **additional safety net**:

```toml
max_snapshots = 30  # Always keep at least last 30 snapshots
```

This works **alongside** your retention policy:
- If you have 30+ snapshots, retention policy applies (5 weekly, 12 monthly, 10 yearly)
- If you have < 30 snapshots, ALL are kept regardless of age
- Protects against accidentally deleting all snapshots

**Recommendation**:
- `max_snapshots = 30` for important daily backups (documents)
- `max_snapshots = 14` for less frequent backups (repos)

---

## Applying Retention (Pruning)

### When to Prune

Prune after you have accumulated multiple snapshots (e.g., after 2-3 weeks of daily backups):

```bash
# Apply retention policy and remove old snapshots
rrb prune
```

**What happens**:
1. Restic identifies snapshots to keep (based on your retention policy)
2. Marks other snapshots for deletion
3. Removes data that's no longer referenced
4. Frees up disk space

### Prune Schedule

- **Weekly**: Run `rrb prune` once a week
- **Monthly**: After creating monthly backups
- **After major changes**: After big deletions or reorganizations

### Safe Pruning

The `forget --prune` command is **safe** if:
- You've tested your retention policy (see below)
- You have backups in multiple locations (local + Google Drive)
- You've verified snapshots before pruning (`rrb list`)

---

## Testing Your Retention Policy

### Simulate Retention Without Deleting

```bash
# See what WOULD be kept/deleted (dry run)
restic -r C:/Users/mcarls/restic-backup-repo forget \
    --keep-weekly 5 \
    --keep-monthly 12 \
    --keep-yearly 10 \
    --dry-run
```

This shows:
- ✅ Snapshots that will be **kept**
- ❌ Snapshots that will be **removed**

**Review carefully** before running `rrb prune`!

### Create Test Backups

To test your retention policy with real data:

1. Create multiple backup snapshots over time
2. Review what would be pruned: `rrb prune --dry-run` (if implemented)
3. Apply prune: `rrb prune`
4. Verify kept snapshots: `rrb list`

---

## Google Drive Setup (Optional)

### Option 1: Direct Google Drive Backend

**Pros**: Simple, all backups go directly to cloud
**Cons**: Slower, requires OAuth token refresh

```bash
# Refresh rclone token
rclone config reconnect gdrive:

# Create backup directory
rclone mkdir gdrive:/backups/rrbackup

# Update config
rrb config set --repo-url "rclone:gdrive:/backups/rrbackup"

# Initialize and test
rrb setup --remote-check
rrb backup --set documents --dry-run
```

### Option 2: Local + Sync to Google Drive (Recommended)

**Pros**: Fast backups, no OAuth issues during backup
**Cons**: Two-step process (backup then sync)

```toml
[repository]
url = "C:/Users/mcarls/restic-backup-repo"
```

**After backups, sync to cloud**:
```bash
rclone sync C:/Users/mcarls/restic-backup-repo gdrive:/backups/rrbackup -P
```

**Automate with PowerShell script** (`sync-backups.ps1`):
```powershell
# Run backups
rrb backup --set documents
rrb backup --set repos

# Sync to Google Drive
rclone sync C:/Users/mcarls/restic-backup-repo gdrive:/backups/rrbackup -P --exclude "locks/**"

if ($LASTEXITCODE -eq 0) {
    Write-Host "✓ Backups synced to Google Drive"
} else {
    Write-Host "✗ Sync failed"
    exit 1
}
```

---

## Scheduling Automated Backups

### Windows Task Scheduler

1. Open Task Scheduler
2. Create Basic Task: "RRBackup Daily Documents"
3. Trigger: **Daily at 2:00 AM**
4. Action: Start a program
   - Program: `rrb`
   - Arguments: `backup --set documents`

5. Create another task: "RRBackup Nightly Repos"
   - Trigger: **Daily at 11:00 PM** (or weekdays only)
   - Action: `rrb backup --set repos`

6. Create weekly prune task: "RRBackup Weekly Prune"
   - Trigger: **Weekly on Sunday at 3:00 AM**
   - Action: `rrb prune`

### PowerShell Script for All Backups

Create `daily-backup.ps1`:
```powershell
# Daily backup script
$ErrorActionPreference = "Stop"

Write-Host "Starting RRBackup..."

# Run backups
rrb backup --set documents
rrb backup --set repos

# Apply retention (weekly)
$dayOfWeek = (Get-Date).DayOfWeek
if ($dayOfWeek -eq "Sunday") {
    Write-Host "Running weekly prune..."
    rrb prune
}

# Optional: Sync to Google Drive
# rclone sync C:/Users/mcarls/restic-backup-repo gdrive:/backups/rrbackup -P

Write-Host "Backup complete!"
```

Schedule this single script daily at 2:00 AM.

---

## Monitoring & Maintenance

### Check Backup Health

```bash
# View recent snapshots
rrb list | head -10

# Check repository stats
rrb stats

# Verify integrity (run monthly)
rrb check
```

### Review Logs

```bash
# Windows PowerShell
ls $env:LOCALAPPDATA\rrbackup\logs | sort -desc | select -first 5
cat $env:LOCALAPPDATA\rrbackup\logs\backup-documents-<timestamp>.log
```

### What to Monitor

- ✅ Backups running on schedule
- ✅ No error logs
- ✅ Repository growing (indicates new data being backed up)
- ✅ Retention working (old snapshots being pruned)
- ✅ Google Drive sync working (if using Option 2)

---

## Quick Reference

```bash
# Setup
rrb config wizard --initialize-repo
rrb setup

# Daily operations
rrb backup --set documents
rrb backup --set repos
rrb list

# Weekly maintenance
rrb prune
rrb stats

# Monthly health check
rrb check

# Restore
rrb list --tag important
restic -r <repo-url> restore <snapshot-id> --target C:/restore

# Config management
rrb config show
rrb config list-sets
rrb config add-set --name photos --include ~/Pictures --schedule "daily 03:00"
```

---

## Summary Checklist

- [ ] Password file created and stored in password manager
- [ ] Config file created with retention policy (5 weekly, 12 monthly, 10 yearly)
- [ ] Repository initialized (`rrb setup`)
- [ ] First backup completed successfully
- [ ] Snapshots verified (`rrb list`)
- [ ] Integrity check passed (`rrb check`)
- [ ] Prune tested (after accumulating snapshots)
- [ ] Google Drive configured (optional)
- [ ] Scheduled backups configured
- [ ] Restore tested from a snapshot

---

## Need Help?

See also:
- `README.md` - Full user guide
- `SETUP_INSTRUCTIONS.md` - Detailed setup steps
- `GOOGLE_DRIVE_SETUP.md` - Google Drive configuration
- `summary-todo2.md` - Technical details and architecture
