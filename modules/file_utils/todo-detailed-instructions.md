# Disk Recovery & Space Reclamation Playbook (Windows + WSL2 + Termux)

> Purpose: Provide a reliable, scriptable set of commands to **find and free disk space** quickly on a Windows host (PowerShell 7), inside WSL2 (Ubuntu), and on Termux (Android).  
> Integrate these steps into `file_utils` and a CLI front-end. Expose **scan** and **clean** subcommands for each environment, and support **guard rails** (min free space) before VHDX compaction.

---

## 0) General Safety & Order of Operations

1. **Close processes that lock WSL files**:
   - VS Code (including Remote WSL), terminals, File Explorer windows open at `\\wsl$`, Docker Desktop (`com.docker.backend`, `com.docker.proxy`).
2. **Free headroom on Windows host first** to avoid stalls while compacting.
3. In WSL:
   - Prune **Docker/Podman** artifacts first (largest savings).
   - Purge **caches**, **build outputs**, **logs**.
   - `fstrim -av` to return freed blocks to the VHDX.
4. **Compact the VHDX** on Windows (with free-space guard).
5. Re-open WSL and (optionally) restart Docker.

---

## 1) PowerShell 7 (Windows Host): SCAN

### 1.1 Top big files in user profile
```powershell
Get-ChildItem $HOME -Recurse -File -ErrorAction SilentlyContinue |
 Sort-Object Length -Descending |
 Select-Object -First 120 @{n='SizeGB';e={[math]::Round($_.Length/1GB,2)}}, FullName
```

### 1.2 Heaviest directories (aggregated)
```powershell
Get-ChildItem $HOME -Recurse -File -ErrorAction SilentlyContinue |
 Group-Object DirectoryName |
 ForEach-Object { [pscustomobject]@{ Path=$_.Name; SizeBytes=($_.Group | Measure-Object Length -Sum).Sum } } |
 Sort-Object SizeBytes -Descending |
 Select-Object -First 60 @{n='SizeGB';e={[math]::Round($_.SizeBytes/1GB,2)}}, Path
```

### 1.3 Find VHDX hogs (actual host bytes)
```powershell
Get-ChildItem @(
  "$env:LOCALAPPDATA\wsl\*\ext4.vhdx",
  "$env:LOCALAPPDATA\Packages\*\LocalState\ext4.vhdx",
  "$env:LOCALAPPDATA\Docker\wsl\data\ext4.vhdx"
) -ErrorAction SilentlyContinue |
 Sort-Object Length -Descending |
 Select-Object @{n='SizeGB';e={[math]::Round($_.Length/1GB,2)}}, FullName
```

---

## 2) PowerShell 7 (Windows Host): CLEAN

> **No admin needed** for everything here.

