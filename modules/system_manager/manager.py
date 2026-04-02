#!/usr/bin/env python3
"""
System Manager Implementation

Contains the logic for 25+ useful cross-platform system commands.
"""

import os
import sys
import platform
import subprocess
import time
import socket
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Any

import psutil
import requests
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.live import Live

from cross_platform import SystemUtils, ClipboardUtils, NetworkUtils, ProcessManager, PrivilegesManager

console = Console()
sysu = SystemUtils()

class SystemManager:
    """Core implementation of system management commands."""

    @staticmethod
    def whoami():
        """Show current user and elevation status."""
        priv = PrivilegesManager()
        is_admin = priv.is_admin()
        status = "[bold red]Elevated (Admin/Root)[/]" if is_admin else "[yellow]Standard User[/]"
        
        table = Table(title="Identity Info")
        table.add_column("Property")
        table.add_column("Value")
        
        table.add_row("Username", os.getlogin() if hasattr(os, "getlogin") else os.environ.get("USER", "unknown"))
        table.add_row("Home", str(Path.home()))
        table.add_row("Status", status)
        table.add_row("OS Name", sysu.os_name)
        
        console.print(table)

    @staticmethod
    def public_ip():
        """Fetch public IP address."""
        try:
            response = requests.get("https://api.ipify.org?format=json", timeout=5)
            ip = response.json().get("ip")
            console.print(f"[bold green]Public IP:[/] {ip}")
        except Exception as e:
            console.print(f"[bold red]Error fetching public IP:[/] {e}")

    @staticmethod
    def local_ip():
        """List all local IP addresses."""
        table = Table(title="Local Network Interfaces")
        table.add_column("Interface")
        table.add_column("Address")
        table.add_column("Netmask")

        for interface, addrs in psutil.net_if_addrs().items():
            for addr in addrs:
                if addr.family == socket.AF_INET:
                    table.add_row(interface, addr.address, addr.netmask or "N/A")
        
        console.print(table)

    @staticmethod
    def uptime():
        """Show system boot time and duration."""
        boot_time_timestamp = psutil.boot_time()
        bt = datetime.fromtimestamp(boot_time_timestamp)
        now = datetime.now()
        uptime_delta = now - bt
        
        # Format uptime string
        days = uptime_delta.days
        hours, remainder = divmod(uptime_delta.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        uptime_str = f"{days}d {hours}h {minutes}m {seconds}s"
        
        console.print(Panel(
            f"[bold cyan]Uptime:[/] {uptime_str}\n"
            f"[bold cyan]Booted at:[/] {bt.strftime('%Y-%m-%d %H:%M:%S')}",
            title="System Uptime"
        ))

    @staticmethod
    def port_scan(start_port: int = 1, end_port: int = 1024):
        """Check for open local ports."""
        console.print(f"Scanning local ports {start_port}-{end_port}...")
        open_ports = []
        
        # Use net_connections for efficiency if possible
        try:
            for conn in psutil.net_connections():
                if conn.status == 'LISTEN' and start_port <= conn.laddr.port <= end_port:
                    open_ports.append(conn.laddr.port)
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            # Fallback to socket scanning if psutil fails (less efficient but reliable)
            for port in range(start_port, end_port + 1):
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(0.01)
                    if s.connect_ex(('127.0.0.1', port)) == 0:
                        open_ports.append(port)

        if open_ports:
            console.print(f"[bold green]Open Ports:[/] {', '.join(map(str, sorted(list(set(open_ports)))))}")
        else:
            console.print("[yellow]No open ports found in range.[/]")

    @staticmethod
    def battery():
        """Show battery status."""
        battery = psutil.sensors_battery()
        if battery is None:
            console.print("[yellow]No battery detected (System is likely plugged into AC).[/]")
            return

        percent = battery.percent
        plugged = battery.power_plugged
        status = "Charging" if plugged else "Discharging"
        color = "green" if percent > 50 else ("yellow" if percent > 20 else "red")
        
        console.print(Panel(
            f"[{color}]Charge:[/] {percent}%\n"
            f"[bold]Source:[/] {'AC Power' if plugged else 'Battery'}\n"
            f"[bold]Status:[/] {status}",
            title="Battery Status"
        ))

    @staticmethod
    def timezone():
        """Show current timezone details."""
        now = datetime.now()
        local_now = now.astimezone()
        tz_name = local_now.tzname()
        utc_offset = local_now.utcoffset()
        
        console.print(f"[bold cyan]Timezone:[/] {tz_name}")
        console.print(f"[bold cyan]UTC Offset:[/] {utc_offset}")
        console.print(f"[bold cyan]Local Time:[/] {now.strftime('%Y-%m-%d %H:%M:%S')}")

    @staticmethod
    def cpu_info():
        """Show CPU details."""
        table = Table(title="CPU Information")
        table.add_column("Property")
        table.add_column("Value")
        
        table.add_row("Physical Cores", str(psutil.cpu_count(logical=False)))
        table.add_row("Logical Cores", str(psutil.cpu_count(logical=True)))
        
        freq = psutil.cpu_freq()
        if freq:
            table.add_row("Max Frequency", f"{freq.max:.2f} MHz")
            table.add_row("Current Frequency", f"{freq.current:.2f} MHz")
        
        load = psutil.cpu_percent(interval=1)
        table.add_row("Current Load", f"{load}%")
        
        console.print(table)

    @staticmethod
    def mem_info():
        """Show memory usage summary."""
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()
        
        from cross_platform.size_utils import format_bytes_binary
        
        table = Table(title="Memory Usage")
        table.add_column("Type")
        table.add_column("Total")
        table.add_column("Used")
        table.add_column("Free")
        table.add_column("Percent")
        
        table.add_row("RAM", 
                      format_bytes_binary(mem.total), 
                      format_bytes_binary(mem.used), 
                      format_bytes_binary(mem.available), 
                      f"{mem.percent}%")
        
        table.add_row("Swap", 
                      format_bytes_binary(swap.total), 
                      format_bytes_binary(swap.used), 
                      format_bytes_binary(swap.free), 
                      f"{swap.percent}%")
        
        console.print(table)

    @staticmethod
    def disk_list():
        """List partitions and mount points."""
        from cross_platform.size_utils import format_bytes_binary
        
        table = Table(title="Disk Partitions")
        table.add_column("Device")
        table.add_column("Mount Point")
        table.add_column("Type")
        table.add_column("Total")
        table.add_column("Used")
        table.add_column("Free")
        
        for part in psutil.disk_partitions():
            try:
                usage = psutil.disk_usage(part.mountpoint)
                table.add_row(
                    part.device,
                    part.mountpoint,
                    part.fstype,
                    format_bytes_binary(usage.total),
                    format_bytes_binary(usage.used),
                    format_bytes_binary(usage.free)
                )
            except PermissionError:
                table.add_row(part.device, part.mountpoint, part.fstype, "N/A", "N/A", "N/A")
        
        console.print(table)

    @staticmethod
    def sys_id():
        """Show unique system ID."""
        if sysu.is_windows():
            # MachineGuid from registry
            cmd = 'reg query "HKEY_LOCAL_MACHINE\\SOFTWARE\\Microsoft\\Cryptography" /v MachineGuid'
            out = sysu.run_command(cmd)
            match = re.search(r'MachineGuid\s+REG_SZ\s+([a-fA-F0-9-]+)', out)
            machine_id = match.group(1) if match else "Unknown"
        else:
            # /etc/machine-id on Linux
            try:
                machine_id = Path("/etc/machine-id").read_text().strip()
            except:
                try:
                    machine_id = Path("/var/lib/dbus/machine-id").read_text().strip()
                except:
                    machine_id = "Unknown"
        
        console.print(f"[bold cyan]System Machine ID:[/] {machine_id}")

    @staticmethod
    def env_get(variable: str):
        """Fetch environment variable with expansion."""
        val = os.environ.get(variable)
        if val:
            expanded = os.path.expandvars(val)
            console.print(f"[bold green]{variable}=[/]{val}")
            if expanded != val:
                console.print(f"[bold yellow]Expanded:[/] {expanded}")
        else:
            console.print(f"[red]Environment variable '{variable}' not found.[/]")

    @staticmethod
    def path_clean():
        """List PATH entries and highlight missing ones."""
        paths = os.environ.get("PATH", "").split(os.pathsep)
        table = Table(title="System PATH Analysis")
        table.add_column("#", justify="right")
        table.add_column("Status")
        table.add_column("Path")
        
        for i, p in enumerate(paths, 1):
            exists = Path(p).exists()
            status = "[green]OK[/]" if exists else "[red]Missing[/]"
            table.add_row(str(i), status, p)
            
        console.print(table)

    @staticmethod
    def shell_info():
        """Show shell information."""
        shell_path = os.environ.get("SHELL", "Unknown")
        shell_name = Path(shell_path).name
        
        console.print(f"[bold cyan]Current Shell:[/] {shell_name}")
        console.print(f"[bold cyan]Shell Path:[/] {shell_path}")
        
        # Check for history file
        hist_file = os.environ.get("HISTFILE")
        if not hist_file:
            if "zsh" in shell_name:
                hist_file = "~/.zsh_history"
            elif "bash" in shell_name:
                hist_file = "~/.bash_history"
        
        if hist_file:
            hist_path = Path(hist_file).expanduser()
            if hist_path.exists():
                console.print(f"[bold cyan]History File:[/] {hist_path}")
                console.print(f"[bold cyan]History Size:[/] {hist_path.stat().st_size} bytes")

    @staticmethod
    def os_detail():
        """Show detailed OS info."""
        console.print(f"[bold cyan]OS System:[/] {platform.system()}")
        console.print(f"[bold cyan]OS Release:[/] {platform.release()}")
        console.print(f"[bold cyan]OS Version:[/] {platform.version()}")
        console.print(f"[bold cyan]Architecture:[/] {platform.machine()}")
        if hasattr(platform, "freedesktop_os_release"):
            try:
                info = platform.freedesktop_os_release()
                console.print(f"[bold cyan]Distro:[/] {info.get('PRETTY_NAME', 'Unknown')}")
            except: pass

    @staticmethod
    def dns_check(domain: str):
        """Test DNS resolution for a domain."""
        try:
            addr = socket.gethostbyname(domain)
            console.print(f"[bold green]{domain}[/] resolves to [bold white]{addr}[/]")
        except Exception as e:
            console.print(f"[bold red]DNS lookup failed for {domain}:[/] {e}")

    @staticmethod
    def internet_test():
        """Check internet latency."""
        try:
            start = time.time()
            requests.get("https://www.google.com", timeout=5)
            latency = (time.time() - start) * 1000
            console.print(f"[bold green]Internet is UP.[/] Latency to Google: {latency:.2f}ms")
        except Exception:
            console.print("[bold red]Internet appears to be DOWN.[/]")

    @staticmethod
    def process_top(count: int = 5):
        """Show top processes by CPU usage."""
        procs = []
        for p in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_info']):
            try:
                procs.append(p.info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        
        # Sort by CPU
        top_cpu = sorted(procs, key=lambda x: x['cpu_percent'], reverse=True)[:count]
        
        table = Table(title=f"Top {count} Processes (CPU)")
        table.add_column("PID", justify="right")
        table.add_column("Name")
        table.add_column("CPU %", justify="right")
        table.add_column("Memory", justify="right")
        
        from cross_platform.size_utils import format_bytes_binary
        for p in top_cpu:
            table.add_row(
                str(p['pid']),
                p['name'],
                f"{p['cpu_percent']}%",
                format_bytes_binary(p['memory_info'].rss)
            )
        console.print(table)

    @staticmethod
    def service_list():
        """List active system services."""
        if sysu.is_windows():
            cmd = "powershell -NoProfile -Command Get-Service | Where-Object { $_.Status -eq 'Running' } | Select-Object -First 20"
            out = sysu.run_command(cmd)
            console.print(Panel(out, title="Running Windows Services (First 20)"))
        elif sysu.is_linux() and not sysu.is_termux():
            cmd = "systemctl list-units --type=service --state=running --no-pager | head -n 20"
            out = sysu.run_command(cmd)
            console.print(Panel(out, title="Active Linux Services (First 20)"))
        else:
            console.print("[yellow]Service listing not supported on this environment.[/]")

    @staticmethod
    def usb_list():
        """List connected USB devices."""
        if sysu.is_windows():
            cmd = 'powershell -NoProfile -Command "Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -match \'USB\' } | Select-Object FriendlyName, InstanceId | Format-Table -AutoSize"'
            out = sysu.run_command(cmd)
            console.print(Panel(out, title="USB Devices (Windows)"))
        elif sysu.is_linux():
            out = sysu.run_command("lsusb")
            console.print(Panel(out, title="USB Devices (lsusb)"))
        else:
            console.print("[yellow]USB listing not supported on this environment.[/]")

    @staticmethod
    def hw_serial():
        """Get hardware serial number."""
        if sysu.is_windows():
            out = sysu.run_command("wmic bios get serialnumber")
            console.print(f"[bold cyan]System Serial:[/] {out.strip().splitlines()[-1] if out else 'Unknown'}")
        elif sysu.is_linux() and not sysu.is_termux():
            out = sysu.run_command("cat /sys/class/dmi/id/product_serial 2>/dev/null || cat /sys/class/dmi/id/board_serial 2>/dev/null", sudo=True)
            console.print(f"[bold cyan]System Serial:[/] {out.strip() or 'Unknown (require sudo?)'}")
        else:
            console.print("[yellow]Hardware serial not accessible in this environment.[/]")

    @staticmethod
    def pkg_stats():
        """Count installed packages via detected managers."""
        from cross_platform.package_manager import detect_package_managers
        mgrs = detect_package_managers()
        
        table = Table(title="Package Manager Stats")
        table.add_column("Manager")
        table.add_column("Status")
        table.add_column("Installed Count")
        
        for mgr, available in mgrs.items():
            count = "N/A"
            if available:
                if mgr == "pip":
                    out = sysu.run_command("pip list --format=json")
                    try: count = len(json.loads(out))
                    except: pass
                elif mgr == "brew":
                    out = sysu.run_command("brew list | wc -l")
                    count = out.strip()
                elif mgr == "pkg" and sysu.is_termux():
                    out = sysu.run_command("pkg list-installed | wc -l")
                    count = out.strip()
                elif mgr == "apt":
                    out = sysu.run_command("dpkg -l | grep '^ii' | wc -l")
                    count = out.strip()
            
            table.add_row(mgr, "[green]Present[/]" if available else "[red]Missing[/]", str(count))
            
        console.print(table)

    @staticmethod
    def time_sync():
        """Check time drift against a public time server."""
        # This is a mock drift check using an HTTP header from Google
        try:
            start = time.time()
            res = requests.head("https://www.google.com", timeout=5)
            server_date = res.headers.get("date")
            if server_date:
                # Parse HTTP date: Sat, 18 Oct 2014 16:27:35 GMT
                server_time = datetime.strptime(server_date, "%a, %d %b %Y %H:%M:%S %Z")
                local_time = datetime.utcnow()
                drift = (server_time - local_time).total_seconds()
                console.print(f"[bold cyan]Public Server Time (Google):[/] {server_time}")
                console.print(f"[bold cyan]Local UTC Time:[/] {local_time.strftime('%Y-%m-%d %H:%M:%S')}")
                console.print(f"[bold {'green' if abs(drift) < 2 else 'red'}]Drift:[/] {drift:.2f} seconds")
        except Exception as e:
            console.print(f"[red]Time sync check failed:[/] {e}")

    @staticmethod
    def weather():
        """Quick weather summary."""
        try:
            # wttr.in format: ?format=3 is a single line
            res = requests.get("https://wttr.in?format=3", timeout=5)
            console.print(Panel(res.text.strip(), title="Current Weather"))
        except Exception:
            console.print("[red]Weather service unavailable.[/]")

    @staticmethod
    def net_ports():
        """Show listening ports with process names."""
        table = Table(title="Listening Ports")
        table.add_column("Protocol")
        table.add_column("Local Address")
        table.add_column("Port", justify="right")
        table.add_column("Status")
        table.add_column("PID", justify="right")
        table.add_column("Process Name")

        for conn in psutil.net_connections(kind='inet'):
            if conn.status == 'LISTEN':
                try:
                    proc = psutil.Process(conn.pid)
                    name = proc.name()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    name = "Unknown"
                
                table.add_row(
                    "TCP" if conn.type == socket.SOCK_STREAM else "UDP",
                    f"{conn.laddr.ip}",
                    str(conn.laddr.port),
                    conn.status,
                    str(conn.pid),
                    name
                )
        console.print(table)

    @staticmethod
    def net_kill_port(port: int):
        """Kill the process using a specific TCP port."""
        target_pids = set()
        for conn in psutil.net_connections(kind='tcp'):
            if conn.laddr.port == port and conn.pid:
                target_pids.add(conn.pid)
        
        if not target_pids:
            console.print(f"[yellow]No process found using port {port}.[/]")
            return

        for pid in target_pids:
            try:
                proc = psutil.Process(pid)
                name = proc.name()
                console.print(f"[warning]Killing process {name} (PID: {pid}) using port {port}...[/]")
                proc.terminate()
                console.print("[green]Process terminated.[/]")
            except Exception as e:
                console.print(f"[red]Failed to kill process {pid}: {e}[/]")

    @staticmethod
    def proc_top_mem(count: int = 10):
        """Show top memory-consuming processes."""
        procs = []
        for p in psutil.process_iter(['pid', 'name', 'memory_info']):
            try:
                info = p.info
                info['rss_mb'] = info['memory_info'].rss / (1024 * 1024)
                procs.append(info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        
        top_mem = sorted(procs, key=lambda x: x['rss_mb'], reverse=True)[:count]
        
        table = Table(title=f"Top {count} Processes (Memory)")
        table.add_column("PID", justify="right")
        table.add_column("Name")
        table.add_column("Memory (MB)", justify="right")
        
        for p in top_mem:
            table.add_row(str(p['pid']), p['name'], f"{p['rss_mb']:.2f}")
        console.print(table)

    @staticmethod
    def sys_which_all(command: str):
        """Show all executable paths for a command."""
        from cross_platform.package_manager import list_executable_paths
        paths = list_executable_paths(command)
        if paths:
            console.print(f"[bold cyan]Executable paths for '{command}':[/]")
            for p in paths:
                console.print(f"  - {p}")
        else:
            console.print(f"[red]Command '{command}' not found on PATH.[/]")

    @staticmethod
    def sys_inspect(proc_name: str):
        """See every property of a running process."""
        found = False
        for p in psutil.process_iter(['pid', 'name']):
            if proc_name.lower() in p.info['name'].lower():
                found = True
                try:
                    full_info = p.as_dict()
                    console.print(Panel(json.dumps(full_info, indent=2, default=str), title=f"Properties: {p.info['name']} (PID: {p.info['pid']})"))
                except Exception as e:
                    console.print(f"[red]Error inspecting {p.info['name']}: {e}[/]")
        if not found:
            console.print(f"[yellow]No process found matching '{proc_name}'.[/]")

    @staticmethod
    def sys_unblock(path: str):
        """Unblock downloaded files (Windows only)."""
        if not sysu.is_windows():
            console.print("[yellow]Unblock-File is only applicable on Windows.[/]")
            return
        
        cmd = f"powershell -NoProfile -Command \"Get-ChildItem -Path '{path}' -Recurse | Unblock-File\""
        console.print(f"Unblocking files in {path}...")
        out = sysu.run_command(cmd)
        console.print("[green]Done.[/]")

    @staticmethod
    def sys_find_cmd(pattern: str):
        """Find commands when you only remember part of the name."""
        if sysu.is_windows():
            cmd = f"powershell -NoProfile -Command \"Get-Command *{pattern}* | Select-Object Name, CommandType, Source | Format-Table -AutoSize\""
            out = sysu.run_command(cmd)
            console.print(Panel(out, title=f"Commands matching '*{pattern}*'"))
        else:
            out = sysu.run_command(f"compgen -c | grep '{pattern}'")
            console.print(f"[bold cyan]Matching commands:[/]\n{out}")

    @staticmethod
    def env_list(filter_pattern: Optional[str] = None):
        """List environment variables, optionally filtered."""
        table = Table(title="Environment Variables")
        table.add_column("Variable")
        table.add_column("Value", overflow="fold")
        
        for key, val in sorted(os.environ.items()):
            if filter_pattern and filter_pattern.lower() not in key.lower():
                continue
            table.add_row(key, val)
        console.print(table)

    @staticmethod
    def file_recent(directory: str = ".", count: int = 20):
        """Find the N most recently modified files."""
        root = Path(directory).resolve()
        files = []
        for p in root.rglob('*'):
            if p.is_file():
                try:
                    files.append((p, p.stat().st_mtime))
                except OSError: pass
        
        recent = sorted(files, key=lambda x: x[1], reverse=True)[:count]
        
        table = Table(title=f"Top {count} Recently Modified Files")
        table.add_column("Modified At")
        table.add_column("Path")
        
        for p, mtime in recent:
            table.add_row(datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S'), str(p))
        console.print(table)

    @staticmethod
    def file_largest(directory: str = ".", count: int = 25):
        """Find the largest files in a tree."""
        from cross_platform.size_utils import format_bytes_binary
        root = Path(directory).resolve()
        files = []
        for p in root.rglob('*'):
            if p.is_file():
                try:
                    files.append((p, p.stat().st_size))
                except OSError: pass
        
        largest = sorted(files, key=lambda x: x[1], reverse=True)[:count]
        
        table = Table(title=f"Top {count} Largest Files")
        table.add_column("Size", justify="right")
        table.add_column("Path")
        
        for p, size in largest:
            table.add_row(format_bytes_binary(size), str(p))
        console.print(table)

    @staticmethod
    def file_tail(filepath: str, lines: int = 100):
        """Tail a log file and keep following it."""
        console.print(f"[bold cyan]Tailing {filepath} (last {lines} lines)...[/]")
        try:
            # Use subprocess to tail if available (Linux/Mac/WSL)
            if not sysu.is_windows() or shutil.which("tail"):
                subprocess.run(["tail", "-n", str(lines), "-f", filepath])
            else:
                # Windows PowerShell fallback
                cmd = f"powershell -NoProfile -Command \"Get-Content '{filepath}' -Tail {lines} -Wait\""
                subprocess.run(cmd, shell=True)
        except KeyboardInterrupt:
            console.print("\n[yellow]Tail stopped.[/]")

    @staticmethod
    def file_grep(pattern: str, directory: str = "."):
        """Grep recursively with line numbers."""
        if shutil.which("rg"):
            subprocess.run(["rg", "-n", pattern, directory])
        elif shutil.which("grep"):
            subprocess.run(["grep", "-rn", pattern, directory])
        else:
            # PowerShell fallback
            cmd = f"powershell -NoProfile -Command \"Get-ChildItem -Path '{directory}' -Recurse -File | Select-String -Pattern '{pattern}'\""
            out = sysu.run_command(cmd)
            console.print(out)

    @staticmethod
    def file_find(pattern: str, directory: str = "."):
        """Find files by name pattern recursively."""
        if shutil.which("fd"):
            subprocess.run(["fd", pattern, directory])
        else:
            root = Path(directory).resolve()
            found = list(root.rglob(pattern))
            if found:
                for p in found:
                    console.print(str(p))
            else:
                console.print(f"[yellow]No files matching '{pattern}' found in {directory}.[/]")

    @staticmethod
    def file_size(directory: str = "."):
        """Measure total size of a folder tree."""
        from cross_platform.size_utils import format_bytes_binary
        root = Path(directory).resolve()
        total = 0
        count = 0
        for p in root.rglob('*'):
            if p.is_file():
                try:
                    total += p.stat().st_size
                    count += 1
                except OSError: pass
        
        console.print(f"[bold cyan]Folder:[/] {root}")
        console.print(f"[bold cyan]Total Size:[/] {format_bytes_binary(total)}")
        console.print(f"[bold cyan]File Count:[/] {count}")

    @staticmethod
    def file_hash(filepath: str):
        """Compute SHA256 for a file."""
        from file_utils.utils import calculate_file_hash
        try:
            h = calculate_file_hash(filepath)
            console.print(f"[bold cyan]SHA256 ({filepath}):[/] {h}")
        except Exception as e:
            console.print(f"[red]Error computing hash: {e}[/]")

    @staticmethod
    def file_dupes(directory: str = "."):
        """Find duplicate files by hash."""
        from file_utils import find_duplicates
        console.print(f"Scanning for duplicates in {directory} (by hash)...")
        dupes = find_duplicates(directory, use_hashes=True)
        if not dupes:
            console.print("[green]No duplicates found.[/]")
            return
        
        for orig, sub_list in dupes.items():
            console.print(f"[bold yellow]Original:[/] {orig}")
            for d in sub_list:
                console.print(f"  [red]Duplicate:[/] {d}")

    @staticmethod
    def file_pp_json(filepath: str):
        """Pretty-print a JSON file."""
        try:
            data = json.loads(Path(filepath).read_text(encoding='utf-8'))
            console.print(json.dumps(data, indent=2))
        except Exception as e:
            console.print(f"[red]Error parsing JSON: {e}[/]")

    @staticmethod
    def file_diff(file1: str, file2: str):
        """Compare two text files quickly."""
        import difflib
        try:
            lines1 = Path(file1).read_text(encoding='utf-8').splitlines()
            lines2 = Path(file2).read_text(encoding='utf-8').splitlines()
            diff = difflib.unified_diff(lines1, lines2, fromfile=file1, tofile=file2)
            for line in diff:
                if line.startswith('+'): console.print(f"[green]{line}[/]")
                elif line.startswith('-'): console.print(f"[red]{line}[/]")
                elif line.startswith('^'): console.print(f"[cyan]{line}[/]")
                else: console.print(line)
        except Exception as e:
            console.print(f"[red]Error comparing files: {e}[/]")

    @staticmethod
    def file_list_paths(directory: str = "."):
        """Copy a list of recursive file paths to the clipboard."""
        if not CLIPBOARD_AVAILABLE:
            console.print("[red]Clipboard utilities not available.[/]")
            return
        
        root = Path(directory).resolve()
        paths = [str(p) for p in root.rglob('*') if p.is_file()]
        text = "\n".join(paths)
        set_clipboard(text)
        console.print(f"[green]Copied {len(paths)} file paths to clipboard.[/]")

    @staticmethod
    def file_rename_preview(pattern: str, replacement: str, directory: str = "."):
        """Rename files with preview (regex)."""
        root = Path(directory).resolve()
        table = Table(title="Rename Preview")
        table.add_column("Original")
        table.add_column("New Name")
        
        for p in root.iterdir():
            if p.is_file():
                new_name = re.sub(pattern, replacement, p.name)
                if new_name != p.name:
                    table.add_row(p.name, f"[green]{new_name}[/]")
        
        console.print(table)
        console.print("[yellow]Use --yes to apply (not implemented in this preview command).[/]")

    @staticmethod
    def sys_members(command: str):
        """See what methods and properties an object actually has (Windows/PS focus)."""
        if sysu.is_windows():
            cmd = f"powershell -NoProfile -Command \"{command} | Get-Member | Format-Table -AutoSize\""
            out = sysu.run_command(cmd)
            console.print(Panel(out, title=f"Members of '{command}'"))
        else:
            # Python inspection equivalent for common modules if needed, or just informative
            console.print(f"[yellow]Get-Member is a PowerShell utility. For Python, try 'dir({command})' in a REPL.[/]")

    @staticmethod
    def file_dir_diff(dir1: str, dir2: str):
        """Compare two directories by relative file path."""
        d1 = Path(dir1).resolve()
        d2 = Path(dir2).resolve()
        
        files1 = {str(p.relative_to(d1)) for p in d1.rglob('*') if p.is_file()}
        files2 = {str(p.relative_to(d2)) for p in d2.rglob('*') if p.is_file()}
        
        only_in_1 = sorted(files1 - files2)
        only_in_2 = sorted(files2 - files1)
        in_both = sorted(files1 & files2)
        
        table = Table(title=f"Directory Comparison: {dir1} vs {dir2}")
        table.add_column("Status")
        table.add_column("Relative Path")
        
        for p in only_in_1: table.add_row("[red]Only in 1[/]", p)
        for p in only_in_2: table.add_row("[blue]Only in 2[/]", p)
        for p in in_both: table.add_row("[green]Present in both[/]", p)
        
        console.print(table)

    @staticmethod
    def file_size_gb(directory: str = "."):
        """Measure folder size in GB directly."""
        root = Path(directory).resolve()
        total = 0
        for p in root.rglob('*'):
            if p.is_file():
                try: total += p.stat().st_size
                except OSError: pass
        
        gb = total / (1024**3)
        console.print(f"[bold cyan]Folder:[/] {root}")
        console.print(f"[bold cyan]Total Size:[/] {gb:.2f} GB")

    @staticmethod
    def sys_table_width(width: int = 4096):
        """Prevent table truncation by setting a very wide output width (Windows/PS)."""
        if sysu.is_windows():
            console.print(f"[info]Setting PowerShell output width to {width}...[/]")
            # This is more of a tip command, as we can't easily change the current process's console buffer permanently from here
            console.print(f"Tip: Append '| Out-String -Width {width}' to your PS commands.")
        else:
            console.print(f"[info]Rich (Python) handles terminal width automatically (current: {console.width}).[/]")
