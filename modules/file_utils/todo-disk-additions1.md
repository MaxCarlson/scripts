Windows App Caches (Teams / Edge / Chrome)
# Clear common Electron/Chromium caches (no admin needed).
$paths=@(
 "$env:APPDATA\Microsoft\Teams\Cache",
 "$env:APPDATA\Microsoft\Teams\GPUCache",
 "$env:LOCALAPPDATA\Microsoft\Olk\EBWebView",
 "$env:LOCALAPPDATA\Microsoft\Edge\User Data\*\Cache",
 "$env:LOCALAPPDATA\Microsoft\Edge\User Data\*\Code Cache",
 "$env:LOCALAPPDATA\Microsoft\Edge\User Data\*\GPUCache",
 "$env:LOCALAPPDATA\Google\Chrome\User Data\*\Cache",
 "$env:LOCALAPPDATA\Google\Chrome\User Data\*\Code Cache",
 "$env:LOCALAPPDATA\Google\Chrome\User Data\*\GPUCache"
)
$paths | ForEach-Object {
  Get-ChildItem $_ -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
}


Tips
• Close Teams/Edge/Chrome first for maximum effect.
• Dry-run: replace Remove-Item with | Measure-Object Length -Sum to see bytes.

Docker Desktop from PowerShell (host) — identify, prune, compact
# See which engine your CLI targets
docker context ls
docker context use desktop-linux    # target Docker Desktop’s Linux engine

# If the engine is healthy, quantify usage and prune
docker system df -v
docker system prune -a --volumes -f
docker builder prune -a -f
docker buildx prune -a -f

# If `docker system df -v` throws 500 on the pipe:
# 1) restart Desktop’s WSL backends
wsl --terminate docker-desktop 2>$null
wsl --terminate docker-desktop-data 2>$null
wsl --shutdown
Stop-Process -Name "Docker Desktop","com.docker.*" -Force -ErrorAction SilentlyContinue
Start-Process "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe"

# 2) try again
docker context use desktop-linux
docker system df -v

# Optional: compact Desktop’s VHDX after pruning (quit Desktop first)
$dd = "$env:LOCALAPPDATA\Docker\wsl\disk\docker_data.vhdx"
if (Test-Path $dd) { compact /c /i "$dd" }


Nuclear reclaim (destructive):
Delete %LOCALAPPDATA%\Docker\wsl\disk\docker_data.vhdx after wsl --shutdown and quitting the app to reclaim everything immediately; Docker Desktop will recreate a small fresh VHDX on next launch.

Host-Wide Triage (top files / per-root sizes)
# Top 40 biggest files on C:\
Get-ChildItem C:\ -File -Recurse -Force -ErrorAction SilentlyContinue |
  Sort-Object Length -Descending |
  Select-Object -First 40 @{n='GB';e={[math]::Round($_.Length/1GB,2)}}, FullName

# Size by major roots (quick attribution)
$roots = 'C:\Users','C:\ProgramData','C:\Program Files','C:\Program Files (x86)','C:\Windows'
foreach($r in $roots){
  try{
    $sum = (Get-ChildItem $r -Recurse -Force -ErrorAction SilentlyContinue -File |
            Measure-Object Length -Sum).Sum
    '{0,-28}  {1,8:N2} GB' -f $r, ($sum/1GB)
  }catch{}
}

# Per-user profiles (who’s largest)
Get-ChildItem 'C:\Users' -Directory -ErrorAction SilentlyContinue |
  ForEach-Object {
    $p=$_.FullName
    try{
      $sz=(Get-ChildItem $p -Recurse -Force -ErrorAction SilentlyContinue -File |
           Measure-Object Length -Sum).Sum
      [pscustomobject]@{ GB=[math]::Round($sz/1GB,2); Path=$p }
    }catch{}
  } | Sort-Object GB -Descending | Select-Object -First
