#!/usr/bin/env python3
"""
CLI entry point for System Manager.
"""

import argparse
import sys
import json
import yaml
from typing import List, Optional, Any

from .manager import SystemManager
from .ui import show_list

mgr = SystemManager()


def _subparser_choices(parser: argparse.ArgumentParser):
    """Return argparse subparser choices for a parser, if present."""
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action.choices
    return {}


def _print_unique_subcommand_help(argv: List[str], category_parsers: dict) -> bool:
    """Print help for a unique one-token nested command such as ``sm sid``."""
    if len(argv) != 1 or argv[0].startswith("-") or argv[0] in category_parsers:
        return False

    matches = []
    for category_parser in category_parsers.values():
        subcommands = _subparser_choices(category_parser)
        if argv[0] in subcommands:
            matches.append(subcommands[argv[0]])

    if len(matches) != 1:
        return False

    matches[0].print_help()
    return True


def output_result(data: Any, format: str = "table", title: str = "System Manager", sort_field: Optional[str] = None, copy: bool = False):
    """Handle command output formatting and optional clipboard copying."""
    
    # Optional clipboard copy
    if copy:
        try:
            from cross_platform.clipboard_utils import set_clipboard
            set_clipboard(str(data))
            print("[SUCCESS] Result copied to clipboard.")
        except Exception as e:
            print(f"[ERROR] Failed to copy to clipboard: {e}")

    if format == "json":
        print(json.dumps(data, indent=2, default=str))
    elif format == "yaml":
        print(yaml.dump(data, default_flow_style=False))
    elif format == "plain":
        if isinstance(data, list):
            for item in data: print(item)
        else:
            print(data)
    else: # Default: table (TUI if list)
        if isinstance(data, list) and data and isinstance(data[0], dict):
            show_list(data, title=title, sort_field=sort_field)
        elif isinstance(data, dict):
            # Print simple vertical table for single dict
            from rich.table import Table
            from rich.console import Console
            table = Table(title=title)
            table.add_column("Property")
            table.add_column("Value")
            for k, v in data.items():
                table.add_row(str(k), str(v))
            Console().print(table)
        else:
            print(data)

