# RRBackup – Restic + Rclone Backup System (Project Brief & Task Board)

## Purpose
Build a **robust, free, cross-platform backup solution** that:
- Uses **Restic** for encrypted, deduplicated, snapshot backups.
- Uses **Rclone** for connectivity (e.g., **Google Drive**) and/or native Restic backends.
- Provides a **Python CLI** (and later a TUI / web UI) to configure, run, monitor, and verify backups.
- Targets **Windows 11 (PowerShell 7+)**, **WSL2/Ubuntu**, and **Android Termux**.
- Prioritizes **reliability**, **observability**, and **easy restore**.

## Current Scope (MVP)
- Python package `rrbackup` with CLI command `rrb`.
- Config-driven operation via `config.toml`:
  - Repository URL (e.g., `rclone:gdrive:/backups/rrbackup` or a local path).
  - Restic password source (`RESTIC_PASSWORD_FILE` preferred).
  - One or more **backup sets** (include/exclude, tags, one-file-system).
  - Retention policy (forget/prune).
- Core commands:
  - `rrb setup` – initialize repo and optionally run a connectivity check.
  - `rrb backup --set <name>` – run a backup for a named set.
  - `rrb list` – list snapshots (filters: path/tag/host).
  - `rrb stats` – repository stats (restore-size).
  - `rrb check` – integrity check.
  - `rrb prune` – apply retention (`forget --prune`).
  - `rrb progress` – show our PID files and `restic list locks`.
- Logging to a timestamped log file per operation; simple PID files for “in progress” visibility.
- Single-letter short flags for all long options (per user preference).

## Assumptions (state them so an LLM can reason safely)
- **Restic** and **Rclone** binaries are preinstalled and on `PATH`.
- Restic supports using an **rclone backend** via URL format `rclone:<remote>:<path>`.  
  If this is unavailable or undesired, an alternative pattern is:
  - Use a **local Restic repo** (fast local backups), then
  - `rclone sync` the Restic repository directory to Google Drive as an offsite copy.
- Repository password is provided either via `RESTIC_PASSWORD_FILE` **(preferred)** or `RESTIC_PASSWORD`.
- No GUI yet; CLI-first design. TUI/web UI will wrap the same command surface.

## File/Folder Structure
