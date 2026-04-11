#!/usr/bin/env python3
"""
System Manager Implementation

Contains the logic for 50+ useful cross-platform system commands.
"""

import os
import sys
import platform
import subprocess
import time
import socket
import json
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Any, Tuple

import psutil
import requests
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.live import Live

from cross_platform import SystemUtils, ClipboardUtils, NetworkUtils, ProcessManager, PrivilegesManager
from .utils import run_powershell, get_console_width, get_console_height
from .command_registry import search_commands
from .process_tools import (
    ProcessQuery,
    act_on_processes,
    find_processes,
    process_parents,
    process_tree as proc_tools_tree,
    sample_process_stats,
    windows_cim_process_search,
)

console = Console()
sysu = SystemUtils()

try:
    from cross_platform.clipboard_utils import set_clipboard, get_clipboard
    CLIPBOARD_AVAILABLE = True
except ImportError:
    CLIPBOARD_AVAILABLE = False

class SystemManager:
    """Core implementation of system management commands."""

    @staticmethod
    def whoami():
        """Show current user and elevation status."""
        priv = PrivilegesManager()
        is_admin = priv.is_admin()
        status = "[bold red]Elevated (Admin/Root)[/]" if is_admin else "[yellow]Standard User[/]"
        
        try:
            username = os.getlogin()
        except:
            username = os.environ.get("USER") or os.environ.get("USERNAME") or "unknown"
            
        return {
            "property": ["Username", "Home", "Status", "OS Name"],
            "value": [username, str(Path.home()), status, sysu.os_name]
        }

    @staticmethod
    def public_ip():
        """Fetch public IP address."""
        try:
            response = requests.get("https://api.ipify.org?format=json", timeout=5)
            return response.json().get("ip")
        except Exception as e:
            return f"Error: {e}"

    @staticmethod
    def local_ip():
        """List all local IP addresses."""
        results = []
        for interface, addrs in psutil.net_if_addrs().items():
            for addr in addrs:
                if addr.family == socket.AF_INET:
                    results.append({
                        "interface": interface,
                        "address": addr.address,
                        "netmask": addr.netmask or "N/A"
                    })
        return results

    @staticmethod
    def uptime():
        """Show system boot time and duration."""
        boot_time_timestamp = psutil.boot_time()
        bt = datetime.fromtimestamp(boot_time_timestamp)
        now = datetime.now()
        uptime_delta = now - bt
        
        days = uptime_delta.days
        hours, remainder = divmod(uptime_delta.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        return {
            "uptime": f"{days}d {hours}h {minutes}m {seconds}s",
            "boot_time": bt.strftime('%Y-%m-%d %H:%M:%S')
        }

    @staticmethod
    def port_scan(start_port: int = 1, end_port: int = 1024):
        """Check for open local ports."""
        open_ports = []
        try:
            for conn in psutil.net_connections():
                if conn.status == 'LISTEN' and start_port <= conn.laddr.port <= end_port:
                    open_ports.append(conn.laddr.port)
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            for port in range(start_port, end_port + 1):
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(0.01)
                    if s.connect_ex(('127.0.0.1', port)) == 0:
                        open_ports.append(port)
        return sorted(list(set(open_ports)))

    @staticmethod
    def battery():
        """Show battery status."""
        battery = psutil.sensors_battery()
        if battery is None:
            return None
        return {
            "percent": battery.percent,
            "power_plugged": battery.power_plugged,
            "status": "Charging" if battery.power_plugged else "Discharging"
        }

    @staticmethod
    def timezone():
        """Show current timezone details."""
        now = datetime.now()
        local_now = now.astimezone()
        return {
            "name": local_now.tzname(),
            "offset": str(local_now.utcoffset()),
            "local_time": now.strftime('%Y-%m-%d %H:%M:%S')
        }

    @staticmethod
    def cpu_info():
        """Show CPU details."""
        freq = psutil.cpu_freq()
        return {
            "physical_cores": psutil.cpu_count(logical=False),
            "logical_cores": psutil.cpu_count(logical=True),
            "max_freq": f"{freq.max:.2f} MHz" if freq else "N/A",
            "current_freq": f"{freq.current:.2f} MHz" if freq else "N/A",
            "current_load": f"{psutil.cpu_percent(interval=0.5)}%"
        }

    @staticmethod
    def mem_info():
        """Show memory usage summary."""
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()
        return [
            {"type": "RAM", "total": mem.total, "used": mem.used, "free": mem.available, "percent": f"{mem.percent}%"},
            {"type": "Swap", "total": swap.total, "used": swap.used, "free": swap.free, "percent": f"{swap.percent}%"}
        ]

    @staticmethod
    def disk_list():
        """List partitions and mount points."""
        results = []
        for part in psutil.disk_partitions():
            try:
                usage = psutil.disk_usage(part.mountpoint)
                results.append({
                    "device": part.device,
                    "mount": part.mountpoint,
                    "fstype": part.fstype,
                    "total": usage.total,
                    "used": usage.used,
                    "free": usage.free,
                    "percent": f"{usage.percent}%"
                })
            except (PermissionError, OSError):
                pass
        return results

    @staticmethod
    def process_top(count: int = 10, sort_by: str = "cpu"):
        """Show top processes by CPU or Memory usage."""
        # Use a single pass if possible, or two passes with shared objects
        procs = {}
        for p in psutil.process_iter(['pid', 'name', 'memory_info']):
            try:
                # First call to cpu_percent to initialize
                p.cpu_percent()
                procs[p.pid] = p
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        
        # Short wait for diff
        time.sleep(0.2)
        
        results = []
        for pid, p in procs.items():
            try:
                cpu = p.cpu_percent()
                # On Windows, Idle process can show huge CPU (sum of idle cores)
                if p.info['name'] == "System Idle Process": cpu = 0.0
                
                mem_info = p.info['memory_info']
                if not mem_info: continue
                results.append({
                    "pid": pid,
                    "name": p.info['name'],
                    "cpu": f"{cpu}%",
                    "cpu_raw": cpu,
                    "memory": mem_info.rss
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        
        if sort_by == "cpu":
            top = sorted(results, key=lambda x: x['cpu_raw'], reverse=True)[:count]
        else:
            top = sorted(results, key=lambda x: x['memory'], reverse=True)[:count]
            
        # Clean up raw fields before returning
        for item in top: item.pop('cpu_raw', None)
        return top

    @staticmethod
    def service_list():
        """List active system services."""
        results = []
        if sysu.is_windows():
            # Use the robust run_powershell helper with SilentlyContinue and explicit status string
            script = "$s = Get-Service -ErrorAction SilentlyContinue | Where-Object Status -eq Running | Select-Object Name, DisplayName, @{n='Status';e={$_.Status.ToString()}}; if ($s) { $s | ConvertTo-Json } else { '[]' }"
            out = run_powershell(script)
            try:
                data = json.loads(out)
                if isinstance(data, dict): data = [data]
                for s in data:
                    results.append({
                        "name": s["Name"],
                        "display": s["DisplayName"],
                        "status": s["Status"]
                    })
            except: pass
        elif sysu.is_linux() and not sysu.is_termux():
            out = sysu.run_command("systemctl list-units --type=service --state=running --no-pager --no-legend")
            for line in out.splitlines():
                parts = line.split(None, 4)
                if len(parts) >= 5:
                    results.append({
                        "name": parts[0],
                        "display": parts[4],
                        "status": parts[3]
                    })
        return results

    @staticmethod
    def sys_table_width(width: Optional[int] = None):
        """Tip for table width."""
        w = width or get_console_width()
        return {"tip": f"Append '| Out-String -Width {w}' to your PS commands."}

    @staticmethod
    def shell_info():
        """Show shell information."""
        shell_path = os.environ.get("SHELL") or os.environ.get("COMSPEC") or "Unknown"
        shell_name = Path(shell_path).name
        
        return {
            "shell": shell_name,
            "path": shell_path,
            "os_name": sysu.os_name
        }

    @staticmethod
    def os_detail():
        """Show detailed OS info."""
        return {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "architecture": platform.machine(),
            "node": platform.node()
        }

    @staticmethod
    def os_detail_print():
        """Print detailed OS info (legacy compatibility)."""
        console.print(f"[bold cyan]OS System:[/] {platform.system()}")
        console.print(f"[bold cyan]OS Release:[/] {platform.release()}")
        console.print(f"[bold cyan]OS Version:[/] {platform.version()}")
        console.print(f"[bold cyan]Architecture:[/] {platform.machine()}")
        if hasattr(platform, "freedesktop_os_release"):
            try:
                info = platform.freedesktop_os_release()
                console.print(f"[bold cyan]Distro:[/] {info.get('PRETTY_NAME', 'Unknown')}")
            except: pass


    # SYS Inspect
    @staticmethod
    def sys_inspect(proc_name: str):
        """See properties of a running process (summarized)."""
        results = []
        for p in psutil.process_iter(['pid', 'name']):
            try:
                if proc_name.lower() in p.info['name'].lower():
                    info = p.as_dict(attrs=['pid', 'name', 'status', 'username', 'create_time', 'exe', 'cmdline', 'cpu_percent', 'memory_info'])
                    # Format creation time
                    if info.get('create_time'):
                        info['created'] = datetime.fromtimestamp(info['create_time']).strftime('%Y-%m-%d %H:%M:%S')
                    # Summarize memory
                    if info.get('memory_info'):
                        from cross_platform.size_utils import format_bytes_binary
                        info['rss'] = format_bytes_binary(info['memory_info'].rss)
                        info['vms'] = format_bytes_binary(info['memory_info'].vms)
                        info.pop('memory_info')
                    results.append(info)
            except: pass
        return results

    # More SYS additions
    @staticmethod
    def sys_monitor():
        """One-shot machine dashboard summary."""
        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        net = psutil.net_io_counters()
        return {
            "cpu_load": f"{cpu}%",
            "memory_usage": f"{mem.percent}%",
            "disk_usage": f"{disk.percent}%",
            "net_sent": format_bytes_binary(net.bytes_sent),
            "net_recv": format_bytes_binary(net.bytes_recv)
        }

    # PKG Category
    @staticmethod
    def pkg_search(query: str):
        """Search for packages (winget/pip)."""
        if sysu.is_windows():
            out = run_powershell(f"winget search '{query}' | Out-String")
            return {"output": out}
        else:
            out = sysu.run_command(f"apt search {query}")
            return {"output": out}

    @staticmethod
    def pkg_which_manager(command: str):
        """Detect which package manager likely owns a command."""
        from cross_platform.package_manager import probe_tool_installations
        cands = probe_tool_installations(command)
        return [{"manager": c.manager, "confidence": c.confidence, "evidence": c.evidence} for c in cands]

    # DISK Category
    @staticmethod
    def disk_mounts():
        """List mounted filesystems."""
        return [{"device": p.device, "mount": p.mountpoint, "fstype": p.fstype, "opts": p.opts} for p in psutil.disk_partitions()]

    # SERVICE Category
    @staticmethod
    def service_start(name: str):
        """Start a service."""
        if sysu.is_windows():
            out = run_powershell(f"Start-Service -Name '{name}'")
            return {"status": "Command issued"}
        else:
            out = sysu.run_command(f"systemctl start {name}", sudo=True)
            return {"output": out}

    @staticmethod
    def service_stop(name: str):
        """Stop a service."""
        if sysu.is_windows():
            out = run_powershell(f"Stop-Service -Name '{name}'")
            return {"status": "Command issued"}
        else:
            out = sysu.run_command(f"systemctl stop {name}", sudo=True)
            return {"output": out}

    # TEXT Category
    @staticmethod
    def text_base64_encode(text: str):
        import base64
        return base64.b64encode(text.encode()).decode()

    @staticmethod
    def text_base64_decode(text: str):
        import base64
        return base64.b64decode(text.encode()).decode()

    @staticmethod
    def text_sha256(text: str):
        import hashlib
        return hashlib.sha256(text.encode()).hexdigest()

    # CRYPTO Category
    @staticmethod
    def crypto_rand(length: int = 32):
        import secrets
        import string
        alphabet = string.ascii_letters + string.digits
        return ''.join(secrets.choice(alphabet) for i in range(length))

    # GIT Category
    @staticmethod
    def git_status_short():
        """Short git status."""
        out = sysu.run_command("git status -s")
        return [{"line": line} for line in out.splitlines()]

    @staticmethod
    def git_branch_info():
        """Current branch info."""
        branch = sysu.run_command("git branch --show-current")
        rev = sysu.run_command("git rev-parse --short HEAD")
        return {"branch": branch, "commit": rev}

    @staticmethod
    def git_root():
        """Find git root."""
        return {"root": sysu.run_command("git rev-parse --show-toplevel")}

    # Iterative File Operations
    @staticmethod
    def file_rename_ext(old_ext: str, new_ext: str, directory: str = ".", recursive: bool = False, apply: bool = False):
        """Rename file extensions in a directory."""
        root = Path(directory).resolve()
        old_ext = "." + old_ext.lstrip(".")
        new_ext = "." + new_ext.lstrip(".")
        results = []
        it = root.rglob(f"*{old_ext}") if recursive else root.glob(f"*{old_ext}")
        for p in it:
            if p.is_file():
                new_path = p.with_suffix(new_ext)
                results.append({"old": str(p), "new": str(new_path)})
                if apply:
                    try: p.rename(new_path)
                    except Exception as e: results[-1]["error"] = str(e)
        return results

    @staticmethod
    def file_add_prefix(prefix: str, directory: str = ".", recursive: bool = False, apply: bool = False):
        """Add a prefix to filenames."""
        root = Path(directory).resolve()
        results = []
        it = root.rglob("*") if recursive else root.iterdir()
        for p in it:
            if p.is_file():
                new_name = prefix + p.name
                new_path = p.parent / new_name
                results.append({"old": str(p), "new": str(new_path)})
                if apply:
                    try: p.rename(new_path)
                    except Exception as e: results[-1]["error"] = str(e)
        return results

    @staticmethod
    def file_add_date_suffix(directory: str = ".", recursive: bool = False, apply: bool = False):
        """Append today's date to filenames."""
        root = Path(directory).resolve()
        suffix = datetime.now().strftime("_%Y%m%d")
        results = []
        it = root.rglob("*") if recursive else root.iterdir()
        for p in it:
            if p.is_file():
                new_name = f"{p.stem}{suffix}{p.suffix}"
                new_path = p.parent / new_name
                results.append({"old": str(p), "new": str(new_path)})
                if apply:
                    try: p.rename(new_path)
                    except Exception as e: results[-1]["error"] = str(e)
        return results

    @staticmethod
    def file_ext_lower(directory: str = ".", recursive: bool = False, apply: bool = False):
        """Normalize extensions to lowercase."""
        root = Path(directory).resolve()
        results = []
        it = root.rglob("*") if recursive else root.iterdir()
        for p in it:
            if p.is_file() and p.suffix != p.suffix.lower():
                new_path = p.with_suffix(p.suffix.lower())
                results.append({"old": str(p), "new": str(new_path)})
                if apply:
                    try: p.rename(new_path)
                    except Exception as e: results[-1]["error"] = str(e)
        return results

    @staticmethod
    def file_spaces_to_underscores(directory: str = ".", recursive: bool = False, apply: bool = False):
        """Replace spaces in filenames with underscores."""
        root = Path(directory).resolve()
        results = []
        it = root.rglob("*") if recursive else root.iterdir()
        for p in it:
            if p.is_file() and " " in p.name:
                new_name = p.name.replace(" ", "_")
                new_path = p.parent / new_name
                results.append({"old": str(p), "new": str(new_path)})
                if apply:
                    try: p.rename(new_path)
                    except Exception as e: results[-1]["error"] = str(e)
        return results

    @staticmethod
    def file_remove_empty_dirs(directory: str = ".", apply: bool = False):
        """Delete empty directories from deepest to shallowest."""
        results = []
        # Use bottom-up to catch nested empties in one pass
        for root, dirs, files in os.walk(directory, topdown=False):
            for d in dirs:
                full_path = Path(root) / d
                if not any(full_path.iterdir()):
                    results.append({"path": str(full_path)})
                    if apply:
                        try: os.rmdir(full_path)
                        except Exception as e: results[-1]["error"] = str(e)
        return results

    @staticmethod
    def file_delete_old(days: int = 30, directory: str = ".", recursive: bool = False, apply: bool = False):
        """Delete files older than N days."""
        root = Path(directory).resolve()
        cutoff = time.time() - (days * 86400)
        results = []
        it = root.rglob("*") if recursive else root.iterdir()
        for p in it:
            if p.is_file():
                try:
                    mtime = p.stat().st_mtime
                    if mtime < cutoff:
                        results.append({
                            "path": str(p), 
                            "mtime": datetime.fromtimestamp(mtime).strftime('%Y-%m-%d'),
                            "days_old": int((time.time() - mtime) / 86400)
                        })
                        if apply:
                            try: p.unlink()
                            except Exception as e: results[-1]["error"] = str(e)
                except: pass
        return results

    @staticmethod
    def file_strip_trailing_whitespace(pattern: str = "*.py|*.ps1|*.md", directory: str = ".", recursive: bool = False, apply: bool = False):
        """Remove trailing whitespace from files."""
        root = Path(directory).resolve()
        patterns = pattern.split('|')
        results = []
        
        found_files = []
        for pat in patterns:
            found_files.extend(root.rglob(pat) if recursive else root.glob(pat))
            
        for p in found_files:
            if p.is_file():
                try:
                    content = p.read_text(encoding='utf-8', errors='ignore')
                    new_content = "\n".join([line.rstrip() for line in content.splitlines()])
                    if content.endswith('\n'): new_content += '\n'
                    
                    if content != new_content:
                        results.append({"path": str(p), "status": "Has trailing whitespace"})
                        if apply:
                            try: 
                                p.write_text(new_content, encoding='utf-8')
                                results[-1]["status"] = "Cleaned"
                            except Exception as e: results[-1]["error"] = str(e)
                except: pass
        return results

    @staticmethod
    def file_dupes_detailed(directory: str = ".", recursive: bool = False):
        """Find duplicates by SHA256 with details."""
        from file_utils import find_duplicates
        from cross_platform.size_utils import format_bytes_binary
        dupes = find_duplicates(directory, use_hashes=True)
        results = []
        for orig, sub_list in dupes.items():
            if not recursive and Path(orig).parent != Path(directory).resolve(): continue
            try:
                size = Path(orig).stat().st_size
                results.append({
                    "name": Path(orig).name,
                    "count": len(sub_list) + 1,
                    "total_waste": format_bytes_binary(size * len(sub_list)),
                    "original": orig,
                    "duplicates": ", ".join(sub_list)
                })
            except: pass
        return results

    @staticmethod
    def file_dir_sizes(directory: str = "."):
        """Show size of each top-level subdirectory."""
        root = Path(directory).resolve()
        results = []
        from cross_platform.size_utils import format_bytes_binary
        for p in root.iterdir():
            if p.is_dir():
                try:
                    total = sum(f.stat().st_size for f in p.rglob('*') if f.is_file())
                    results.append({
                        "folder": p.name,
                        "size": format_bytes_binary(total),
                        "bytes": total
                    })
                except: pass
        return sorted(results, key=lambda x: x['bytes'], reverse=True)

    @staticmethod
    def file_long_paths(directory: str = ".", count: int = 50, recursive: bool = True):
        """Find the longest paths in a tree."""
        root = Path(directory).resolve()
        files = []
        it = root.rglob("*") if recursive else root.iterdir()
        for p in it:
            files.append({"length": len(str(p)), "path": str(p)})
        return sorted(files, key=lambda x: x['length'], reverse=True)[:count]

    @staticmethod
    def file_empty_files(directory: str = ".", recursive: bool = False):
        """List zero-byte files."""
        root = Path(directory).resolve()
        results = []
        it = root.rglob("*") if recursive else root.iterdir()
        for p in it:
            if p.is_file() and p.stat().st_size == 0:
                results.append({"path": str(p), "name": p.name})
        return results

    @staticmethod
    def net_kill_port_range(start: int, end: int, apply: bool = False):
        """Kill processes listening on a port range."""
        results = []
        for conn in psutil.net_connections(kind='inet'):
            if start <= conn.laddr.port <= end:
                try:
                    proc = psutil.Process(conn.pid)
                    results.append({
                        "port": conn.laddr.port,
                        "pid": conn.pid,
                        "name": proc.name(),
                        "status": "Found"
                    })
                    if apply:
                        proc.terminate()
                        results[-1]["status"] = "Terminated"
                except: pass
        return results

    @staticmethod
    def proc_full_list():
        """Detailed process list."""
        results = []
        for p in psutil.process_iter(['pid', 'name', 'exe', 'cmdline']):
            try:
                results.append({
                    "pid": p.info['pid'],
                    "name": p.info['name'],
                    "path": p.info['exe'] or "N/A",
                    "cmdline": " ".join(p.info['cmdline']) if p.info['cmdline'] else "N/A"
                })
            except: pass
        return results

    @staticmethod
    def sys_recent_errors(count: int = 50):
        """Show recent system event errors (Windows)."""
        if sysu.is_windows():
            script = f"Get-WinEvent -LogName System -MaxEvents {count} -ErrorAction SilentlyContinue | Where-Object {{ $_.LevelDisplayName -in @('Error','Warning') }} | Select-Object TimeCreated, Id, ProviderName, LevelDisplayName, Message | ConvertTo-Json"
            out = run_powershell(script)
            try:
                data = json.loads(out)
                if isinstance(data, dict): data = [data]
                return [{
                    "time": d.get("TimeCreated"),
                    "level": d.get("LevelDisplayName"),
                    "source": d.get("ProviderName"),
                    "message": d.get("Message", "")[:100] + "..."
                } for d in data]
            except: return []
        return [{"info": "Event log only supported on Windows currently."}]

    @staticmethod
    def sys_console_size():
        """Show console dimensions."""
        return {
            "width": get_console_width(),
            "height": get_console_height()
        }

    @staticmethod
    def env_list(filter_pattern: Optional[str] = None):
        """List environment variables."""
        results = []
        for key, val in sorted(os.environ.items()):
            if filter_pattern and filter_pattern.lower() not in key.lower():
                continue
            results.append({"variable": key, "value": val})
        return results

    @staticmethod
    def env_get(variable: str):
        """Fetch environment variable with expansion."""
        val = os.environ.get(variable)
        if val:
            expanded = os.path.expandvars(val)
            console.print(f"[bold green]{variable}=[/]{val}")
            if expanded != val:
                console.print(f"[bold yellow]Expanded:[/] {expanded}")
            return {"variable": variable, "value": val, "expanded": expanded}
        else:
            console.print(f"[red]Environment variable '{variable}' not found.[/]")
            return None

    @staticmethod
    def disk_usage(path: str = "/"):
        """Show disk usage for a path."""
        try:
            usage = psutil.disk_usage(path)
            from cross_platform.size_utils import format_bytes_binary
            return {
                "total": format_bytes_binary(usage.total),
                "used": format_bytes_binary(usage.used),
                "free": format_bytes_binary(usage.free),
                "percent": f"{usage.percent}%"
            }
        except: return {"error": "Path not accessible"}

    @staticmethod
    def disk_free():
        """Show free space on all drives."""
        results = []
        for part in psutil.disk_partitions():
            if sysu.is_windows() and "cdrom" in part.opts: continue
            try:
                usage = psutil.disk_usage(part.mountpoint)
                from cross_platform.size_utils import format_bytes_binary
                results.append({
                    "drive": part.mountpoint,
                    "free": format_bytes_binary(usage.free),
                    "percent_free": f"{100 - usage.percent}%"
                })
            except: pass
        return results

    @staticmethod
    def docker_ps():
        """List running docker containers."""
        if not shutil.which("docker"): return [{"error": "Docker not installed"}]
        out = sysu.run_command("docker ps --format '{{json .}}'")
        results = []
        for line in out.splitlines():
            try: results.append(json.loads(line))
            except: pass
        return results

    @staticmethod
    def docker_images():
        """List docker images."""
        if not shutil.which("docker"): return [{"error": "Docker not installed"}]
        out = sysu.run_command("docker images --format '{{json .}}'")
        results = []
        for line in out.splitlines():
            try: results.append(json.loads(line))
            except: pass
        return results

    @staticmethod
    def sys_cmd_search(pattern: str):
        """Find commands by fuzzy name match."""
        if sysu.is_windows():
            cmd = f"powershell -NoProfile -Command \"Get-Command *{pattern}* -ErrorAction SilentlyContinue | Select-Object Name, CommandType, Source | ConvertTo-Json\""
            out = sysu.run_command(cmd)
            try:
                data = json.loads(out)
                if isinstance(data, dict): data = [data]
                return data
            except: return []
        else:
            # Simple alias/bin search for posix
            out = sysu.run_command(f"compgen -c | grep '{pattern}'")
            return [{"command": line} for line in out.splitlines()]




    # ID additions
    @staticmethod
    def id_hostname():
        """Show hostname and FQDN."""
        return {
            "hostname": socket.gethostname(),
            "fqdn": socket.getfqdn()
        }

    @staticmethod
    def id_groups():
        """Show current user group memberships."""
        if sysu.is_windows():
            out = run_powershell("whoami /groups /fo csv | ConvertFrom-Csv | ConvertTo-Json")
            try:
                data = json.loads(out)
                if isinstance(data, dict): data = [data]
                return [{"group": g.get("Group Name"), "sid": g.get("SID")} for g in data]
            except: return []
        else:
            import grp
            groups = [g.gr_name for g in grp.getgrall() if os.getlogin() in g.gr_mem]
            return [{"group": g} for g in groups]

    @staticmethod
    def id_admin_check():
        """Explicitly report whether the current shell is elevated."""
        priv = PrivilegesManager()
        return {"elevated": priv.is_admin()}

    @staticmethod
    def id_sid():
        """Show Windows SID or Unix UID/GID."""
        if sysu.is_windows():
            out = run_powershell("whoami /user /fo csv | ConvertFrom-Csv | ConvertTo-Json")
            try:
                data = json.loads(out)
                if isinstance(data, dict): data = [data]
                return {"user": data[0].get("User Name"), "sid": data[0].get("SID")}
            except: return {}
        else:
            return {"uid": os.getuid(), "gid": os.getgid()}

    @staticmethod
    def id_sessions():
        """Show active sessions."""
        users = psutil.users()
        return [{
            "user": u.name,
            "terminal": u.terminal,
            "host": u.host,
            "started": datetime.fromtimestamp(u.started).strftime('%Y-%m-%d %H:%M:%S'),
            "pid": u.pid
        } for u in users]

    # NET additions
    @staticmethod
    def net_ping(host: str, count: int = 4):
        """Friendly connectivity test."""
        flag = "-n" if sysu.is_windows() else "-c"
        out = sysu.run_command(f"ping {flag} {count} {host}")
        return {"output": out}

    @staticmethod
    def net_resolve(domain: str):
        """Resolve hostname to records."""
        try:
            info = socket.getaddrinfo(domain, None)
            results = []
            for item in info:
                results.append({
                    "family": "IPv4" if item[0] == socket.AF_INET else "IPv6",
                    "address": item[4][0]
                })
            # Deduplicate
            return [dict(t) for t in {tuple(d.items()) for d in results}]
        except Exception as e:
            return [{"error": str(e)}]

    @staticmethod
    def net_reverse_dns(ip: str):
        """Reverse DNS lookup."""
        try:
            name, alias, addresslist = socket.gethostbyaddr(ip)
            return {"hostname": name, "aliases": alias}
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def net_ports():
        """Show listening ports with process names."""
        results = []
        for conn in psutil.net_connections(kind='inet'):
            if conn.status == 'LISTEN':
                try:
                    proc = psutil.Process(conn.pid)
                    name = proc.name()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    name = "Unknown"
                
                results.append({
                    "protocol": "TCP" if conn.type == socket.SOCK_STREAM else "UDP",
                    "address": f"{conn.laddr.ip}",
                    "port": conn.laddr.port,
                    "pid": conn.pid,
                    "process": name
                })
        return results

    @staticmethod
    def net_arp():
        """Show ARP cache."""
        if sysu.is_windows():
            out = sysu.run_command("arp -a")
            return [{"line": line} for line in out.splitlines() if line.strip()]
        else:
            out = sysu.run_command("ip neighbor show")
            return [{"neighbor": line} for line in out.splitlines()]

    # More PROC additions
    @staticmethod
    def proc_cmdline(pid: int):
        """Show full command line for a process."""
        try:
            p = psutil.Process(pid)
            return {"pid": pid, "name": p.name(), "cmdline": " ".join(p.cmdline())}
        except: return {"error": "Process not found"}

    @staticmethod
    def proc_threads(pid: int):
        """Show threads for a process."""
        try:
            p = psutil.Process(pid)
            threads = p.threads()
            return [{"id": t.id, "user_time": t.user_time, "system_time": t.system_time} for t in threads]
        except: return []

    @staticmethod
    def proc_handles(pid: int):
        """Show handle count (Windows) or FD count (Unix)."""
        try:
            p = psutil.Process(pid)
            if sysu.is_windows():
                return {"pid": pid, "handles": p.num_handles()}
            else:
                return {"pid": pid, "fds": p.num_fds()}
        except: return {"error": "Process not found"}

    # More SYS additions
    @staticmethod
    def sys_motherboard():
        """Motherboard information."""
        if sysu.is_windows():
            out = run_powershell("Get-CimInstance Win32_BaseBoard | Select-Object Manufacturer, Product, SerialNumber | ConvertTo-Json")
            try: return json.loads(out)
            except: return {}
        return {"info": "Not supported on this platform."}

    @staticmethod
    def sys_clipboard():
        """Show clipboard metadata."""
        if not CLIPBOARD_AVAILABLE: return {"error": "Not available"}
        text = get_clipboard()
        return {
            "length": len(text),
            "preview": text[:50] + "..." if len(text) > 50 else text
        }

    @staticmethod
    def sys_screen():
        """Display information (Windows)."""
        if sysu.is_windows():
            out = run_powershell("Get-CimInstance Win32_VideoController | Select-Object CurrentHorizontalResolution, CurrentVerticalResolution, CurrentRefreshRate | ConvertTo-Json")
            try: return json.loads(out)
            except: return {}
        return {"info": "Not supported on this platform."}


    @staticmethod
    def net_interfaces():
        """Detailed interface list."""
        results = []
        stats = psutil.net_if_stats()
        addrs = psutil.net_if_addrs()
        for name, stat in stats.items():
            ip_list = addrs.get(name, [])
            ipv4 = next((a.address for u in [ip_list] for a in u if a.family == socket.AF_INET), "N/A")
            results.append({
                "name": name,
                "status": "UP" if stat.isup else "DOWN",
                "speed": f"{stat.speed}Mbps",
                "mtu": stat.mtu,
                "ipv4": ipv4
            })
        return results

    @staticmethod
    def net_gateway():
        """Show default gateway."""
        if sysu.is_windows():
            out = run_powershell("Get-NetRoute -DestinationPrefix '0.0.0.0/0' | Select-Object NextHop, InterfaceAlias | ConvertTo-Json")
            try:
                data = json.loads(out)
                if isinstance(data, dict): data = [data]
                return [{"gateway": d.get("NextHop"), "interface": d.get("InterfaceAlias")} for d in data]
            except: return []
        else:
            # Simple fallback for linux
            out = sysu.run_command("ip route show default")
            match = re.search(r'default via (\S+) dev (\S+)', out)
            if match:
                return [{"gateway": match.group(1), "interface": match.group(2)}]
            return []

    @staticmethod
    def net_wifi():
        """Show WiFi details."""
        if sysu.is_windows():
            out = run_powershell("netsh wlan show interfaces | Out-String")
            return {"raw": out}
        elif sysu.is_linux():
            out = sysu.run_command("nmcli -t -f active,ssid,signal,bars,device device wifi | grep '^yes'")
            return {"info": out}
        return {"error": "Not supported on this platform."}

    # PROC additions
    @staticmethod
    def proc_tree(pid: Optional[int] = None):
        """Show process tree."""
        root_pid = pid or os.getpid()
        try:
            root = psutil.Process(root_pid)
            tree = []
            def build_tree(p, depth=0):
                tree.append({
                    "depth": depth,
                    "pid": p.pid,
                    "name": p.name(),
                    "display": "  " * depth + f"|- {p.name()} ({p.pid})"
                })
                for child in p.children():
                    try: build_tree(child, depth + 1)
                    except: pass
            build_tree(root)
            return tree
        except: return []

    @staticmethod
    def proc_find(pattern: str):
        """Find processes by name or command line."""
        results = []
        for p in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                if pattern.lower() in p.info['name'].lower() or \
                   (p.info['cmdline'] and pattern.lower() in " ".join(p.info['cmdline']).lower()):
                    results.append({
                        "pid": p.info['pid'],
                        "name": p.info['name'],
                        "cmdline": " ".join(p.info['cmdline']) if p.info['cmdline'] else ""
                    })
            except: pass
        return results

    @staticmethod
    def proc_find_detailed(
        pid: Optional[int] = None,
        query: Optional[str] = None,
        name: Optional[str] = None,
        cmdline: bool = False,
        exe: bool = False,
        path: Optional[str] = None,
        regex: bool = False,
        fuzzy: bool = False,
        cim: bool = False,
    ):
        """Find processes with detailed matching options."""
        if cim and query:
            return windows_cim_process_search(query)
        return find_processes(
            ProcessQuery(pid=pid, query=query, name=name, cmdline=cmdline, exe=exe, path=path, regex=regex, fuzzy=fuzzy)
        )

    @staticmethod
    def proc_parents(pid: int):
        """Show parent process chain."""
        return process_parents(pid)

    @staticmethod
    def proc_children(pid: int, recursive: bool = False):
        """Show child processes."""
        rows = proc_tools_tree(pid, include_root=False)
        if recursive:
            return rows
        return [row for row in rows if row.get("depth") == 0]

    @staticmethod
    def proc_action(
        action: str,
        pid: Optional[int] = None,
        query: Optional[str] = None,
        name: Optional[str] = None,
        cmdline: bool = False,
        exe: bool = False,
        path: Optional[str] = None,
        regex: bool = False,
        fuzzy: bool = False,
        recursive: bool = False,
        force: bool = False,
        dry_run: bool = True,
        confirm: bool = False,
    ):
        """Apply or preview a process action."""
        return act_on_processes(
            action,
            pid=pid,
            query=query,
            name=name,
            cmdline=cmdline,
            exe=exe,
            path=path,
            regex=regex,
            fuzzy=fuzzy,
            recursive=recursive,
            force=force,
            dry_run=dry_run,
            confirm=confirm,
        )

    @staticmethod
    def proc_stats(pid: int, interval: float = 1.0, samples: int = 1, include_tree: bool = False):
        """Sample process resource usage."""
        return sample_process_stats(pid, interval=interval, samples=samples, include_tree=include_tree)

    @staticmethod
    def help_search(query: str, regex: bool = False, fuzzy: bool = False):
        """Search system_manager command metadata."""
        return search_commands(query, regex=regex, fuzzy=fuzzy)

    @staticmethod
    def proc_kill(pid_or_name: str, force: bool = False):
        """Kill by PID or name."""
        target_pids = []
        if pid_or_name.isdigit():
            target_pids.append(int(pid_or_name))
        else:
            for p in psutil.process_iter(['pid', 'name']):
                if pid_or_name.lower() in p.info['name'].lower():
                    target_pids.append(p.info['pid'])
        
        results = []
        for pid in target_pids:
            try:
                p = psutil.Process(pid)
                if force: p.kill()
                else: p.terminate()
                results.append({"pid": pid, "status": "Killed" if force else "Terminated"})
            except Exception as e:
                results.append({"pid": pid, "error": str(e)})
        return results

    # SYS additions
    @staticmethod
    def sys_gpu():
        """GPU information."""
        if sysu.is_windows():
            out = run_powershell("Get-CimInstance Win32_VideoController | Select-Object Name, AdapterRAM, DriverVersion | ConvertTo-Json")
            try:
                data = json.loads(out)
                if isinstance(data, dict): data = [data]
                from cross_platform.size_utils import format_bytes_binary
                return [{
                    "name": d.get("Name"),
                    "vram": format_bytes_binary(d.get("AdapterRAM", 0)) if d.get("AdapterRAM") else "N/A",
                    "driver": d.get("DriverVersion")
                } for d in data]
            except: return []
        else:
            # Fallback for linux (lspci)
            out = sysu.run_command("lspci | grep -i vga")
            return [{"info": out}]

    @staticmethod
    def sys_bios():
        """BIOS information."""
        if sysu.is_windows():
            out = run_powershell("Get-CimInstance Win32_BIOS | Select-Object Manufacturer, Version, ReleaseDate | ConvertTo-Json")
            try:
                data = json.loads(out)
                return {
                    "vendor": data.get("Manufacturer"),
                    "version": data.get("Version"),
                    "date": data.get("ReleaseDate")
                }
            except: return {}
        else:
            vendor = sysu.run_command("cat /sys/class/dmi/id/bios_vendor 2>/dev/null")
            version = sysu.run_command("cat /sys/class/dmi/id/bios_version 2>/dev/null")
            return {"vendor": vendor, "version": version}

    @staticmethod
    def sys_reboot_required():
        """Check if reboot is pending."""
        if sysu.is_windows():
            out = run_powershell("Test-Path 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Component Based Servicing\\RebootPending'")
            return {"reboot_required": "True" in out}
        else:
            return {"reboot_required": os.path.exists("/var/run/reboot-required")}

    # PKG additions
    @staticmethod
    def pkg_list(manager: Optional[str] = None):
        """List packages."""
        from cross_platform.package_manager import detect_package_managers
        mgrs = detect_package_managers()
        if not manager:
            # Pick first available
            manager = next((m for m, av in mgrs.items() if av), "pip")
        
        results = []
        if manager == "pip":
            out = sysu.run_command("pip list --format=json")
            try:
                data = json.loads(out)
                return [{"name": p["name"], "version": p["version"]} for p in data]
            except: pass
        elif manager == "winget" and sysu.is_windows():
            # winget list is slow, we'll just return first few or summarized
            return [{"info": "Run 'winget list' for full list"}]
        
        return results

    @staticmethod
    def pkg_outdated():
        """Check for outdated packages."""
        # Focus on pip for cross-platform demo
        out = sysu.run_command("pip list --outdated --format=json")
        try:
            data = json.loads(out)
            return [{
                "name": p["name"],
                "current": p["version"],
                "latest": p["latest_version"]
            } for p in data]
        except: return []

    # More Net additions
    @staticmethod
    def net_trace(host: str):
        """Traceroute / tracert wrapper."""
        cmd = f"tracert {host}" if sysu.is_windows() else f"traceroute {host}"
        console.print(f"Tracing route to {host}...")
        subprocess.run(cmd, shell=True)
        return {"status": "Complete"}

    @staticmethod
    def net_http_head(url: str):
        """Fetch HTTP headers."""
        try:
            res = requests.head(url, timeout=10)
            return dict(res.headers)
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def net_tls(host: str, port: int = 443):
        """Inspect TLS cert info."""
        import ssl
        context = ssl.create_default_context()
        try:
            with socket.create_connection((host, port)) as sock:
                with context.wrap_socket(sock, server_hostname=host) as ssock:
                    cert = sock.getpeercert()
                    return cert
        except Exception as e:
            return {"error": str(e)}

    # More Sys additions
    @staticmethod
    def sys_temps():
        """CPU/GPU temperatures."""
        try:
            temps = psutil.sensors_temperatures()
            results = []
            for name, entries in temps.items():
                for entry in entries:
                    results.append({
                        "sensor": name,
                        "label": entry.label or "N/A",
                        "current": f"{entry.current}°C"
                    })
            return results
        except:
            return [{"info": "Temperature sensors not accessible."}]

    @staticmethod
    def sys_eventlog(count: int = 20):
        """Query recent system errors/warnings."""
        if sysu.is_windows():
            out = run_powershell(f"Get-EventLog -LogName System -EntryType Error,Warning -Newest {count} | Select-Object TimeGenerated, Source, Message | ConvertTo-Json")
            try:
                data = json.loads(out)
                if isinstance(data, dict): data = [data]
                return [{
                    "time": d.get("TimeGenerated"),
                    "source": d.get("Source"),
                    "message": d.get("Message", "")[:100] + "..."
                } for d in data]
            except: return []
        else:
            out = sysu.run_command(f"journalctl -p 3..4 -n {count} --no-pager")
            return [{"journal": line} for line in out.splitlines()]

    # Env Path management
    @staticmethod
    def env_path_user():
        """List user-defined PATH variables."""
        from file_utils.path_ops import list_paths
        return [{"path": p} for p in list_paths("user")]

    @staticmethod
    def env_path_machine():
        """List machine PATH variables."""
        from file_utils.path_ops import list_paths
        try:
            return [{"path": p} for p in list_paths("machine")]
        except: return []

    @staticmethod
    def env_path_verify(directory: str):
        """Verify if a folder is on PATH."""
        target = str(Path(directory).resolve()).lower()
        paths = os.environ.get("PATH", "").split(os.pathsep)
        found = False
        for p in paths:
            try:
                if str(Path(p).resolve()).lower() == target:
                    found = True
                    break
            except: continue
        return {"directory": directory, "on_path": found}

    # File additions
    @staticmethod
    def file_recent(directory: str = ".", count: int = 20, recursive: bool = False):
        """Find the N most recently modified files."""
        root = Path(directory).resolve()
        files = []
        glob_pattern = "**/*" if recursive else "*"
        for p in root.glob(glob_pattern):
            if p.is_file():
                try:
                    files.append({
                        "path": str(p),
                        "mtime": p.stat().st_mtime,
                        "name": p.name,
                        "modified": datetime.fromtimestamp(p.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                    })
                except OSError: pass
        
        return sorted(files, key=lambda x: x['mtime'], reverse=True)[:count]

    @staticmethod
    def file_largest(directory: str = ".", count: int = 25, recursive: bool = False):
        """Find the largest files in a tree."""
        root = Path(directory).resolve()
        files = []
        glob_pattern = "**/*" if recursive else "*"
        for p in root.glob(glob_pattern):
            if p.is_file():
                try:
                    files.append({
                        "path": str(p),
                        "size": p.stat().st_size,
                        "name": p.name
                    })
                except OSError: pass

        return sorted(files, key=lambda x: x['size'], reverse=True)[:count]

    @staticmethod
    def file_grep(pattern: str, directory: str = ".", recursive: bool = False):
        """Search text files for a literal pattern."""
        root = Path(directory).resolve()
        results = []
        glob_pattern = "**/*" if recursive else "*"
        for path in root.glob(glob_pattern):
            if not path.is_file():
                continue
            try:
                with path.open("r", encoding="utf-8") as handle:
                    for line_number, line in enumerate(handle, start=1):
                        if pattern in line:
                            results.append(
                                {
                                    "path": str(path),
                                    "line_number": line_number,
                                    "line": line.rstrip("\n"),
                                }
                            )
            except (OSError, UnicodeDecodeError):
                continue
        return results

    @staticmethod
    def file_size(directory: str = ".", recursive: bool = True):
        """Measure total size of a folder."""
        from cross_platform.size_utils import format_bytes_binary
        root = Path(directory).resolve()
        total = 0
        count = 0
        it = root.rglob('*') if recursive else root.iterdir()
        for p in it:
            if p.is_file():
                try:
                    total += p.stat().st_size
                    count += 1
                except OSError: pass
        
        return {
            "folder": str(root),
            "total_size": format_bytes_binary(total),
            "file_count": count,
            "bytes": total
        }

    @staticmethod
    def sys_console_size():
        """Show console dimensions."""
        return {
            "width": get_console_width(),
            "height": get_console_height()
        }

    @staticmethod
    def env_list(filter_pattern: Optional[str] = None):
        """List environment variables."""
        results = []
        for key, val in sorted(os.environ.items()):
            if filter_pattern and filter_pattern.lower() not in key.lower():
                continue
            results.append({"variable": key, "value": val})
        return results

    @staticmethod
    def env_get(variable: str):
        """Fetch environment variable with expansion."""
        val = os.environ.get(variable)
        if val:
            expanded = os.path.expandvars(val)
            console.print(f"[bold green]{variable}=[/]{val}")
            if expanded != val:
                console.print(f"[bold yellow]Expanded:[/] {expanded}")
            return {"variable": variable, "value": val, "expanded": expanded}
        else:
            console.print(f"[red]Environment variable '{variable}' not found.[/]")
            return None

    @staticmethod
    def disk_usage(path: str = "/"):
        """Show disk usage for a path."""
        try:
            usage = psutil.disk_usage(path)
            from cross_platform.size_utils import format_bytes_binary
            return {
                "total": format_bytes_binary(usage.total),
                "used": format_bytes_binary(usage.used),
                "free": format_bytes_binary(usage.free),
                "percent": f"{usage.percent}%"
            }
        except: return {"error": "Path not accessible"}

    @staticmethod
    def disk_free():
        """Show free space on all drives."""
        results = []
        for part in psutil.disk_partitions():
            if sysu.is_windows() and "cdrom" in part.opts: continue
            try:
                usage = psutil.disk_usage(part.mountpoint)
                from cross_platform.size_utils import format_bytes_binary
                results.append({
                    "drive": part.mountpoint,
                    "free": format_bytes_binary(usage.free),
                    "percent_free": f"{100 - usage.percent}%"
                })
            except: pass
        return results

    @staticmethod
    def docker_ps():
        """List running docker containers."""
        if not shutil.which("docker"): return [{"error": "Docker not installed"}]
        out = sysu.run_command("docker ps --format '{{json .}}'")
        results = []
        for line in out.splitlines():
            try: results.append(json.loads(line))
            except: pass
        return results

    @staticmethod
    def docker_images():
        """List docker images."""
        if not shutil.which("docker"): return [{"error": "Docker not installed"}]
        out = sysu.run_command("docker images --format '{{json .}}'")
        results = []
        for line in out.splitlines():
            try: results.append(json.loads(line))
            except: pass
        return results

    @staticmethod
    def proc_owner(pid: Optional[int] = None, name: Optional[str] = None):
        """Show owner and executable path of a running process."""
        results = []
        for p in psutil.process_iter(['pid', 'name', 'username', 'exe']):
            try:
                match = False
                if pid is not None and p.info['pid'] == pid: match = True
                elif name is not None and name.lower() in p.info['name'].lower(): match = True
                elif pid is None and name is None: match = True # List all if no filters
                
                if match:
                    results.append({
                        "pid": p.info['pid'],
                        "name": p.info['name'],
                        "owner": p.info['username'] or "Unknown",
                        "path": p.info['exe'] or "N/A"
                    })
            except (psutil.NoSuchProcess, psutil.AccessDenied): pass
        return results

    # PERM additions
    @staticmethod
    def perm_show(path: str):
        """Show full ACL details for a path."""
        if sysu.is_windows():
            script = f"Get-Acl -LiteralPath '{path}' | Select-Object Path, Owner, Group, AreAccessRulesProtected, AccessToString, Sddl | ConvertTo-Json"
            out = run_powershell(script)
            try: return json.loads(out)
            except: return {"error": "Failed to get ACL"}
        else:
            st = os.stat(path)
            return {
                "path": path,
                "uid": st.st_uid,
                "gid": st.st_gid,
                "mode": oct(st.st_mode)
            }

    @staticmethod
    def perm_scan_protected(directory: str, recursive: bool = True, directories_only: bool = True):
        """List files or folders with inheritance disabled."""
        if not sysu.is_windows(): return []
        filter_cmd = "Where-Object { $_.PSIsContainer }" if directories_only else ""
        script = f"Get-ChildItem -LiteralPath '{directory}' {'-Recurse' if recursive else ''} -Force -ErrorAction SilentlyContinue | {filter_cmd} | ForEach-Object {{ $acl = Get-Acl -LiteralPath $_.FullName; if ($acl.AreAccessRulesProtected) {{ [pscustomobject]@{{ Path=$_.FullName; Owner=$acl.Owner; InheritanceDisabled=$true }} }} }} | ConvertTo-Json"
        out = run_powershell(script)
        try:
            data = json.loads(out)
            if isinstance(data, dict): data = [data]
            return data
        except: return []

    @staticmethod
    def perm_scan_missing_read(directory: str, user: Optional[str] = None, principals: Optional[List[str]] = None, recursive: bool = True):
        """List folders that do not appear to grant read access to target user or common principals."""
        if not sysu.is_windows(): return []
        
        target_user = user or os.environ.get("USERNAME")
        extra_principals = principals or []
        all_principals = [target_user, "BUILTIN\\Administrators", "BUILTIN\\Users", "NT AUTHORITY\\Authenticated Users", "Everyone"] + extra_principals
        
        # Build PS array string
        principals_array = "@('" + "','".join(all_principals) + "')"
        
        script = f"""
        $Principals = {principals_array}
        Get-ChildItem -LiteralPath '{directory}' {'-Recurse' if recursive else ''} -Directory -Force -ErrorAction SilentlyContinue | ForEach-Object {{
            $acl = Get-Acl -LiteralPath $_.FullName
            $matched = $acl.Access | Where-Object {{ $_.IdentityReference.Value -in $Principals -and ($_.FileSystemRights -match 'Read' -or $_.FileSystemRights -match 'FullControl') }}
            if (-not $matched) {{
                [pscustomobject]@{{
                    Path = $_.FullName
                    Owner = $acl.Owner
                    InheritanceDisabled = $acl.AreAccessRulesProtected
                    MatchingReadPrincipalCount = 0
                }}
            }}
        }} | ConvertTo-Json
        """
        out = run_powershell(script)
        try:
            data = json.loads(out)
            if isinstance(data, dict): data = [data]
            return data
        except: return []

    @staticmethod
    def perm_compare(good_path: str, bad_path: str, show_sddl: bool = False):
        """Compare ACLs between two paths."""
        if sysu.is_windows():
            script = f"""
            $g = Get-Acl -LiteralPath '{good_path}'
            $b = Get-Acl -LiteralPath '{bad_path}'
            [pscustomobject]@{{
                GoodPath = '{good_path}'
                BadPath = '{bad_path}'
                OwnerMatch = $g.Owner -eq $b.Owner
                InheritanceMatch = $g.AreAccessRulesProtected -eq $b.AreAccessRulesProtected
                AceCountMatch = $g.Access.Count -eq $b.Access.Count
                SddlMatch = $g.Sddl -eq $b.Sddl
                GoodOwner = $g.Owner
                BadOwner = $b.Owner
                GoodInheritanceDisabled = $g.AreAccessRulesProtected
                BadInheritanceDisabled = $b.AreAccessRulesProtected
                GoodAceCount = $g.Access.Count
                BadAceCount = $b.Access.Count
                { "GoodSddl = $g.Sddl; BadSddl = $b.Sddl" if show_sddl else "" }
            }} | ConvertTo-Json
            """
            out = run_powershell(script)
            try: return json.loads(out)
            except: return {"error": "Comparison failed"}
        return {"error": "Comparison only supported on Windows."}

    @staticmethod
    def perm_test_read(directory: str, recursive: bool = True, max_errors: int = 100, quiet_success: bool = True):
        """Recursively attempt to open files for reading and report failures."""
        processed = 0
        failed = []
        root = Path(directory).resolve()
        it = root.rglob("*") if recursive else root.iterdir()
        
        for p in it:
            if p.is_file():
                processed += 1
                try:
                    with p.open("rb") as f: f.read(1)
                except Exception as e:
                    failed.append({"path": str(p), "error": str(e)})
                    if len(failed) >= max_errors: break
        
        return {
            "summary": {"FilesProcessed": processed, "FilesFailed": len(failed)},
            "failures": failed
        }

    @staticmethod
    def perm_normalize(path: str, user: Optional[str] = None, rights: str = "read", apply: bool = False):
        """Repair a subtree by taking ownership, enabling inheritance, granting access, and resetting ACLs."""
        if not sysu.is_windows(): return [{"error": "Windows only"}]
        
        target_user = user or os.environ.get("USERNAME")
        rights_map = {"read": "RX", "modify": "M", "full": "F"}
        r = rights_map.get(rights.lower(), rights)
        
        # Steps to perform
        steps = [
            ("takeown", f"takeown /F \"{path}\" /R /D Y"),
            ("setowner", f"icacls \"{path}\" /setowner \"{target_user}\" /T /C /Q"),
            ("grant", f"icacls \"{path}\" /grant:r \"{target_user}:(OI)(CI){r}\" /T /C /Q"),
            ("inheritance", f"icacls \"{path}\" /inheritance:e /T /C /Q"),
            ("reset", f"icacls \"{path}\" /reset /T /C /Q")
        ]
        
        results = []
        processed = 0
        errors = 0
        
        for name, cmd in steps:
            results.append({
                "Step": name,
                "Command": cmd,
                "Status": "Applied" if apply else "Preview"
            })
            if apply:
                try:
                    out = sysu.run_command(cmd)
                    if "failed" in out.lower() or "denied" in out.lower():
                        results[-1]["Status"] = "Partial Failure"
                        results[-1]["Output"] = out[:200] + "..."
                        errors += 1
                except Exception as e:
                    results[-1]["Status"] = "Error"
                    results[-1]["Error"] = str(e)
                    errors += 1
        
        # Summary
        summary = {
            "Target": path,
            "ApplyMode": apply,
            "StepsTotal": len(steps),
            "Errors": errors,
            "Status": "Completed with errors" if errors > 0 and apply else ("Success" if apply else "Preview")
        }
        
        return {"summary": summary, "steps": results}