def main(argv: Optional[List[str]] = None):
    argv = list(argv) if argv is not None else sys.argv[1:]

    # Common parser for all commands
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-f", "--format", choices=["table", "json", "yaml", "plain"], default="table", help="Output format")
    common.add_argument("-c", "--copy", action="store_true", help="Copy result to clipboard")
    common.add_argument("-t", "--top", type=int, help="Limit number of results")
    common.add_argument("-s", "--sort", help="Sort by field name")
    common.add_argument("-r", "--reverse", action="store_true", help="Reverse sort order")

    parser = argparse.ArgumentParser(prog="sm", description="Cross-platform System Manager CLI")
    subparsers = parser.add_subparsers(dest="category", help="Command category")
    category_parsers = {}

    # ID category
    id_parser = subparsers.add_parser("id", help="Identity information")
    category_parsers["id"] = id_parser
    id_sub = id_parser.add_subparsers(dest="cmd")
    id_sub.add_parser("whoami", parents=[common], help="Show current user and elevation status")
    id_sub.add_parser("hostname", parents=[common], help="Show hostname and FQDN")
    id_sub.add_parser("groups", parents=[common], help="Show user group memberships")
    id_sub.add_parser("admin-check", parents=[common], help="Check if shell is elevated")
    id_sub.add_parser("sid", parents=[common], help="Show user SID/UID")
    id_sub.add_parser("sessions", parents=[common], help="Show active sessions")

    # NET category
    net_parser = subparsers.add_parser("net", help="Network utilities")
    category_parsers["net"] = net_parser
    net_sub = net_parser.add_subparsers(dest="cmd")
    net_sub.add_parser("public-ip", parents=[common], help="Show public IP address")
    net_sub.add_parser("local-ip", parents=[common], help="Show local IP addresses")
    ping = net_sub.add_parser("ping", parents=[common], help="Ping a host")
    ping.add_argument("host", help="Host to ping")
    ping.add_argument("-n", "--count", type=int, default=4, help="Number of requests")
    
    trace = net_sub.add_parser("trace", parents=[common], help="Trace route to a host")
    trace.add_argument("host", help="Host to trace")
    
    resolve = net_sub.add_parser("resolve", parents=[common], help="Resolve hostname")
    resolve.add_argument("domain", help="Domain to resolve")

    rdns = net_sub.add_parser("reverse-dns", parents=[common], help="Reverse DNS lookup")
    rdns.add_argument("ip", help="IP address")
    
    head = net_sub.add_parser("http-head", parents=[common], help="Fetch HTTP headers")
    head.add_argument("url", help="URL to fetch")
    
    net_sub.add_parser("interfaces", parents=[common], help="List network interfaces")
    net_sub.add_parser("gateway", parents=[common], help="Show default gateway")
    net_sub.add_parser("wifi", parents=[common], help="Show WiFi details")
    net_sub.add_parser("ports", parents=[common], help="Show listening ports")
    net_sub.add_parser("arp", parents=[common], help="Show ARP cache")
    
    kport = net_sub.add_parser("kill-port", parents=[common], help="Kill process using a port")
    kport.add_argument("port", type=int, help="Port number")

    krange = net_sub.add_parser("kill-port-range", parents=[common], help="Kill processes in port range")
    krange.add_argument("start", type=int, help="Start port")
    krange.add_argument("end", type=int, help="End port")
    krange.add_argument("-A", "--apply", action="store_true", help="Execute termination")

    # PROC category
    proc_parser = subparsers.add_parser("proc", help="Process management")
    category_parsers["proc"] = proc_parser
    proc_sub = proc_parser.add_subparsers(dest="cmd")
    top_cpu = proc_sub.add_parser("top-cpu", parents=[common], help="Show top processes by CPU")
    top_cpu.add_argument("-n", "--count", type=int, default=10, help="Number of processes")
    
    top_mem = proc_sub.add_parser("top-mem", parents=[common], help="Show top processes by Memory")
    top_mem.add_argument("-n", "--count", type=int, default=10, help="Number of processes")
    
    tree = proc_sub.add_parser("tree", parents=[common], help="Show process tree")
    tree.add_argument("-p", "--pid", type=int, help="Root PID")
    
    def add_proc_match_args(proc_cmd):
        proc_cmd.add_argument("-p", "--pid", type=int, help="Process ID")
        proc_cmd.add_argument("-q", "--query", help="Search query")
        proc_cmd.add_argument("-N", "--name", help="Process name search")
        proc_cmd.add_argument("-C", "--cmdline", action="store_true", help="Search command line")
        proc_cmd.add_argument("-E", "--exe", action="store_true", help="Search executable path")
        proc_cmd.add_argument("-P", "--path", help="Filter by executable path or working directory")
        proc_cmd.add_argument("-x", "--regex", action="store_true", help="Use regular expression matching")
        proc_cmd.add_argument("-z", "--fuzzy", action="store_true", help="Use fuzzy matching")

    find_p = proc_sub.add_parser("find", parents=[common], help="Find processes")
    find_p.add_argument("pattern", nargs="?", help="Search pattern")
    add_proc_match_args(find_p)
    find_p.add_argument("-M", "--cim", action="store_true", help="Use Windows CIM command-line search")
    
    kill_p = proc_sub.add_parser("kill", parents=[common], help="Kill processes")
    kill_p.add_argument("name", nargs="?", help="PID or Name")
    add_proc_match_args(kill_p)
    kill_p.add_argument("-F", "--force", action="store_true", help="Force kill")
    kill_p.add_argument("-n", "--dry-run", action="store_true", default=True, help="Preview action without changes")
    kill_p.add_argument("-y", "--confirm", action="store_true", help="Confirm destructive action")

    parents_p = proc_sub.add_parser("parents", parents=[common], help="Show parent chain")
    parents_p.add_argument("-p", "--pid", required=True, type=int, help="Process ID")

    children_p = proc_sub.add_parser("children", parents=[common], help="Show child processes")
    children_p.add_argument("-p", "--pid", required=True, type=int, help="Process ID")
    children_p.add_argument("-R", "--recursive", action="store_true", help="Recurse through descendants")

    for action_name in ["pause", "resume", "stop", "stop-tree", "restart", "restart-tree"]:
        action_p = proc_sub.add_parser(action_name, parents=[common], help=f"{action_name} matched processes")
        add_proc_match_args(action_p)
        action_p.add_argument("-F", "--force", action="store_true", help="Use force where supported")
        action_p.add_argument("-n", "--dry-run", action="store_true", default=False, help="Preview action without changes")
        action_p.add_argument("-y", "--confirm", action="store_true", help="Confirm destructive action")

    stats_p = proc_sub.add_parser("stats", parents=[common], help="Sample process resource usage")
    stats_p.add_argument("-p", "--pid", required=True, type=int, help="Process ID")
    stats_p.add_argument("-i", "--interval", type=float, default=1.0, help="Seconds between samples")
    stats_p.add_argument("-S", "--samples", type=int, default=1, help="Number of samples")

    stats_tree_p = proc_sub.add_parser("stats-tree", parents=[common], help="Sample process tree resource usage")
    stats_tree_p.add_argument("-p", "--pid", required=True, type=int, help="Process ID")
    stats_tree_p.add_argument("-i", "--interval", type=float, default=1.0, help="Seconds between samples")
    stats_tree_p.add_argument("-S", "--samples", type=int, default=1, help="Number of samples")

    cmdl = proc_sub.add_parser("cmdline", parents=[common], help="Show process command line")
    cmdl.add_argument("pid", type=int, help="PID")

    thrd = proc_sub.add_parser("threads", parents=[common], help="Show process threads")
    thrd.add_argument("pid", type=int, help="PID")

    hndl = proc_sub.add_parser("handles", parents=[common], help="Show process handles/fds")
    hndl.add_argument("pid", type=int, help="PID")

    proc_sub.add_parser("full-list", parents=[common], help="Detailed process list")

    help_search_p = subparsers.add_parser("help-search", help="Search sm command metadata")
    help_search_p.add_argument("-q", "--query", required=True, help="Search query")
    help_search_p.add_argument("-x", "--regex", action="store_true", help="Use regular expression matching")
    help_search_p.add_argument("-z", "--fuzzy", action="store_true", help="Use fuzzy matching")
    help_search_p.add_argument("-f", "--format", choices=["table", "json", "yaml", "plain"], default="table", help="Output format")
    help_search_p.add_argument("-c", "--copy", action="store_true", help="Copy result to clipboard")

    # SYS category
    sys_parser = subparsers.add_parser("sys", help="System information")
    category_parsers["sys"] = sys_parser
    sys_sub = sys_parser.add_subparsers(dest="cmd")
    sys_sub.add_parser("uptime", parents=[common], help="Show system uptime")
    sys_sub.add_parser("cpu", parents=[common], help="Show CPU information")
    sys_sub.add_parser("mem", parents=[common], help="Show memory usage")
    sys_sub.add_parser("disk", parents=[common], help="Show disk partitions")
    sys_sub.add_parser("id", parents=[common], help="Show system unique ID")
    sys_sub.add_parser("os", parents=[common], help="Show detailed OS info")
    sys_sub.add_parser("gpu", parents=[common], help="Show GPU information")
    sys_sub.add_parser("bios", parents=[common], help="Show BIOS information")
    sys_sub.add_parser("motherboard", parents=[common], help="Show motherboard info")
    sys_sub.add_parser("reboot-required", parents=[common], help="Check if reboot is pending")
    sys_sub.add_parser("services", parents=[common], help="List active services")
    sys_sub.add_parser("console-size", parents=[common], help="Show console dimensions")
    sys_sub.add_parser("monitor", parents=[common], help="Machine dashboard summary")
    sys_sub.add_parser("locale", parents=[common], help="Show locale info")
    sys_sub.add_parser("clipboard", parents=[common], help="Show clipboard metadata")
    sys_sub.add_parser("screen", parents=[common], help="Show display info")
    sys_sub.add_parser("recent-errors", parents=[common], help="Show recent system errors (Windows)")
    
    twidth = sys_sub.add_parser("table-width", parents=[common], help="Get/Set table width tip")
    twidth.add_argument("-w", "--width", type=int, help="Target width")
    
    inspect = sys_sub.add_parser("inspect", parents=[common], help="Inspect a process in detail")
    inspect.add_argument("name", help="Process name part")
    
    find_cmd = sys_sub.add_parser("find-cmd", parents=[common], help="Search for commands")
    find_cmd.add_argument("pattern", help="Search pattern")

    cmd_srch = sys_sub.add_parser("cmd-search", parents=[common], help="Fuzzy command search (Windows)")
    cmd_srch.add_argument("pattern", help="Search pattern")

    # ENV category
    env_parser = subparsers.add_parser("env", help="Environment management")
    category_parsers["env"] = env_parser
    env_sub = env_parser.add_subparsers(dest="cmd")
    elist = env_sub.add_parser("list", parents=[common], help="List environment variables")
    elist.add_argument("-p", "--pattern", help="Filter pattern")
    
    eget = env_sub.add_parser("get", parents=[common], help="Get env variable value")
    eget.add_argument("variable", help="Variable name")
    
    env_sub.add_parser("path-user", parents=[common], help="List user path entries")
    env_sub.add_parser("path-machine", parents=[common], help="List machine path entries")
    
    pver = env_sub.add_parser("path-verify", parents=[common], help="Check if folder is on path")
    pver.add_argument("directory", help="Directory path")

    # PKG category
    pkg_parser = subparsers.add_parser("pkg", help="Package management")
    category_parsers["pkg"] = pkg_parser
    pkg_sub = pkg_parser.add_subparsers(dest="cmd")
    plist = pkg_sub.add_parser("list", parents=[common], help="List installed packages")
    plist.add_argument("-m", "--manager", help="Specific manager (pip, winget, apt)")
    pkg_sub.add_parser("outdated", parents=[common], help="Check for outdated packages (pip)")
    psearch = pkg_sub.add_parser("search", parents=[common], help="Search for packages")
    psearch.add_argument("query", help="Search query")
    pwhich = pkg_sub.add_parser("which-manager", parents=[common], help="Detect manager for command")
    pwhich.add_argument("command", help="Command name")

    # DISK category
    disk_parser = subparsers.add_parser("disk", help="Disk utilities")
    category_parsers["disk"] = disk_parser
    disk_sub = disk_parser.add_subparsers(dest="cmd")
    dusage = disk_sub.add_parser("usage", parents=[common], help="Show disk usage")
    dusage.add_argument("path", nargs="?", default="/", help="Path to check")
    disk_sub.add_parser("free", parents=[common], help="Show free space on all drives")
    disk_sub.add_parser("mounts", parents=[common], help="List mounted filesystems")

    # SERVICE category
    svc_parser = subparsers.add_parser("service", help="Service management")
    category_parsers["service"] = svc_parser
    svc_sub = svc_parser.add_subparsers(dest="cmd")
    svc_sub.add_parser("list", parents=[common], help="List active services")
    sstat = svc_sub.add_parser("status", parents=[common], help="Get service status")
    sstat.add_argument("name", help="Service name")
    sstart = svc_sub.add_parser("start", parents=[common], help="Start a service")
    sstart.add_argument("name", help="Service name")
    sstop = svc_sub.add_parser("stop", parents=[common], help="Stop a service")
    sstop.add_argument("name", help="Service name")

    # DOCKER category
    dock_parser = subparsers.add_parser("docker", help="Docker utilities")
    category_parsers["docker"] = dock_parser
    dock_sub = dock_parser.add_subparsers(dest="cmd")
    dock_sub.add_parser("ps", parents=[common], help="List running containers")
    dock_sub.add_parser("images", parents=[common], help="List docker images")

    # GIT category
    git_parser = subparsers.add_parser("git", help="Git utilities")
    category_parsers["git"] = git_parser
    git_sub = git_parser.add_subparsers(dest="cmd")
    git_sub.add_parser("status-short", parents=[common], help="Short git status")
    git_sub.add_parser("branch-info", parents=[common], help="Current branch info")
    git_sub.add_parser("root", parents=[common], help="Find git root")

    # TEXT category
    text_parser = subparsers.add_parser("text", help="Text utilities")
    category_parsers["text"] = text_parser
    text_sub = text_parser.add_subparsers(dest="cmd")
    tenc = text_sub.add_parser("base64-encode", parents=[common], help="Base64 encode")
    tenc.add_argument("text", help="Text to encode")
    tdec = text_sub.add_parser("base64-decode", parents=[common], help="Base64 decode")
    tdec.add_argument("text", help="Text to decode")
    tsha = text_sub.add_parser("sha256", parents=[common], help="SHA256 hash string")
    tsha.add_argument("text", help="Text to hash")

    # CRYPTO category
    crypto_parser = subparsers.add_parser("crypto", help="Crypto utilities")
    category_parsers["crypto"] = crypto_parser
    crypto_sub = crypto_parser.add_subparsers(dest="cmd")
    crand = crypto_sub.add_parser("rand", parents=[common], help="Generate random string")
    crand.add_argument("-l", "--length", type=int, default=32, help="Length")

    # FILE category
    file_parser = subparsers.add_parser("file", help="File utilities")
    category_parsers["file"] = file_parser
    file_sub = file_parser.add_subparsers(dest="cmd")
    
    frecent = file_sub.add_parser("recent", parents=[common], help="Show recent files")
    frecent.add_argument("directory", nargs="?", default=".", help="Root directory")
    frecent.add_argument("-n", "--count", type=int, default=20, help="Number of files")
    frecent.add_argument("-R", "--recursive", action="store_true", help="Recursive search")
    
    flargest = file_sub.add_parser("largest", parents=[common], help="Show largest files")
    flargest.add_argument("directory", nargs="?", default=".", help="Root directory")
    flargest.add_argument("-n", "--count", type=int, default=25, help="Number of files")
    flargest.add_argument("-R", "--recursive", action="store_true", help="Recursive search")
    
    fgrep = file_sub.add_parser("grep", parents=[common], help="Grep files")
    fgrep.add_argument("pattern", help="Search pattern")
    fgrep.add_argument("directory", nargs="?", default=".", help="Root directory")
    fgrep.add_argument("-R", "--recursive", action="store_true", help="Recursive search")
    
    fsize = file_sub.add_parser("size", parents=[common], help="Measure folder size")
    fsize.add_argument("directory", nargs="?", default=".", help="Directory")
    fsize.add_argument("-S", "--shallow", action="store_false", dest="recursive", help="Shallow scan only")
    fsize.set_defaults(recursive=True)

    # Iterative File Ops
    rext = file_sub.add_parser("rename-ext", parents=[common], help="Rename file extensions")
    rext.add_argument("old_ext", help="Old extension")
    rext.add_argument("new_ext", help="New extension")
    rext.add_argument("directory", nargs="?", default=".", help="Directory")
    rext.add_argument("-R", "--recursive", action="store_true", help="Recursive")
    rext.add_argument("-A", "--apply", action="store_true", help="Execute rename")

    aprefix = file_sub.add_parser("add-prefix", parents=[common], help="Add prefix to filenames")
    aprefix.add_argument("prefix", help="Prefix string")
    aprefix.add_argument("directory", nargs="?", default=".", help="Directory")
    aprefix.add_argument("-R", "--recursive", action="store_true", help="Recursive")
    aprefix.add_argument("-A", "--apply", action="store_true", help="Execute rename")

    adate = file_sub.add_parser("add-date-suffix", parents=[common], help="Add date suffix to filenames")
    adate.add_argument("directory", nargs="?", default=".", help="Directory")
    adate.add_argument("-R", "--recursive", action="store_true", help="Recursive")
    adate.add_argument("-A", "--apply", action="store_true", help="Execute rename")

    elower = file_sub.add_parser("ext-lower", parents=[common], help="Lowercase file extensions")
    elower.add_argument("directory", nargs="?", default=".", help="Directory")
    elower.add_argument("-R", "--recursive", action="store_true", help="Recursive")
    elower.add_argument("-A", "--apply", action="store_true", help="Execute rename")

    sund = file_sub.add_parser("spaces-to-underscores", parents=[common], help="Replace spaces with underscores")
    sund.add_argument("directory", nargs="?", default=".", help="Directory")
    sund.add_argument("-R", "--recursive", action="store_true", help="Recursive")
    sund.add_argument("-A", "--apply", action="store_true", help="Execute rename")

    rempty = file_sub.add_parser("remove-empty-dirs", parents=[common], help="Remove empty directories")
    rempty.add_argument("directory", nargs="?", default=".", help="Directory")
    rempty.add_argument("-A", "--apply", action="store_true", help="Execute removal")

    dold = file_sub.add_parser("delete-old", parents=[common], help="Delete old files")
    dold.add_argument("-d", "--days", type=int, default=30, help="Days threshold")
    dold.add_argument("directory", nargs="?", default=".", help="Directory")
    dold.add_argument("-R", "--recursive", action="store_true", help="Recursive")
    dold.add_argument("-A", "--apply", action="store_true", help="Execute deletion")

    fdupes = file_sub.add_parser("dupes-detailed", parents=[common], help="Find duplicates with details")
    fdupes.add_argument("directory", nargs="?", default=".", help="Directory")
    fdupes.add_argument("-R", "--recursive", action="store_true", help="Recursive")

    dsizes = file_sub.add_parser("dir-sizes", parents=[common], help="Show top-level directory sizes")
    dsizes.add_argument("directory", nargs="?", default=".", help="Directory")

    lpaths = file_sub.add_parser("long-paths", parents=[common], help="Find longest file paths")
    lpaths.add_argument("directory", nargs="?", default=".", help="Directory")
    lpaths.add_argument("-n", "--count", type=int, default=50, help="Number of files")
    lpaths.add_argument("-R", "--recursive", action="store_true", help="Recursive")

    efiles = file_sub.add_parser("empty-files", parents=[common], help="List empty files")
    efiles.add_argument("directory", nargs="?", default=".", help="Directory")
    efiles.add_argument("-R", "--recursive", action="store_true", help="Recursive")

    # PERM category
    perm_parser = subparsers.add_parser("perm", help="Permissions and ACL management")
    category_parsers["perm"] = perm_parser
    perm_sub = perm_parser.add_subparsers(dest="cmd")
    
    pshow = perm_sub.add_parser("show", parents=[common], help="Show full ACL details")
    pshow.add_argument("path", help="File or folder path")
    
    pentries = perm_sub.add_parser("entries", parents=[common], help="Show individual ACL entries")
    pentries.add_argument("path", help="File or folder path")
    
    picacls = perm_sub.add_parser("icacls", parents=[common], help="Show native icacls output")
    picacls.add_argument("path", help="File or folder path")
    
    pcomp = perm_sub.add_parser("compare", parents=[common], help="Compare ACLs between two paths")
    pcomp.add_argument("path1", help="First path")
    pcomp.add_argument("path2", help="Second path")
    
    pchain = perm_sub.add_parser("parent-chain", parents=[common], help="Show ACLs for path and parents")
    pchain.add_argument("path", help="File or folder path")
    
    pdeny = perm_sub.add_parser("scan-deny", parents=[common], help="Scan tree for explicit Deny rules")
    pdeny.add_argument("directory", help="Root directory")
    
    pprot = perm_sub.add_parser("scan-protected", parents=[common], help="Scan tree for disabled inheritance")
    pprot.add_argument("directory", help="Root directory")
    
    ptread = perm_sub.add_parser("test-read", parents=[common], help="Test read access recursively")
    ptread.add_argument("directory", help="Root directory")
    
    ptwrite = perm_sub.add_parser("test-write", parents=[common], help="Test write access recursively")
    ptwrite.add_argument("directory", help="Root directory")
    
    powner = perm_sub.add_parser("owner", parents=[common], help="Show owner information")
    powner.add_argument("path", help="File or folder path")
    powner.add_argument("-R", "--recursive", action="store_true", help="Recursive scan")
    
    ptake = perm_sub.add_parser("takeown", parents=[common], help="Take ownership")
    ptake.add_argument("path", help="File or folder path")
    ptake.add_argument("-R", "--recursive", action="store_true", help="Recursive")
    ptake.add_argument("-A", "--apply", action="store_true", help="Apply changes")
    
    penable = perm_sub.add_parser("enable-inheritance", parents=[common], help="Enable ACL inheritance")
    penable.add_argument("path", help="File or folder path")
    penable.add_argument("-R", "--recursive", action="store_true", help="Recursive")
    penable.add_argument("-A", "--apply", action="store_true", help="Apply changes")
    
    preset = perm_sub.add_parser("reset", parents=[common], help="Reset ACLs to inherited defaults")
    preset.add_argument("path", help="File or folder path")
    preset.add_argument("-R", "--recursive", action="store_true", help="Recursive")
    preset.add_argument("-A", "--apply", action="store_true", help="Apply changes")
    
    pgrant = perm_sub.add_parser("grant", parents=[common], help="Grant explicit access")
    pgrant.add_argument("path", help="File or folder path")
    pgrant.add_argument("-u", "--user", required=True, help="User or group name")
    pgrant.add_argument("-g", "--rights", choices=["read", "modify", "full"], default="read", help="Access rights")
    pgrant.add_argument("-R", "--recursive", action="store_true", help="Recursive")
    pgrant.add_argument("-A", "--apply", action="store_true", help="Apply changes")
    
    pnorm = perm_sub.add_parser("normalize", parents=[common], help="Standardized ACL repair/normalization")
    pnorm.add_argument("path", help="File or folder path")
    pnorm.add_argument("-u", "--user", help="Optional user to grant rights to")
    pnorm.add_argument("-g", "--rights", choices=["read", "modify", "full"], default="read", help="Rights for optional user")
    pnorm.add_argument("-A", "--apply", action="store_true", help="Apply changes")

    if _print_unique_subcommand_help(argv, category_parsers):
        return 0

    args = parser.parse_args(argv)

    if not args.category:
        parser.print_help()
        return 0
    if args.category in category_parsers and getattr(args, "cmd", None) is None:
        category_parsers[args.category].print_help()
        return 0

    # Dispatch
    data = None
    title = f"{args.category.upper()} {getattr(args, 'cmd', '')}"
    
    try:
        if args.category == "id":
            if args.cmd == "whoami": data = mgr.whoami()
            elif args.cmd == "hostname": data = mgr.id_hostname()
            elif args.cmd == "groups": data = mgr.id_groups()
            elif args.cmd == "admin-check": data = mgr.id_admin_check()
            elif args.cmd == "sid": data = mgr.id_sid()
            elif args.cmd == "sessions": data = mgr.id_sessions()
            
        elif args.category == "net":
            if args.cmd == "public-ip": data = mgr.public_ip()
            elif args.cmd == "local-ip": data = mgr.local_ip()
            elif args.cmd == "ping": data = mgr.net_ping(args.host, args.count)
            elif args.cmd == "trace": data = mgr.net_trace(args.host)
            elif args.cmd == "resolve": data = mgr.net_resolve(args.domain)
            elif args.cmd == "reverse-dns": data = mgr.net_reverse_dns(args.ip)
            elif args.cmd == "http-head": data = mgr.net_http_head(args.url)
            elif args.cmd == "interfaces": data = mgr.net_interfaces()
            elif args.cmd == "gateway": data = mgr.net_gateway()
            elif args.cmd == "wifi": data = mgr.net_wifi()
            elif args.cmd == "ports": data = mgr.net_ports()
            elif args.cmd == "arp": data = mgr.net_arp()
            elif args.cmd == "kill-port": data = mgr.net_kill_port(args.port)
            elif args.cmd == "kill-port-range": data = mgr.net_kill_port_range(args.start, args.end, args.apply)
            
        elif args.category == "proc":
            if args.cmd == "top-cpu": data = mgr.process_top(args.count or 10, "cpu")
            elif args.cmd == "top-mem": data = mgr.process_top(args.count or 10, "mem")
            elif args.cmd == "tree": data = mgr.proc_tree(args.pid)
            elif args.cmd == "find":
                data = mgr.proc_find_detailed(
                    pid=args.pid,
                    query=args.query or args.pattern,
                    name=args.name,
                    cmdline=args.cmdline,
                    exe=args.exe,
                    path=args.path,
                    regex=args.regex,
                    fuzzy=args.fuzzy,
                    cim=args.cim,
                )
            elif args.cmd == "parents": data = mgr.proc_parents(args.pid)
            elif args.cmd == "children": data = mgr.proc_children(args.pid, args.recursive)
            elif args.cmd in ["pause", "resume", "stop", "stop-tree", "restart", "restart-tree"]:
                action = args.cmd.replace("-tree", "")
                data = mgr.proc_action(
                    action,
                    pid=args.pid,
                    query=args.query,
                    name=args.name,
                    cmdline=args.cmdline,
                    exe=args.exe,
                    path=args.path,
                    regex=args.regex,
                    fuzzy=args.fuzzy,
                    recursive=args.cmd.endswith("-tree"),
                    force=args.force,
                    dry_run=args.dry_run,
                    confirm=args.confirm,
                )
            elif args.cmd == "kill":
                target_pid = args.pid
                target_query = args.query
                target_name = args.name
                if args.name and args.name.isdigit() and not args.query and not args.pid:
                    target_pid = int(args.name)
                    target_name = None
                elif args.name and not args.query and not args.name:
                    target_query = args.name
                data = mgr.proc_action(
                    "kill",
                    pid=target_pid,
                    query=target_query,
                    name=target_name,
                    cmdline=args.cmdline,
                    exe=args.exe,
                    path=args.path,
                    regex=args.regex,
                    fuzzy=args.fuzzy,
                    force=True,
                    dry_run=args.dry_run,
                    confirm=args.confirm,
                )
            elif args.cmd == "cmdline": data = mgr.proc_cmdline(args.pid)
            elif args.cmd == "threads": data = mgr.proc_threads(args.pid)
            elif args.cmd == "handles": data = mgr.proc_handles(args.pid)
            elif args.cmd == "full-list": data = mgr.proc_full_list()
            elif args.cmd == "stats": data = mgr.proc_stats(args.pid, args.interval, args.samples, include_tree=False)
            elif args.cmd == "stats-tree": data = mgr.proc_stats(args.pid, args.interval, args.samples, include_tree=True)

        elif args.category == "help-search":
            data = mgr.help_search(args.query, args.regex, args.fuzzy)
            
        elif args.category == "sys":
            if args.cmd == "uptime": data = mgr.uptime()
            elif args.cmd == "cpu": data = mgr.cpu_info()
            elif args.cmd == "mem": data = mgr.mem_info()
            elif args.cmd == "disk": data = mgr.disk_list()
            elif args.cmd == "id": data = mgr.sys_id()
            elif args.cmd == "os": data = mgr.os_detail()
            elif args.cmd == "gpu": data = mgr.sys_gpu()
            elif args.cmd == "bios": data = mgr.sys_bios()
            elif args.cmd == "motherboard": data = mgr.sys_motherboard()
            elif args.cmd == "reboot-required": data = mgr.sys_reboot_required()
            elif args.cmd == "services": data = mgr.service_list()
            elif args.cmd == "console-size": data = mgr.sys_console_size()
            elif args.cmd == "table-width": data = mgr.sys_table_width(args.width)
            elif args.cmd == "inspect": data = mgr.sys_inspect(args.name)
            elif args.cmd == "find-cmd": data = mgr.sys_find_cmd(args.pattern)
            elif args.cmd == "cmd-search": data = mgr.sys_cmd_search(args.pattern)
            elif args.cmd == "monitor": data = mgr.sys_monitor()
            elif args.cmd == "locale": data = mgr.sys_locale()
            elif args.cmd == "clipboard": data = mgr.sys_clipboard()
            elif args.cmd == "recent-errors": data = mgr.sys_recent_errors()
            elif args.cmd == "screen": data = mgr.sys_screen()
            
        elif args.category == "env":
            if args.cmd == "list": data = mgr.env_list(args.pattern)
            elif args.cmd == "get": data = mgr.env_get(args.variable)
            elif args.cmd == "path-user": data = mgr.env_path_user()
            elif args.cmd == "path-machine": data = mgr.env_path_machine()
            elif args.cmd == "path-verify": data = mgr.env_path_verify(args.directory)
            
        elif args.category == "pkg":
            if args.cmd == "list": data = mgr.pkg_list(args.manager)
            elif args.cmd == "outdated": data = mgr.pkg_outdated()
            elif args.cmd == "search": data = mgr.pkg_search(args.query)
            elif args.cmd == "which-manager": data = mgr.pkg_which_manager(args.command)
            
        elif args.category == "service":
            if args.cmd == "list": data = mgr.service_list()
            elif args.cmd == "status": data = mgr.service_status(args.name)
            elif args.cmd == "start": data = mgr.service_start(args.name)
            elif args.cmd == "stop": data = mgr.service_stop(args.name)

        elif args.category == "docker":
            if args.cmd == "ps": data = mgr.docker_ps()
            elif args.cmd == "images": data = mgr.docker_images()

        elif args.category == "git":
            if args.cmd == "status-short": data = mgr.git_status_short()
            elif args.cmd == "branch-info": data = mgr.git_branch_info()
            elif args.cmd == "root": data = mgr.git_root()

        elif args.category == "text":
            if args.cmd == "base64-encode": data = mgr.text_base64_encode(args.text)
            elif args.cmd == "base64-decode": data = mgr.text_base64_decode(args.text)
            elif args.cmd == "sha256": data = mgr.text_sha256(args.text)

        elif args.category == "crypto":
            if args.cmd == "rand": data = mgr.crypto_rand(args.length)

        elif args.category == "disk":
            if args.cmd == "usage": data = mgr.disk_usage(args.path)
            elif args.cmd == "free": data = mgr.disk_free()
            elif args.cmd == "mounts": data = mgr.disk_mounts()

        elif args.category == "file":
            if args.cmd == "recent": data = mgr.file_recent(args.directory, args.count, args.recursive)
            elif args.cmd == "largest": data = mgr.file_largest(args.directory, args.count, args.recursive)
            elif args.cmd == "grep": data = mgr.file_grep(args.pattern, args.directory, args.recursive)
            elif args.cmd == "size": data = mgr.file_size(args.directory, args.recursive)
            elif args.cmd == "rename-ext": data = mgr.file_rename_ext(args.old_ext, args.new_ext, args.directory, args.recursive, args.apply)
            elif args.cmd == "add-prefix": data = mgr.file_add_prefix(args.prefix, args.directory, args.recursive, args.apply)
            elif args.cmd == "add-date-suffix": data = mgr.file_add_date_suffix(args.directory, args.recursive, args.apply)
            elif args.cmd == "ext-lower": data = mgr.file_ext_lower(args.directory, args.recursive, args.apply)
            elif args.cmd == "spaces-to-underscores": data = mgr.file_spaces_to_underscores(args.directory, args.recursive, args.apply)
            elif args.cmd == "remove-empty-dirs": data = mgr.file_remove_empty_dirs(args.directory, args.apply)
            elif args.cmd == "delete-old": data = mgr.file_delete_old(args.days, args.directory, args.recursive, args.apply)
            elif args.cmd == "dupes-detailed": data = mgr.file_dupes_detailed(args.directory, args.recursive)
            elif args.cmd == "dir-sizes": data = mgr.file_dir_sizes(args.directory)
            elif args.cmd == "long-paths": data = mgr.file_long_paths(args.directory, args.count, args.recursive)
            elif args.cmd == "empty-files": data = mgr.file_empty_files(args.directory, args.recursive)

        if data is not None:
            # Apply --top filter if requested and data is a list
            if getattr(args, "top", None) and isinstance(data, list):
                data = data[:args.top]
            output_result(
                data,
                format=args.format,
                title=title,
                sort_field=getattr(args, "sort", None),
                copy=getattr(args, "copy", False),
            )
            
    except Exception as e:
        print(f"[ERROR] Command execution failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0

if __name__ == "__main__":
    sys.exit(main())
