# mypysetup/installer.py
from __future__ import annotations
import os, sys, shutil, subprocess
from pathlib import Path
from typing import Optional, Tuple

# cross_platform is your compatibility layer (import required per your request)
try:
    from cross_platform import SystemUtils, debug_utils
    write = debug_utils.write_debug
except Exception:  # fallback minimal logger if cross_platform isn't importable yet
    class SystemUtils:  # minimal fallback
        import platform
        def __init__(self): self.os_name = self.platform.system().lower()
        def run_command(self, command: str, sudo: bool=False) -> str:
            try:
                if sudo and self.os_name in ("linux","darwin"): command = f"sudo {command}"
                cp = subprocess.run(command, shell=True, text=True, capture_output=True)
                return cp.stdout.strip() if cp.returncode == 0 else ""
            except Exception: return ""
    def write(msg, channel="Information", **_): print(f"[{channel}] {msg}")

sysu = SystemUtils()

# ---------- Utility ----------
def which(exe: str) -> Optional[str]:
    p = shutil.which(exe)
    return os.path.abspath(p) if p else None

def call(cmd: list[str] | str) -> Tuple[int, str, str]:
    try:
        if isinstance(cmd, list):
            cp = subprocess.run(cmd, text=True, capture_output=True)
        else:
            cp = subprocess.run(cmd, shell=True, text=True, capture_output=True)
        return cp.returncode, cp.stdout.strip(), cp.stderr.strip()
    except Exception as e:
        return 1, "", str(e)

def user_bin_paths() -> list[Path]:
    paths = []
    if sysu.os_name == "windows":
        paths.append(Path(os.environ.get("USERPROFILE", str(Path.home()))) / ".local" / "bin")
        paths.append(Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))) / "Python" / "Scripts")
    else:
        paths.append(Path.home() / ".local" / "bin")
    return paths

def ensure_path_hint_lines() -> list[str]:
    bins = [str(p) for p in user_bin_paths()]
    if sysu.os_name == "windows":
        return [f'$env:Path = "{bins[0]};" + $env:Path  # ensure user bin first']
    else:
        return [f'export PATH="$HOME/.local/bin:$PATH"  # ensure user bin first']

# ---------- Tool checks & installers ----------
def check_uv() -> Optional[str]:
    return which("uv")

def install_uv() -> Tuple[bool, Optional[str], str]:
    if check_uv():  # already installed
        loc = check_uv()
        return True, loc, "already"
    if sysu.os_name == "windows":
        cmd = 'irm https://astral.sh/uv/install.ps1 | iex'
        rc, out, err = call(["pwsh","-NoProfile","-Command",cmd]) if which("pwsh") else call(["powershell","-NoProfile","-Command",cmd])
    else:
        rc, out, err = call('curl -LsSf https://astral.sh/uv/install.sh | sh')
    loc = check_uv()
    return (rc==0 and loc is not None), loc, "installed" if rc==0 else err

def check_pipx() -> Optional[str]:
    return which("pipx")

def install_pipx() -> Tuple[bool, Optional[str], str]:
    if check_pipx(): return True, check_pipx(), "already"
    py = which("python") or which("python3")
    if not py: return False, None, "python not found"
    rc, out, err = call([py, "-m", "pip", "install", "--user", "pipx"])
    if rc==0: call([py, "-m", "pipx", "ensurepath"])
    return (rc==0), check_pipx(), "installed" if rc==0 else err

def check_micromamba() -> Optional[str]:
    return which("micromamba")

def install_micromamba() -> Tuple[bool, Optional[str], str]:
    if check_micromamba(): return True, check_micromamba(), "already"
    if sysu.os_name == "windows":
        target_dir = user_bin_paths()[0]
        target_dir.mkdir(parents=True, exist_ok=True)
        ps = "pwsh" if which("pwsh") else "powershell"
        script = """
$u = 'https://micro.mamba.pm/api/micromamba/win-64/latest';
$dl = Join-Path $env:TEMP 'micromamba.tar.bz2';
Invoke-WebRequest -Uri $u -OutFile $dl;
tar -xvjf $dl -C $env:TEMP;
Copy-Item (Join-Path $env:TEMP 'Library\\bin\\micromamba.exe') -Destination $env:USERPROFILE\\.local\\bin\\micromamba.exe -Force;
"""
        rc, out, err = call([ps, "-NoProfile", "-Command", script])
    else:
        target_dir = user_bin_paths()[0]
        target_dir.mkdir(parents=True, exist_ok=True)
        rc, out, err = call(f"curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest | tar -xvj -C {target_dir} --strip-components=1 bin/micromamba")
    loc = check_micromamba()
    return (rc==0 and loc is not None), loc, "installed" if rc==0 else err

