#!/usr/bin/env python3
"""
System Manager CLI

A comprehensive CLI for system management, leveraging cross_platform.
"""

import argparse
import sys
from typing import Sequence

from .manager import SystemManager

def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sm",
        description="System Manager - Cross-platform system utilities and information."
    )
    subparsers = parser.add_subparsers(dest="category", title="categories", help="Command category")

    # --- Identity Category ---
    id_parser = subparsers.add_parser("id", help="Identity and elevation info")
    id_sub = id_parser.add_subparsers(dest="cmd", required=True)
    id_sub.add_parser("whoami", help="Show current user and elevation status")
    id_sub.add_parser("sys-id", help="Show unique system machine ID")

    # --- Network Category ---
    net_parser = subparsers.add_parser("net", help="Network utilities")
    net_sub = net_parser.add_subparsers(dest="cmd", required=True)
    net_sub.add_parser("public-ip", help="Fetch public IP address")
    net_sub.add_parser("local-ip", help="List local IP addresses")
    ps = net_sub.add_parser("port-scan", help="Scan local ports")
    ps.add_argument("-s", "--start", type=int, default=1, help="Start port")
    ps.add_argument("-e", "--end", type=int, default=1024, help="End port")
    net_sub.add_parser("dns-check", help="Test DNS resolution").add_argument("domain", help="Domain to check")
    net_sub.add_parser("internet", help="Check internet latency")
    net_sub.add_parser("weather", help="Quick weather summary")
    net_sub.add_parser("ports", help="Show listening ports with process names")
    kp = net_sub.add_parser("kill-port", help="Kill process using a TCP port")
    kp.add_argument("port", type=int, help="Port number")

    # --- Process Category ---
    proc_parser = subparsers.add_parser("proc", help="Process management")
    proc_sub = proc_parser.add_subparsers(dest="cmd", required=True)
    top = proc_sub.add_parser("top", help="Top processes by CPU (alias for top-cpu)")
    top.add_argument("-n", "--count", type=int, default=5, help="Number of processes")
    tcpu = proc_sub.add_parser("top-cpu", help="Top processes by CPU")
    tcpu.add_argument("-n", "--count", type=int, default=10, help="Number of processes")
    tmem = proc_sub.add_parser("top-mem", help="Top processes by memory")
    tmem.add_argument("-n", "--count", type=int, default=10, help="Number of processes")
    proc_sub.add_parser("list", help="List all processes (cross_platform wrapper)")

    # --- System Info Category ---
    sys_parser = subparsers.add_parser("sys", help="System information")
    sys_sub = sys_parser.add_subparsers(dest="cmd", required=True)
    sys_sub.add_parser("uptime", help="System uptime and boot time")
    sys_sub.add_parser("battery", help="Battery status")
    sys_sub.add_parser("timezone", help="Current timezone and time")
    sys_sub.add_parser("cpu", help="CPU details")
    sys_sub.add_parser("mem", help="Memory usage")
    sys_sub.add_parser("disk", help="Disk partitions and usage")
    sys_sub.add_parser("os", help="Detailed OS/Kernel info")
    sys_sub.add_parser("hw-serial", help="Hardware serial number")
    sys_sub.add_parser("usb", help="List USB devices")
    sys_sub.add_parser("services", help="List active system services")
    sys_sub.add_parser("pkgs", help="Package manager statistics")
    wa = sys_sub.add_parser("which-all", help="Show all executable paths for a command")
    wa.add_argument("command", help="Command name")
    ins = sys_sub.add_parser("inspect", help="See every property of a running process")
    ins.add_argument("proc_name", help="Process name to match")
    unb = sys_sub.add_parser("unblock", help="Unblock downloaded files (Windows only)")
    unb.add_argument("path", help="Directory path to unblock")
    fc = sys_sub.add_parser("find-cmd", help="Find commands by part of name")
    fc.add_argument("pattern", help="Search pattern")
    memb = sys_sub.add_parser("members", help="See methods and properties of an object (PS focus)")
    memb.add_argument("command", help="Object or command to inspect")
    tw = sys_sub.add_parser("table-width", help="Prevent table truncation (Windows focus)")
    tw.add_argument("-w", "--width", type=int, default=4096, help="Width in characters")

    # --- Environment Category ---
    env_parser = subparsers.add_parser("env", help="Environment utilities")
    env_sub = env_parser.add_subparsers(dest="cmd", required=True)
    eg = env_sub.add_parser("get", help="Get and expand environment variable")
    eg.add_argument("variable", help="Variable name")
    ls = env_sub.add_parser("list", help="List all environment variables")
    ls.add_argument("-f", "--filter", help="Filter variables by name")
    env_sub.add_parser("path-clean", help="Analyze system PATH for missing entries")
    env_sub.add_parser("shell", help="Show current shell and history info")

    # --- File Category ---
    file_parser = subparsers.add_parser("file", help="File and directory utilities")
    file_sub = file_parser.add_subparsers(dest="cmd", required=True)
    
    rec = file_sub.add_parser("recent", help="Find recently modified files")
    rec.add_argument("directory", nargs="?", default=".", help="Directory to scan")
    rec.add_argument("-n", "--count", type=int, default=20, help="Number of files")
    
    lar = file_sub.add_parser("largest", help="Find largest files")
    lar.add_argument("directory", nargs="?", default=".", help="Directory to scan")
    lar.add_argument("-n", "--count", type=int, default=25, help="Number of files")
    
    tail = file_sub.add_parser("tail", help="Tail a log file and follow")
    tail.add_argument("filepath", help="Path to file")
    tail.add_argument("-n", "--lines", type=int, default=100, help="Number of lines")
    
    grep = file_sub.add_parser("grep", help="Recursive search for pattern")
    grep.add_argument("pattern", help="Regex pattern")
    grep.add_argument("directory", nargs="?", default=".", help="Directory to scan")
    
    find = file_sub.add_parser("find", help="Find files by name pattern")
    find.add_argument("pattern", help="Name pattern (glob)")
    find.add_argument("directory", nargs="?", default=".", help="Directory to scan")
    
    sz = file_sub.add_parser("size", help="Total size of folder tree")
    sz.add_argument("directory", nargs="?", default=".", help="Directory to measure")
    
    szgb = file_sub.add_parser("size-gb", help="Folder size in GB directly")
    szgb.add_argument("directory", nargs="?", default=".", help="Directory to measure")
    
    hsh = file_sub.add_parser("hash", help="Compute SHA256 for a file")
    hsh.add_argument("filepath", help="Path to file")
    
    dup = file_sub.add_parser("dupes", help="Find duplicate files by hash")
    dup.add_argument("directory", nargs="?", default=".", help="Directory to scan")
    
    ppj = file_sub.add_parser("pp-json", help="Pretty-print JSON file")
    ppj.add_argument("filepath", help="Path to JSON file")
    
    df = file_sub.add_parser("diff", help="Compare two text files")
    df.add_argument("file1", help="First file")
    df.add_argument("file2", help="Second file")
    
    ddiff = file_sub.add_parser("dir-diff", help="Compare two directories by relative paths")
    ddiff.add_argument("dir1", help="First directory")
    ddiff.add_argument("dir2", help="Second directory")
    
    lp = file_sub.add_parser("list-paths", help="Copy list of file paths to clipboard")
    lp.add_argument("directory", nargs="?", default=".", help="Directory to scan")
    
    ren = file_sub.add_parser("rename-preview", help="Bulk rename preview (regex)")
    ren.add_argument("pattern", help="Regex match pattern")
    ren.add_argument("replacement", help="Replacement pattern")
    ren.add_argument("directory", nargs="?", default=".", help="Directory to scan")

    # --- Time Category ---
    time_parser = subparsers.add_parser("time", help="Time utilities")
    time_sub = time_parser.add_subparsers(dest="cmd", required=True)
    time_sub.add_parser("sync", help="Check time drift against Google")

    args = parser.parse_args(argv)

    mgr = SystemManager()

    # Identity
    if args.category == "id":
        if args.cmd == "whoami": mgr.whoami()
        elif args.cmd == "sys-id": mgr.sys_id()
    
    # Network
    elif args.category == "net":
        if args.cmd == "public-ip": mgr.public_ip()
        elif args.cmd == "local-ip": mgr.local_ip()
        elif args.cmd == "port-scan": mgr.port_scan(args.start, args.end)
        elif args.cmd == "dns-check": mgr.dns_check(args.domain)
        elif args.cmd == "internet": mgr.internet_test()
        elif args.cmd == "weather": mgr.weather()
        elif args.cmd == "ports": mgr.net_ports()
        elif args.cmd == "kill-port": mgr.net_kill_port(args.port)

    # Process
    elif args.category == "proc":
        if args.cmd in ("top", "top-cpu"): mgr.process_top(args.count)
        elif args.cmd == "top-mem": mgr.proc_top_mem(args.count)
        elif args.cmd == "list":
            from cross_platform import ProcessManager
            print(ProcessManager().list_processes())

    # System
    elif args.category == "sys":
        if args.cmd == "uptime": mgr.uptime()
        elif args.cmd == "battery": mgr.battery()
        elif args.cmd == "timezone": mgr.timezone()
        elif args.cmd == "cpu": mgr.cpu_info()
        elif args.cmd == "mem": mgr.mem_info()
        elif args.cmd == "disk": mgr.disk_list()
        elif args.cmd == "os": mgr.os_detail()
        elif args.cmd == "hw-serial": mgr.hw_serial()
        elif args.cmd == "usb": mgr.usb_list()
        elif args.cmd == "services": mgr.service_list()
        elif args.cmd == "pkgs": mgr.pkg_stats()
        elif args.cmd == "which-all": mgr.sys_which_all(args.command)
        elif args.cmd == "inspect": mgr.sys_inspect(args.proc_name)
        elif args.cmd == "unblock": mgr.sys_unblock(args.path)
        elif args.cmd == "find-cmd": mgr.sys_find_cmd(args.pattern)
        elif args.cmd == "members": mgr.sys_members(args.command)
        elif args.cmd == "table-width": mgr.sys_table_width(args.width)

    # Environment
    elif args.category == "env":
        if args.cmd == "get": mgr.env_get(args.variable)
        elif args.cmd == "list": mgr.env_list(args.filter)
        elif args.cmd == "path-clean": mgr.path_clean()
        elif args.cmd == "shell": mgr.shell_info()

    # File
    elif args.category == "file":
        if args.cmd == "recent": mgr.file_recent(args.directory, args.count)
        elif args.cmd == "largest": mgr.file_largest(args.directory, args.count)
        elif args.cmd == "tail": mgr.file_tail(args.filepath, args.lines)
        elif args.cmd == "grep": mgr.file_grep(args.pattern, args.directory)
        elif args.cmd == "find": mgr.file_find(args.pattern, args.directory)
        elif args.cmd == "size": mgr.file_size(args.directory)
        elif args.cmd == "size-gb": mgr.file_size_gb(args.directory)
        elif args.cmd == "hash": mgr.file_hash(args.filepath)
        elif args.cmd == "dupes": mgr.file_dupes(args.directory)
        elif args.cmd == "pp-json": mgr.file_pp_json(args.filepath)
        elif args.cmd == "diff": mgr.file_diff(args.file1, args.file2)
        elif args.cmd == "dir-diff": mgr.file_dir_diff(args.dir1, args.dir2)
        elif args.cmd == "list-paths": mgr.file_list_paths(args.directory)
        elif args.cmd == "rename-preview": mgr.file_rename_preview(args.pattern, args.replacement, args.directory)

    # Time
    elif args.category == "time":
        if args.cmd == "sync": mgr.time_sync()

    else:
        parser.print_help()

    return 0

if __name__ == "__main__":
    sys.exit(main())
