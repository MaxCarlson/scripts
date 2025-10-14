# RRBackup Setup Instructions

## Quick Start (Local Repository)

### 1. Run the Setup Wizard

Launch the guided configuration flow. It will help you choose where to store backups (local drive or Google Drive via rclone), configure encryption, retention defaults, and define one or more backup sets (including schedules, number of copies, compression preferences, etc.).

```bash
rrb config wizard --initialize-repo
```

The `--initialize-repo` flag runs `restic init` immediately after the configuration is saved. Omit it if you plan to initialize later.

Prefer to do things manually? Follow the steps below.

### 1a. Create Password File

```powershell
# PowerShell
$password = Read-Host -Prompt "Enter a secure password for your backups" -AsSecureString
[Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($password)) | Out-File -FilePath "$env:APPDATA\rrbackup\restic_password.txt" -NoNewline
```

Or manually create: `C:\Users\mcarls\AppData\Roaming\rrbackup\restic_password.txt`

**IMPORTANT**: Store this password securely! Without it, your backups cannot be restored.

### 2. Review Configuration

Edit: `C:\Users\mcarls\AppData\Roaming\rrbackup\config.toml`

Customize:
- Repository location
- Backup sets (what to back up)
- Exclude patterns
- Retention policy

### 3. Create Repository Directory

```bash
mkdir -p C:/Users/mcarls/restic-backup-repo
```

### 4. Initialize Repository

```bash
rrb setup
```

### 5. Run First Backup

```bash
# Dry run first (no changes)
rrb backup --set documents --dry-run

# Actual backup
rrb backup --set documents
```

### 6. Verify Backup

```bash
rrb list
rrb stats
rrb check
```

## Google Drive Setup (Optional)

### Option A: Direct Google Drive Backend

1. **Refresh rclone token:**
   ```bash
   rclone config reconnect gdrive:
   ```

2. **Create backup directory:**
   ```bash
   rclone mkdir gdrive:/backups
   rclone mkdir gdrive:/backups/rrbackup
   ```

3. **Update config.toml:**
   ```toml
   [repository]
   url = "rclone:gdrive:/backups/rrbackup"
   ```

4. **Initialize and test:**
   ```bash
   rrb setup --remote-check
   rrb backup --set documents --dry-run
   ```

### Option B: Local Repo + Manual Sync (Recommended)

Advantages:
- Faster backups (no network delays)
- No OAuth token issues during backups
- Offsite copy on Google Drive

1. **Use local repository** (already configured)

2. **After backups, sync to Google Drive:**
   ```bash
   rclone sync C:/Users/mcarls/restic-backup-repo gdrive:/backups/rrbackup -P --exclude "locks/**"
   ```

3. **Optional: Create sync script** (`sync-to-gdrive.ps1`):
   ```powershell
   # Sync local restic repo to Google Drive
   rclone sync C:/Users/mcarls/restic-backup-repo gdrive:/backups/rrbackup -P --exclude "locks/**"
   if ($LASTEXITCODE -eq 0) {
       Write-Host "✓ Backup synced to Google Drive successfully"
   } else {
       Write-Host "✗ Sync failed with exit code $LASTEXITCODE"
   }
   ```

## Daily Workflow

### Manual Backups

```bash
# Documents
rrb backup --set documents

# Code repositories
rrb backup --set repos

# Check status
rrb list
rrb progress
```

### Maintenance

```bash
# Weekly: Check integrity
rrb check

# Monthly: Apply retention policy
rrb prune

# Check space usage
rrb stats
```

## Scheduling (Windows Task Scheduler)

### Create Backup Task

1. Open Task Scheduler
2. Create Basic Task: "RRBackup Daily"
3. Trigger: Daily at 2:00 AM
4. Action: Start a program
   - Program: `rrb`
   - Arguments: `backup --set documents`
   - Start in: `C:\Users\mcarls`

### Create Prune Task

1. Create Basic Task: "RRBackup Prune"
2. Trigger: Weekly on Sunday at 3:00 AM
3. Action: `rrb prune`

## Restore Examples

### List Available Snapshots

```bash
rrb list
rrb list --tag important
rrb list --path Documents
```

### Restore Files

```bash
# Restore latest snapshot to directory
restic -r C:/Users/mcarls/restic-backup-repo restore latest --target C:/Users/mcarls/restore

# Restore specific files
restic -r C:/Users/mcarls/restic-backup-repo restore latest --target C:/Users/mcarls/restore --include "Documents/important-file.docx"

# Restore specific snapshot
restic -r C:/Users/mcarls/restic-backup-repo restore 03dfbf52 --target C:/Users/mcarls/restore
```

### Restore from Google Drive

```bash
# If using direct Google Drive backend
restic -r rclone:gdrive:/backups/rrbackup restore latest --target C:/Users/mcarls/restore

# If using synced repo, first sync down
rclone sync gdrive:/backups/rrbackup C:/Users/mcarls/restic-backup-repo-restored -P
restic -r C:/Users/mcarls/restic-backup-repo-restored restore latest --target C:/Users/mcarls/restore
```

## Troubleshooting

### Repository Not Found

Ensure:
- Repository directory exists
- Config file path is correct
- You ran `rrb setup` first

### Password Issues

- Check file exists: `C:\Users\mcarls\AppData\Roaming\rrbackup\restic_password.txt`
- No trailing newlines in password file
- File is readable

### Google Drive Token Expired

```bash
rclone config reconnect gdrive:
```

### Check Logs

```bash
# View latest logs
ls C:\Users\mcarls\AppData\Local\rrbackup\logs | sort -r | head -5
tail C:\Users\mcarls\AppData\Local\rrbackup\logs\<log-file>
```

## Best Practices

1. **Test restores regularly** - Backups are useless if you can't restore
2. **Monitor backup logs** - Check for errors
3. **Keep password secure** - Store in password manager
4. **3-2-1 rule**: 3 copies, 2 different media, 1 offsite (Google Drive)
5. **Run `rrb check`** monthly to verify integrity
6. **Apply retention** with `rrb prune` to manage storage

## Configuration Files

- **Main config**: `%APPDATA%\rrbackup\config.toml`
- **Password**: `%APPDATA%\rrbackup\restic_password.txt`
- **Logs**: `%LOCALAPPDATA%\rrbackup\logs\`
- **State**: `%LOCALAPPDATA%\rrbackup\`

## Next Steps

1. ✅ Module installed (`pip install -e .`)
2. ⬜ Create password file
3. ⬜ Customize config.toml
4. ⬜ Run `rrb setup`
5. ⬜ Test with dry-run: `rrb backup --set documents -n`
6. ⬜ Run actual backup
7. ⬜ Test restore
8. ⬜ Setup Google Drive sync (optional)
9. ⬜ Schedule automated backups