# ---------- Python launcher alignment (Windows) ----------
def python_executable(exe: str) -> Optional[str]:
    if not which(exe): return None
    rc, out, _ = call([exe, "-c", "import sys;print(sys.executable)"])
    return out if rc==0 and out else None

def check_py_alignment(prefer_version: str="3.11") -> dict:
    result = {"python": python_executable("python") or python_executable("python3"),
              "py": None, "aligned": None, "suggest_env": f"PY_PYTHON={prefer_version}"}
    py_exec = None
    if which("py"):
        rc, out, _ = call(["py", "-c", "import sys;print(sys.executable)"])
        if rc==0: py_exec = out
    result["py"] = py_exec
    result["aligned"] = (result["python"] == result["py"]) if result["python"] and result["py"] else None
    return result

def list_windows_py_versions() -> list[tuple[str,str]]:
    rc, out, _ = call(["py","-0p"]) if which("py") else (1,"","")
    versions = []
    if rc==0:
        for line in out.splitlines():
            line=line.strip()
            if not line.startswith("-"): continue
            parts = line.split()
            ver = parts[0].lstrip("-")
            path = parts[-1]
            versions.append((ver, path))
    return versions

# ---------- Profile handling ----------
def profile_paths() -> tuple[Optional[Path], Optional[Path]]:
    if sysu.os_name == "windows":
        rc, out, _ = call(["pwsh","-NoProfile","-Command","$PROFILE"]) if which("pwsh") else call(["powershell","-NoProfile","-Command","$PROFILE"])
        p = Path(out) if rc==0 and out else None
        return p, None
    pz = Path.home()/".zshrc"
    pb = Path.home()/".bashrc"
    return (pz if pz.exists() else None), (pb if pb.exists() else pb)

def has_profile_lines(profile: Path, markers: list[str]) -> bool:
    if not profile or not profile.exists(): return False
    txt = profile.read_text(encoding="utf-8", errors="ignore")
    return all(m in txt for m in markers)

def append_profile_lines(profile: Path, lines: list[str]) -> None:
    profile.parent.mkdir(parents=True, exist_ok=True)
    with open(profile, "a", encoding="utf-8") as f:
        f.write("\n# --- mypysetup additions ---\n")
        for ln in lines: f.write(ln.rstrip()+"\n")

# ---------- Public ops ----------
def status() -> dict:
    out = {
        "os": sysu.os_name,
        "uv": check_uv(),
        "pipx": check_pipx(),
        "micromamba": check_micromamba(),
        "user_bins": [str(p) for p in user_bin_paths()],
        "py_alignment": check_py_alignment(),
    }
    return out

def install_missing() -> dict:
    result = {"uv": None, "pipx": None, "micromamba": None, "path_hint": ensure_path_hint_lines()}
    ok, loc, msg = install_uv();    result["uv"] = {"ok": ok, "path": loc, "message": msg}
    ok, loc, msg = install_pipx();  result["pipx"] = {"ok": ok, "path": loc, "message": msg}
    ok, loc, msg = install_micromamba(); result["micromamba"] = {"ok": ok, "path": loc, "message": msg}
    return result

def ensure_global_python() -> Optional[str]:
    py = which("python") or which("python3")
    if py: return py
    if sysu.os_name == "windows":
        options = [
            "winget install --id Python.Python.3.11 --source winget --scope user",
            "winget install --id Python.Python.3.12 --source winget --scope user",
            "Microsoft Store: Python 3.11 or 3.12 (user install)",
        ]
        print("\nNo global Python detected. Recent options:")
        for i,o in enumerate(options,1): print(f"  {i}. {o}")
        choice = input("Pick an option (or press Enter to cancel): ").strip()
        if not choice: return None
        try:
            idx = int(choice); cmd = options[idx-1]
            rc, out, err = call(cmd)
            return which("python") or which("python3")
        except Exception:
            return None
    else:
        print("\nNo global Python detected. On Ubuntu 24.04:")
        print("  sudo apt update && sudo apt install -y python3 python3-venv python3-pip")
        confirm = input("Run this now with sudo? [y/N]: ").strip().lower()
        if confirm == "y":
            rc, out, err = call("sudo apt update && sudo apt install -y python3 python3-venv python3-pip")
            return which("python3") or which("python")
        return None
