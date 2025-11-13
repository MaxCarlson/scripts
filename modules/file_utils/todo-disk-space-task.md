# Disk Space Recovery Utilities — Design Brief

**Goal:** Add cross-platform disk-cleanup and size-inspection utilities to `file_utils` (using the existing `cross_platform` module to detect OS and shell), supporting:
- **Windows 11 (PowerShell 7+)**
- **WSL2 Ubuntu**
- **Android Termux (zsh/bash)**

The utilities must (a) **find** large files/folders, (b) **summarize** space by directory and file type, (c) **delete** common caches/artifacts safely, (d) **shrink container stores**, and (e) **reclaim** freed space (WSL VHDX). Provide **preview → delete** flows, dry-run flags, and interactive confirmation.

---

## 1) Requirements & CLI

### 1.1. CLI Entrypoints
Implement a single entry CLI (e.g., `disktool`) with subcommands:

- `scan-largest` — list largest files and directories.
- `scan-caches` — detect common caches (pip/conda/npm/huggingface/VS Code server/WinGet/etc.).
- `clean` — remove selected caches/artifacts (with `--dry-run`, `--yes`).
- `containers` — show and clean Docker/Podman stores (rootful and rootless).
- `wsl-reclaim` — perform `fstrim` in WSL; compact VHDX from Windows (invoke PowerShell).
- `report` — emit a JSON and Markdown summary.

**Flags (examples):**
- `-p/--path PATH` (scan root)
- `-n/--top N` (results)
- `-m/--min-size SIZE` (e.g., `500M`, `2G`)
- `-f/--format json|table|md`
- `-y/--yes` (confirm)
- `-d/--dry-run` (no changes)
- `-v/--verbose`

### 1.2. Safety & Idempotence
- Default to **read-only** (`scan-*`), and require `--yes` (or interactive confirm) to delete.
- Handle zsh globbing errors by **quoting** and using `bash -lc` when needed.
- When a store is in use (e.g., `dockerd`/`containerd`), **stop** services/processes within user rights before deleting.
- Always support `--dry-run`.

---

## 2) Finding the Largest Files/Directories

### 2.1. Ubuntu/WSL2 (bash/zsh)
**Largest files (≥500 MB), sorted descending:**
```bash
sudo find / -xdev -type f -size +500M -printf '%s %p\n' 2>/dev/null | sort -hr | awk '{printf "%.2f GB  %s\n",$1/1073741824,$2}' | head -n 100
```
- `-xdev` limits to one filesystem (avoid `/mnt/c` unless requested).
- Use `sort -hr` (human-readable reverse) or numeric `sort -n` + `tail`.

**Top directories at root:**
```bash
sudo du -xhd1 / 2>/dev/null | sort -h | tail -n 20
```

**Drill into a path (e.g., home, var):**
```bash
sudo du -xhd1 /home 2>/dev/null | sort -h | tail -n 20
sudo du -xhd1 /var/lib 2>/dev/null | sort -h | tail -n 20
```

### 2.2. Windows (PowerShell)
**Top 50 largest files in profile:**
```powershell
Get-ChildItem $HOME -Recurse -File -ErrorAction SilentlyContinue |
 Sort-Object Length -Descending | Select-Object -First 50 @{n='SizeGB';e={[math]::Round($_.Length/1GB,2)}}, FullName
```

**Top 30 heaviest folders (aggregated):**
```powershell
Get-ChildItem $HOME -Recurse -File -ErrorAction SilentlyContinue |
 Group-Object DirectoryName | ForEach-Object {
  [pscustomobject]@{ Path=$_.Name; SizeBytes=($_.Group | Measure-Object Length -Sum).Sum }
 } | Sort-Object SizeBytes -Descending | Select-Object -First 30 @{n='SizeGB';e={[math]::Round($_.SizeBytes/1GB,2)}}, Path
```