### 2.1 Prep this session
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
"{0:N2} GB free (before)" -f ((Get-PSDrive C).Free/1GB)
```

### 2.2 User temp + recycle bin
```powershell
Clear-RecycleBin -Force
Remove-Item "$env:TEMP\*" -Recurse -Force -ErrorAction SilentlyContinue
```

### 2.3 VS Code Remote WSL cache (keep newest)
```powershell
$root="$HOME\vscode-remote-wsl\stable"
if (Test-Path $root) {
  Get-ChildItem $root -Directory | Sort-Object LastWriteTime -Descending |
  Select-Object -Skip 1 | Remove-Item -Recurse -Force
}
```

### 2.4 WinGet caches
```powershell
Remove-Item "$env:LOCALAPPDATA\Packages\Microsoft.DesktopAppInstaller_8wekyb3d8bbwe\LocalCache\Microsoft\WinGet" -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item "$env:LOCALAPPDATA\Microsoft\WinGet" -Recurse -Force -ErrorAction SilentlyContinue
```

### 2.5 VS Code extensions — keep latest per extension (robust)
```powershell
$extDir = "$HOME\.vscode\extensions"
if (Test-Path $extDir) {
    Get-ChildItem $extDir -Directory |
    Group-Object {
        $name = $_.Name
        $cut  = $name.LastIndexOf('-')
        if ($cut -gt 0) { $name.Substring(0, $cut) } else { $name }
    } |
    ForEach-Object {
        $_.Group | Sort-Object LastWriteTime -Descending | Select-Object -Skip 1 | Remove-Item -Recurse -Force
    }
}
```

### 2.6 Node/NuGet caches (user)
```powershell
$npmCache = (npm config get cache) 2>$null
if ($npmCache -and (Test-Path $npmCache)) {
  Remove-Item "$npmCache\*" -Recurse -Force -ErrorAction SilentlyContinue
}
Remove-Item "$HOME\.nuget\packages" -Recurse -Force -ErrorAction SilentlyContinue
```

### 2.7 Close handles that lock WSL / VHDX
```powershell
Get-Process -Name "Code","Code - Insiders","wslservice","Docker Desktop","com.docker.backend","com.docker.proxy" -ErrorAction SilentlyContinue | Stop-Process -Force
```

### 2.8 Compact WSL VHDX **with free-space guard**
```powershell
$minGB = 15
$freeGB = [math]::Round((Get-PSDrive C).Free/1GB,2)
if ($freeGB -lt $minGB) {
    "Skipping compact: only $freeGB GB free (< $minGB GB)."
} else {
    wsl --shutdown
    $vhd = (Get-ChildItem "$env:LOCALAPPDATA\wsl\*\ext4.vhdx" -ErrorAction SilentlyContinue | Select-Object -First 1).FullName
    if ($vhd) { compact /c /a /f /i /exe:lzx "$vhd"; compact /q "$vhd" }
    wsl -d Ubuntu
}
"{0:N2} GB free (after)" -f ((Get-PSDrive C).Free/1GB)
```

> **Optional destructive reset** of Docker Desktop’s own WSL disk (only if you can repull images):
> ```powershell
> wsl --shutdown
> taskkill /IM "Docker Desktop.exe" /F 2>$null; taskkill /IM "com.docker.backend.exe" /F 2>$null; taskkill /IM "com.docker.proxy.exe" /F 2>$null
> Remove-Item "$env:LOCALAPPDATA\Docker\wsl\data\ext4.vhdx" -Force
> ```

---

## 3) Ubuntu / WSL2: SCAN

### 3.1 Filesystems & top-level usage
```bash
df -h /
sudo du -xhd1 / 2>/dev/null | sort -h | tail -n 20
sudo du -xhd1 /var/lib 2>/dev/null | sort -h | tail -n 20
sudo du -xhd1 /home 2>/dev/null | sort -h | tail -n 20
```

### 3.2 Biggest files (home)
```bash
find "$HOME" -xdev -type f -size +500M -printf '%s %p\n' 2>/dev/null | sort -hr | head -n 100
```

> (`sort -hr` = show **largest** first; avoids the “wrong end” confusion.)

---

## 4) Ubuntu / WSL2: CLEAN

### 4.1 APT & logs
```bash
sudo apt-get clean
sudo bash -lc 'rm -f /var/cache/apt/*pkgcache* || true'
sudo rm -rf /var/lib/apt/lists/*
sudo journalctl --vacuum-time=3d
```

### 4.2 Python, Node, Conda/Mamba caches
```bash
rm -rf ~/.cache/{pip,pipenv,huggingface,uv} 2>/dev/null || true
npm cache clean --force 2>/dev/null || true
conda clean -a -y || mamba clean -a -y || true
```

### 4.3 Common build/test artifacts (home)
```bash
find "$HOME" -maxdepth 6 -type d \( -name build -o -name dist -o -name .pytest_cache -o -name __pycache__ -o -name node_modules \) -prune -print0 | xargs -0 -r rm -rf --
```

### 4.4 Your Pulse workspace (permissions then purge)
```bash
sudo chown -R "$USER":"$USER" "$HOME/src/pulse" 2>/dev/null || true
find "$HOME/src/pulse" -maxdepth 4 -type d \( -name build -o -name cmake-build* -o -name .pytest_cache -o -name CMakeFiles \) -print0 | xargs -0 -r rm -rf --
find "$HOME/src/pulse" -type f \( -name 'CMakeCache.txt' -o -name '*.o' -o -name '*.a' -o -name '*.so' -o -name '*.log' -o -name '*.ninja' -o -name '*.gcda' -o -name '*.gcno' \) -print0 | xargs -0 -r rm -f --
```

### 4.5 Old release tarballs
```bash
find "$HOME/src/pulse/build/release" -type f -name '*.tar.gz' -mtime +14 -print0 2>/dev/null | xargs -0 -r rm -f --
```

### 4.6 Docker (rootful) — **make daemon reachable** then prune
```bash
# Force unix socket (bypass fd://)
sudo systemctl stop docker docker.socket containerd 2>/dev/null || true
sudo rm -f /var/run/docker.pid /var/run/docker.sock
sudo mkdir -p /etc/systemd/system/docker.service.d
printf '%s\n' '[Service]' 'ExecStart=' 'ExecStart=/usr/bin/dockerd --containerd=/run/containerd/containerd.sock -H unix:///var/run/docker.sock' | sudo tee /etc/systemd/system/docker.service.d/override.conf >/dev/null
sudo systemctl daemon-reload
sudo systemctl start containerd
sudo systemctl restart docker

# Verify then prune
ls -l /var/run/docker.sock || true
sudo docker version || true
sudo docker system df -v || true
sudo docker system prune -a --volumes -f || true
sudo docker builder prune -a -f || true
sudo docker buildx prune -a -f || true
sudo find /var/lib/docker/containers -type f -name '*-json.log' -size +10M -exec truncate -s 0 {} + 2>/dev/null || true
```

> **Hard reset (destructive)** if store is corrupt:
> ```bash
> sudo systemctl stop docker containerd 2>/dev/null || true
> sudo rm -rf /var/lib/docker && sudo mkdir -p /var/lib/docker && sudo chmod 711 /var/lib/docker
> sudo systemctl start containerd docker
> ```

### 4.7 Podman (rootless) cleanup
```bash
podman stop -a 2>/dev/null || true
podman pod rm -af 2>/dev/null || true
podman rm -af 2>/dev/null || true
podman rmi -af 2>/dev/null || true
podman volume prune -f 2>/dev/null || true
podman builder prune -af 2>/dev/null || true
podman system prune -a -f --volumes 2>/dev/null || true
# Optional full reset (nukes store)
podman system reset --force 2>/dev/null || true
```

### 4.8 Git repositories — compact packs safely
```bash
# For each repo under ~/src
find "$HOME/src" -maxdepth 4 -type d -name ".git" -print0 2>/dev/null | while IFS= read -r -d '' d; do
  repo="$(dirname "$d")"
  echo "GC: $repo"
  git -C "$repo" gc --aggressive --prune=now || true
done
```

### 4.9 Return freed blocks to the VHDX
```bash
sudo fstrim -av
```

---

## 5) Termux (Android): SCAN & CLEAN (user-scope)

### 5.1 Scan big files in $HOME
```bash
du -xhd1 "$HOME" 2>/dev/null | sort -h | tail -n 20
find "$HOME" -xdev -type f -size +200M -printf '%s %p\n' | sort -hr | head -n 50
```

### 5.2 Clean caches & node_modules
```bash
rm -rf ~/.cache/{pip,pipenv} 2>/dev/null || true
npm cache clean --force 2>/dev/null || true
find "$HOME" -maxdepth 6 -type d \( -name node_modules -o -name __pycache__ -o -name .pytest_cache \) -prune -print0 | xargs -0 -r rm -rf --
```

---

## 6) Integration Notes for `file_utils` Module & CLI

### 6.1 CLI structure
- `file-utils scan --target {windows,ubuntu,termux} [-t|--top N] [-d|--depth N]`
- `file-utils clean --target {windows,ubuntu,termux} [--level quick|deep] [--keep-days K]`
- `file-utils docker-clean [--reset]`
- `file-utils podman-clean [--reset]`
- `file-utils git-gc --root <path> [--aggressive]`
- `file-utils compact-vhdx --min-free-gb 15`

All flags get short forms (`-t`, `-d`, `-k`, etc.). Detect OS via your `cross_platform` module and dispatch platform steps.

### 6.2 Guard rails
- Before **compaction**, check `(Get-PSDrive C).Free/1GB >= --min-free-gb`.
- If false → print required frees and **skip** compaction.
- Always **shut down WSL** and **close locking processes** before compaction.

### 6.3 Idempotence & safety
- Use `|| true` / `-ErrorAction SilentlyContinue` to make steps resilient.
- Print **before/after** free space.
- Dry-run mode `--dry-run` prints commands without executing.

### 6.4 Extensibility
- Add providers:
  - **Cache cleaners**: npm, pip, pipenv, uv, conda/mamba, NuGet, WinGet.
  - **Artifact cleaners**: build/`node_modules`/`__pycache__`/`.pytest_cache`.
  - **Container cleaners**: Docker/Podman prune/reset.
  - **Git compaction**: `git gc` across roots.
  - **Log maintenance**: `journalctl --vacuum-time`, truncate `*-json.log`.

### 6.5 Output & logging
- Summaries:
  - Total freed on host (GB), total freed in guest (GB).
  - Top 10 remaining biggest directories/files.
- For failures, capture tail of `journalctl -u docker*`.

---

## 7) FAQ

- **Why does WSL show 1 TB `/` but my SSD is 512 GB?**  
  The ext4 lives in a **sparse VHDX** with a virtual capacity (~1 TB). Host usage is the VHDX file’s actual size.

- **Prune says 0 B reclaimed but I built images.**  
  You may be on a different engine (Docker Desktop vs WSL dockerd) or images already deleted. Ensure `/var/run/docker.sock` exists and points to the engine you expect.

- **Compaction didn’t shrink the VHDX.**  
  Make sure you ran `fstrim -av` inside WSL, then closed all handles and ran `compact` with enough free host space. For maximum shrink (logical), do **export→unregister→import** to a new VHDX later.


