# Google Drive Setup Guide for RRBackup

## Reconnect Expired Token

If you see an "invalid_grant" or "token expired" error:

```bash
rclone config reconnect gdrive:
```

This will open a browser window for you to re-authenticate with Google.

## Fresh Setup (if needed)

If you need to set up Google Drive from scratch:

### 1. Start Rclone Config

```bash
rclone config
```

### 2. Create New Remote

```
n) New remote
name> gdrive
Storage> drive
```

### 3. Configure OAuth

```
client_id> (press Enter for default)
client_secret> (press Enter for default)
scope> 1 (Full access)
root_folder_id> (press Enter for default)
service_account_file> (press Enter for default)
```

### 4. Advanced Config

```
Edit advanced config? (y/n) n
Use auto config? (y/n) y
```

This will open your browser for OAuth authentication.

### 5. Verify Setup

```bash
rclone lsd gdrive:
```

You should see your Google Drive folders listed.

## Create Backup Directory

Create a directory in Google Drive for your backups:

```bash
rclone mkdir gdrive:/backups
rclone mkdir gdrive:/backups/rrbackup
```

## Test Connectivity

```bash
# List folders
rclone lsd gdrive:/backups

# Test write
echo "test" | rclone rcat gdrive:/backups/test.txt
rclone cat gdrive:/backups/test.txt
rclone delete gdrive:/backups/test.txt
```

## Update Your config.toml

Once Google Drive is working, update your `config.toml`:

```toml
[repository]
url = "rclone:gdrive:/backups/rrbackup"
password_file = "~/.config/rrbackup/restic_password.txt"
```

## Alternative: Local Repo + Rclone Sync

If you prefer to keep your primary repo local (faster backups), you can sync it to Google Drive as an offsite copy:

**config.toml:**
```toml
[repository]
url = "C:/Users/mcarls/restic-repo"
password_file = "~/.config/rrbackup/restic_password.txt"
```

**Manual sync to Google Drive:**
```bash
# After backups complete
rclone sync C:/Users/mcarls/restic-repo gdrive:/backups/rrbackup -P
```

This approach gives you:
- Fast local backups
- Offsite copy on Google Drive
- No OAuth token expiration issues during backups

## Troubleshooting

### Token Refresh Fails

If `rclone config reconnect` fails, delete and recreate the remote:

```bash
rclone config delete gdrive
rclone config create gdrive drive
```

### Rate Limits

If you hit Google API rate limits, wait a few minutes or use:

```bash
rclone --drive-chunk-size 128M --transfers 1 ...
```

### Permissions

Ensure the Google account has enough storage space. Check quota:

```bash
rclone about gdrive:
```