**Find VHDX files (WSL & Docker Desktop):**
```powershell
Get-ChildItem @("$env:LOCALAPPDATA\wsl\*\ext4.vhdx",
 "$env:LOCALAPPDATA\Packages\*\LocalState\ext4.vhdx",
 "$env:LOCALAPPDATA\Docker\wsl\data\ext4.vhdx") -ErrorAction SilentlyContinue |
 Sort-Object Length -Descending | Select-Object @{n='SizeGB';e={[math]::Round($_.Length/1GB,2)}}, FullName
```

### 2.3. Termux (Android)
- Home: `$HOME` under `/data/data/com.termux/files/home`
- File size scans (same as Linux), but **storage** is limited; avoid scanning `/sdcard` unless requested.
```bash
find "$HOME" -xdev -type f -size +200M -printf '%s %p\n' 2>/dev/null | sort -hr | head
du -xhd1 "$HOME" 2>/dev/null | sort -h | tail -n 20
```

---

## 3) Deleting Common Caches & Artifacts

### 3.1. Python/ML (all Linux/Termux)
```bash
rm -rf ~/.cache/pip ~/.cache/pipenv ~/.cache/huggingface ~/.cache/uv 2>/dev/null || true
```

### 3.2. Conda/Mamba (Linux/Termux)
```bash
conda clean -a -y || mamba clean -a -y || true
du -sh ~/miniconda3/pkgs ~/miniconda3/envs/* 2>/dev/null | sort -h
# env removal: conda env remove -n <ENV> -y
```

### 3.3. Node/JS (Linux/Termux)
```bash
npm cache clean --force 2>/dev/null || true
find . -maxdepth 6 -type d -name node_modules -prune -print0 | xargs -0 -r rm -rf --
```

### 3.4. APT & Journals (Ubuntu/WSL2)
```bash
sudo apt-get clean && sudo bash -lc 'rm -f /var/cache/apt/*pkgcache* || true' && sudo rm -rf /var/lib/apt/lists/*
sudo journalctl --vacuum-time=7d
```

### 3.5. Build Artifacts (Linux/Termux)
```bash
find "$HOME" -maxdepth 6 -type d \( -name build -o -name dist -o -name .pytest_cache -o -name __pycache__ \) -prune -print0 | xargs -0 -r rm -rf --
```

### 3.6. Git Object Stores (Linux/Termux)
```bash
find "$HOME" -type d -name .git -prune -print 2>/dev/null | sed 's|/\.git$||' | xargs -r -I{} bash -lc 'cd "{}" && git gc --aggressive --prune=now || true'
```

### 3.7. Windows user caches (PowerShell)
```powershell
Clear-RecycleBin -Force; Remove-Item "$env:TEMP\*" -Recurse -Force -ErrorAction SilentlyContinue
```
```powershell
$root="$HOME\vscode-remote-wsl\stable"; if (Test-Path $root) { Get-ChildItem $root -Directory | Sort-Object LastWriteTime -Descending | Select-Object -Skip 1 | Remove-Item -Recurse -Force }
```
```powershell
Remove-Item "$env:LOCALAPPDATA\Packages\Microsoft.DesktopAppInstaller_8wekyb3d8bbwe\LocalCache\Microsoft\WinGet" -Recurse -Force -ErrorAction SilentlyContinue; Remove-Item "$env:LOCALAPPDATA\Microsoft\WinGet" -Recurse -Force -ErrorAction SilentlyContinue
```
```powershell
Remove-Item "$HOME\.nuget\packages" -Recurse -Force -ErrorAction SilentlyContinue
```

---

## 4) Containers: Docker & Podman

### 4.1. Docker (Linux)
```bash
docker system df -v || true
docker system prune -a --volumes -f || true
docker builder prune -a -f || true
docker buildx prune -a -f || true
sudo find /var/lib/docker/containers -type f -name '*-json.log' -size +10M -exec truncate -s 0 {} +
```
If orphaned layers remain under `/var/lib/docker/overlay2`:
```bash
sudo systemctl stop docker containerd 2>/dev/null || true && sudo pkill -9 dockerd containerd 2>/dev/null || true && sudo rm -rf /var/lib/docker && sudo mkdir -p /var/lib/docker && sudo chmod 711 /var/lib/docker
```

