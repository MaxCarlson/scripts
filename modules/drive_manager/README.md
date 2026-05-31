# drive-manager

`drive-manager` is a cross-platform CLI and Python module for disk and USB inspection, bad-drive diagnosis, safe formatting, USB restoration, and raw bootable-image writing.

The design goal is strong safety: every destructive or write operation defaults to dry-run mode, the OS disk is never destructively modifiable, non-USB disks require explicit typed confirmation, and disks larger than 256 GiB are refused unless `--allow-large-disk` is also provided.

## Install for development

```bash
python -m venv .venv && . .venv/bin/activate && python -m pip install -e .
```

On Windows PowerShell:

```powershell
py -m venv .venv && .\.venv\Scripts\Activate.ps1 && py -m pip install -e .
```

## Quick usage

List disks:

```bash
drive-manager scan list
```

List USB disks:

```bash
drive-manager scan usb
```

Show detailed disk information:

```bash
drive-manager scan detail -d 6
```

Diagnose a disk:

```bash
drive-manager diagnose disk -d 6
```

Restore a USB drive to normal FAT32 storage, dry-run first:

```bash
drive-manager restore normal -d 6 -f FAT32 -l USB
```

Actually execute after reviewing the dry run:

```bash
drive-manager restore normal -d 6 -f FAT32 -l USB -x
```

Write a raw image to a USB drive, dry-run first:

```bash
drive-manager image write -d 6 -i .\memtest86-usb.img -V
```

Actually execute:

```bash
drive-manager image write -d 6 -i .\memtest86-usb.img -x -V -F
```

Download and write an image URL:

```bash
drive-manager image write -d 6 -u https://example.com/image.img -x -V -F
```

## Safety rules

| Target | Required for destructive/write operation |
|---|---|
| USB disk <= 256 GiB | `-x / --execute` |
| USB disk > 256 GiB | `-x / --execute` and `-L / --allow-large-disk` |
| Non-USB disk <= 256 GiB | `-x / --execute`, `-U / --allow-non-usb`, typed confirmations |
| Non-USB disk > 256 GiB | `-x / --execute`, `-U / --allow-non-usb`, `-L / --allow-large-disk`, typed confirmations |
| OS disk | Always refused. No override. |

## Important Windows note

Run destructive/write operations from an elevated PowerShell session. Read-only scan and diagnosis commands can often run unelevated, but raw writes and formatting require Administrator privileges.

## Important WSL2 note

WSL2 usually does not see Windows-attached USB drives unless they are explicitly forwarded. For normal Windows USB drive work, run `drive-manager` from Windows PowerShell rather than inside WSL2.

## Command groups

```text
drive-manager scan list
drive-manager scan usb
drive-manager scan volumes
drive-manager scan letters -d 6
drive-manager scan detail -d 6

drive-manager diagnose disk -d 6
drive-manager diagnose usb

drive-manager mount list
drive-manager mount unmount -p F:
drive-manager mount eject -d 6

drive-manager format usb -d 6 -f FAT32 -l USB

drive-manager wipe clear -d 6

drive-manager image write -d 6 -i image.img
drive-manager image verify -d 6 -i image.img

drive-manager usb rescan
drive-manager usb reset-device -d 6

drive-manager health smart -d 6

drive-manager restore normal -d 6 -f FAT32 -l USB

drive-manager doctor deps
drive-manager doctor permissions
drive-manager doctor platform
```

## JSON output

Most read-only commands support JSON:

```bash
drive-manager scan list -j
```

## Status

This is an alpha-quality safety-first implementation. Read-only disk inventory and diagnosis are intended to be immediately useful. Destructive operations are guarded by dry-run defaults and centralized safety policy.