### 4.2. Podman (rootless)
```bash
podman ps -a; podman images -a; podman volume ls
podman stop -a || true && podman pod rm -af || true && podman rm -af || true
podman rmi -af || true && podman volume prune -f || true && podman builder prune -af || true
podman system prune -a -f --volumes || true
podman system reset --force  # (nukes rootless store; opt-in)
```
**Rootless store path:** `~/.local/share/containers/storage`

### 4.3. Docker Desktop on Windows
File: `%LOCALAPPDATA%\Docker\wsl\data\ext4.vhdx`
```powershell
wsl --shutdown; taskkill /IM "Docker Desktop.exe" /F 2>$null; taskkill /IM "com.docker.backend.exe" /F 2>$null; taskkill /IM "com.docker.proxy.exe" /F 2>$null; Remove-Item "$env:LOCALAPPDATA\Docker\wsl\data\ext4.vhdx" -Force -ErrorAction SilentlyContinue
```
Docker Desktop recreates it cleanly on next launch.

---

## 5) Reclaiming VHDX Space (WSL2)

### 5.1. Inside WSL: mark free blocks
```bash
sudo fstrim -av
```

### 5.2. Windows: reduce **size on disk** with NTFS LZX (no admin)
```powershell
wsl --shutdown; $vhd=(Get-ChildItem "$env:LOCALAPPDATA\wsl\*\ext4.vhdx").FullName; compact /c /a /f /i /exe:lzx "$vhd"; compact /q "$vhd"
```
> Note: `Length` remains large; LZX reduces physical bytes used.

### 5.3. Shrink **logical** file size (export → import)
Requires free space on another drive/share roughly equal to used size inside WSL:
```powershell
wsl --shutdown
wsl --export Ubuntu "D:\ubuntu-export.tar"
wsl --unregister Ubuntu
wsl --import Ubuntu "D:\WSL\Ubuntu" "D:\ubuntu-export.tar" --version 2
```

---

## 6) UX & Implementation Notes

### 6.1. Cross-platform detection
Use the provided `cross_platform` module to detect:
- OS: Windows / Linux / Android (Termux detection: env var `TERMUX_VERSION` or path prefix `/data/data/com.termux`)
- Shell: PowerShell vs bash/zsh.

### 6.2. Execution strategy
- Linux/Termux: prefer `subprocess.run([...])` with explicit args; avoid unquoted globs.
- PowerShell: use `pwsh -NoProfile -Command "<cmd>"` or native `System.Management.Automation` if available.
- Provide an abstraction: `run_cmd(cmd: Sequence[str], shell=False, check=False, capture=True, sudo=False)`.

### 6.3. Preview → Delete
- Every cleaner implements `plan()` (return list of actions & size estimates) and `apply()` (executes).
- `--dry-run` prints the plan in table/JSON.
- `--yes` skips prompts; otherwise interactive selection.

### 6.4. Reporting
- Aggregate per-category reclaimed bytes.
- Emit both JSON and Markdown reports (`report` subcommand).

### 6.5. Error Handling
- If a directory is **busy** (e.g., `/var/lib/docker`), stop daemons first.
- For zsh “no matches found,” call via `bash -lc 'rm -f /var/cache/apt/*pkgcache*'`.
- If `compact` says “file in use,” close VS Code Remote, Docker Desktop, and `\\wsl$` Explorer, then retry.

---

## 7) Test Matrix

### 7.1. Read-only scanning
- Large file scan returns sorted results on all three platforms.
- Directory size scan (`du`/PowerShell aggregation) matches manual spot checks.

### 7.2. Cleaners (dry-run)
- Show correct lists for pip/conda/npm/huggingface/VS Code server/WinGet/Podman/Docker.

### 7.3. Cleaners (apply)
- Re-run scans show reduced sizes.
- WSL: `fstrim` succeeds; Windows `compact` reduces size on disk; export/import shrinks logical size.

---

## 8) Reference Command Library (to embed)

### 8.1. Linux/Termux (scan)
```bash
sudo du -xhd1 / 2>/dev/null | sort -h | tail -n 20
sudo du -xhd1 /home 2>/dev/null | sort -h | tail -n 20
sudo du -xhd1 /var/lib 2>/dev/null | sort -h | tail -n 20
find "$HOME" -xdev -type f -size +500M -printf '%s %p\n' 2>/dev/null | sort -hr | head -n 100
```

### 8.2. Linux/Termux (clean)
```bash
sudo apt-get clean && sudo bash -lc 'rm -f /var/cache/apt/*pkgcache* || true' && sudo rm -rf /var/lib/apt/lists/*
rm -rf ~/.cache/pip ~/.cache/pipenv ~/.cache/huggingface ~/.cache/uv
conda clean -a -y || mamba clean -a -y || true
find . -maxdepth 6 -type d \( -name build -o -name dist -o -name .pytest_cache -o -name __pycache__ -o -name node_modules \) -prune -print0 | xargs -0 -r rm -rf --
find "$HOME" -type d -name .git -prune -print | sed 's|/\.git$||' | xargs -r -I{} bash -lc 'cd "{}" && git gc --aggressive --prune=now || true'
```

### 8.3. Docker/Podman
```bash
docker system prune -a --volumes -f || true; docker builder prune -a -f || true; docker buildx prune -a -f || true
sudo systemctl stop docker containerd 2>/dev/null || true && sudo pkill -9 dockerd containerd 2>/dev/null || true && sudo rm -rf /var/lib/docker && sudo mkdir -p /var/lib/docker && sudo chmod 711 /var/lib/docker
podman stop -a || true && podman pod rm -af || true && podman rm -af || true && podman rmi -af || true && podman volume prune -f || true && podman builder prune -af || true && podman system prune -a -f --volumes || true
```

### 8.4. Windows
```powershell
Get-ChildItem "$env:LOCALAPPDATA\wsl\*\ext4.vhdx","$env:LOCALAPPDATA\Docker\wsl\data\ext4.vhdx" -ErrorAction SilentlyContinue | Sort-Object Length -Descending | Select-Object @{n='SizeGB';e={[math]::Round($_.Length/1GB,2)}}, FullName
Clear-RecycleBin -Force; Remove-Item "$env:TEMP\*" -Recurse -Force -ErrorAction SilentlyContinue
$root="$HOME\vscode-remote-wsl\stable"; if (Test-Path $root) { Get-ChildItem $root -Directory | Sort-Object LastWriteTime -Descending | Select-Object -Skip 1 | Remove-Item -Recurse -Force }
Remove-Item "$env:LOCALAPPDATA\Packages\Microsoft.DesktopAppInstaller_8wekyb3d8bbwe\LocalCache\Microsoft\WinGet" -Recurse -Force -ErrorAction SilentlyContinue; Remove-Item "$env:LOCALAPPDATA\Microsoft\WinGet" -Recurse -Force -ErrorAction SilentlyContinue
wsl --shutdown; $vhd=(Get-ChildItem "$env:LOCALAPPDATA\wsl\*\ext4.vhdx").FullName; compact /c /a /f /i /exe:lzx "$vhd"; compact /q "$vhd"; wsl -d Ubuntu
```

---

## 9) Deliverables

1. **Python module** additions in `file_utils`:
   - `scan_largest_files(path, min_size, top, ...)`
   - `scan_heaviest_dirs(path, depth, ...)`
   - `detect_caches()` → list of cache locations per platform
   - `clean_caches(selection, dry_run, yes)`
   - `containers_info()` / `containers_clean(options, dry_run)`
   - `wsl_reclaim(compact: bool, export_path: Optional[str])`
   - `report(format)` → JSON/Markdown

2. **CLI** `disktool` exposing the above with consistent flags (both long + single-letter).

3. **Pytests** covering parsing, scanning, dry-run planning, and platform branching.

4. **Docs**: README section with all commands above, warnings, and recovery notes.

---

