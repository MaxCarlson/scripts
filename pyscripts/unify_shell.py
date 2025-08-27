# File: scripts/pyscripts/unify_shell.py
#!/usr/bin/env python3
"""
Unified shell alias/function framework.

- Single source of truth: YAML files (or a directory of YAMLs) under ~/dotfiles/unified/
- Generate shell shims for Zsh and PowerShell
- Run portable Python implementations when provided

CLI:
  dot run <name> [args...]           Execute an alias/function by name
  dot generate --yaml <file|dir>     Emit Zsh/Pwsh shims
            --zsh <out.zsh> --pwsh <out.ps1>
  dot list [filter]                  List available entries (merged from YAML), optionally filter by substring
"""

from __future__ import annotations
import argparse
import dataclasses
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

try:
    import yaml  # PyYAML
except Exception as e:
    print("ERROR: PyYAML is required: pip install pyyaml", file=sys.stderr)
    sys.exit(1)


# ---------- Models ----------

@dataclasses.dataclass
class Entry:
    name: str
    desc: str = ""
    posix: Optional[str] = None        # shell string for bash/zsh
    powershell: Optional[str] = None   # shell string for pwsh
    python_impl: Optional[str] = None  # name of python function implemented below
    requires: List[str] = dataclasses.field(default_factory=list)
    category: str = "misc"


# ---------- Helpers ----------

def _is_windows() -> bool:
    return platform.system().lower().startswith("win")

def _have(cmd: str) -> bool:
    # On Windows, honor .exe/.ps1 in PATH as well
    return shutil.which(cmd) is not None

def _all_requirements_present(reqs: List[str]) -> bool:
    for r in reqs:
        if not _have(r):
            return False
    return True

def load_aliases(yaml_path: Path) -> List[Entry]:
    """
    Load alias/function entries from a single YAML file OR from all YAMLs in a directory.

    Accepted shapes:
      - File path: a single YAML list of entries
      - Directory: merges all *.yml and *.yaml (sorted by filename)
    """
    p = Path(yaml_path)
    if not p.exists():
        raise FileNotFoundError(f"Aliases YAML path not found: {p}")

    # Collect raw lists from one file or many
    raw_items: List[dict] = []
    if p.is_dir():
        files = sorted(list(p.glob("*.yml")) + list(p.glob("*.yaml")))
        for f in files:
            content = yaml.safe_load(f.read_text(encoding="utf-8")) or []
            if isinstance(content, list):
                raw_items.extend(content)
    else:
        content = yaml.safe_load(p.read_text(encoding="utf-8")) or []
        if isinstance(content, list):
            raw_items.extend(content)

    # Normalize into Entry objects
    entries: List[Entry] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        name = raw.get("name")
        if not name or not isinstance(name, str):
            continue
        entries.append(
            Entry(
                name=name.strip(),
                desc=(raw.get("desc") or "") if isinstance(raw.get("desc"), str) else "",
                posix=raw.get("posix") if isinstance(raw.get("posix"), str) else None,
                powershell=raw.get("powershell") if isinstance(raw.get("powershell"), str) else None,
                python_impl=raw.get("python_impl") if isinstance(raw.get("python_impl"), str) else None,
                requires=list(raw.get("requires") or []),
                category=raw.get("category", "misc") if isinstance(raw.get("category"), str) else "misc",
            )
        )

    # Enforce uniqueness
    seen: set[str] = set()
    dups = []
    for e in entries:
        if e.name in seen:
            dups.append(e.name)
        else:
            seen.add(e.name)
    if dups:
        raise ValueError(f"Duplicate alias names across loaded YAMLs: {sorted(set(dups))}")

    return entries


# ---------- Python implementations (portable logic) ----------

def py_mkcd(argv: List[str]) -> int:
    """
    mkcd <dir> [base_dir]
    """
    if not argv:
        print("Usage: mkcd <dir> [base_dir]", file=sys.stderr)
        return 2
    name = argv[0]
    base = Path(argv[1]) if len(argv) > 1 else Path.cwd()
    target = (base / name).resolve()
    target.mkdir(parents=True, exist_ok=True)
    # Change directory only for subshell; print the path for the shell shim to cd.
    print(str(target))
    return 0

def py_rgmax(argv: List[str]) -> int:
    """
    rgmax "search phrase" [num=1] [path=.]
    Uses ripgrep if present; otherwise, a slow pure-Python fallback.
    """
    if not argv:
        print('Usage: rgmax "search phrase" [num] [path]', file=sys.stderr)
        return 2
    phrase = argv[0]
    try:
        num = int(argv[1]) if len(argv) > 1 else 1
    except ValueError:
        print("num must be an integer", file=sys.stderr)
        return 2
    root = Path(argv[2]) if len(argv) > 2 else Path(".")
    if _have("rg"):
        cmd = ["rg", "-c", "--fixed-strings", "--", phrase, str(root)]
        res = subprocess.run(cmd, text=True, capture_output=True)
        print(res.stdout, end="")
        return res.returncode if res.returncode in (0, 1) else 1
    # Fallback (very limited, text files only)
    counts: List[Tuple[int, Path]] = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        try:
            text = p.read_text(errors="ignore")
        except Exception:
            continue
        c = text.count(phrase)
        if c:
            counts.append((c, p))
    counts.sort(key=lambda t: t[0], reverse=True)
    for c, p in counts[:num]:
        print(f"{p}:{c}")
    return 0

def _walk_limited(root: Path, max_depth: int) -> List[Tuple[int, Path]]:
    """Pure-Python limited-depth directory walk for lt fallback."""
    items: List[Tuple[int, Path]] = []
    root = root.resolve()
    def rel_depth(p: Path) -> int:
        try:
            return len(p.relative_to(root).parts)
        except Exception:
            return 0
    for p in root.rglob("*"):
        d = rel_depth(p)
        if d <= max_depth:
            items.append((d, p))
    items.sort(key=lambda t: (t[0], str(t[1])))
    return items

def py_lt(argv: List[str]) -> int:
    """
    lt [depth] [path]
    Prefers eza, then tree, then a Python fallback.
    """
    depth = 2
    start = Path(".")
    if argv:
        try:
            depth = int(argv[0])
            if depth < 1:
                raise ValueError
            if len(argv) > 1:
                start = Path(argv[1])
        except ValueError:
            depth = 2
            start = Path(argv[0])
            if len(argv) > 1:
                try:
                    depth = int(argv[1])
                    if depth < 1:
                        depth = 2
                except ValueError:
                    pass

    start = start.resolve()
    if not start.exists():
        print(f"lt: path not found: {start}", file=sys.stderr)
        return 2

    if _have("eza"):
        cmd = ["eza", "--tree", f"--level={depth}", "--group-directories-first", "--icons", str(start)]
        return subprocess.call(cmd)
    if _have("tree"):
        cmd = ["tree", "-L", str(depth), str(start)]
        return subprocess.call(cmd)

    # Python fallback
    indent_unit = "  "
    print(start)
    items = _walk_limited(start, depth)
    for d, p in items:
        if p == start:
            continue
        rel = p.relative_to(start)
        print(f"{indent_unit * d}{rel}")
    return 0

def py_list(argv: List[str], entries: List[Entry]) -> int:
    """
    list [filter]
    Print available names + descriptions. If filter is provided, only show matching rows.
    """
    flt = (argv[0].lower() if argv else "").strip()
    rows = []
    for e in entries:
        if not _all_requirements_present(e.requires):
            continue
        if flt and (flt not in e.name.lower()) and (flt not in (e.desc or "").lower()):
            continue
        rows.append((e.name, e.desc))
    rows.sort(key=lambda t: t[0].lower())
    width = max((len(n) for n, _ in rows), default=0)
    for n, d in rows:
        pad = " " * (width - len(n))
        print(f"{n}{pad}  —  {d}")
    return 0

PY_FUNCS = {
    "mkcd": py_mkcd,
    "rgmax": py_rgmax,
    "lt": py_lt,
    # 'list' is handled specially (needs entries); expose via CLI and optional alias below.
}


# ---------- Execution ----------

def run_entry(entry: Entry, argv: List[str], all_entries: Optional[List[Entry]] = None) -> int:
    # Python implementation takes precedence if present
    if entry.python_impl:
        if entry.python_impl == "list":
            # Needs the full catalog
            return py_list(argv, all_entries or [])
        func = PY_FUNCS.get(entry.python_impl)
        if not func:
            print(
                f"ERROR: python_impl '{entry.python_impl}' not found for {entry.name}",
                file=sys.stderr,
            )
            return 1
        rc = func(argv)
        return rc

    # Otherwise, dispatch to per-platform string command
    if _is_windows():
        cmd = entry.powershell or entry.posix
        shell = True  # let pwsh resolve its syntax when invoked from pwsh shim
    else:
        cmd = entry.posix or entry.powershell
        shell = True
    if not cmd:
        print(f"ERROR: no command for this platform: {entry.name}", file=sys.stderr)
        return 1

    # Join args carefully; simplest approach is to append quoted args.
    arg_str = " ".join(subprocess.list2cmdline([a]) for a in argv)
    full = f"{cmd} {arg_str}".strip()
    return subprocess.call(full, shell=shell)


# ---------- Codegen ----------

ZSH_HEADER = """# AUTOGENERATED — DO NOT EDIT
# Source this from your zsh init.
# Generated by unify_shell.py
"""

PWSH_HEADER = """# AUTOGENERATED — DO NOT EDIT
# Dot-source this in your profile.
# Generated by unify_shell.py
"""

def generate_zsh(entries: List[Entry]) -> str:
    lines = [ZSH_HEADER]
    lines.append('command -v dot >/dev/null 2>&1 || alias dot="unify_shell.py"')
    for e in entries:
        if not _all_requirements_present(e.requires):
            continue
        if e.python_impl == "mkcd":
            lines.append(
                f"""
# {e.desc}
function {e.name}() {{
  local target
  target=$(dot run {e.name} "$@") || return $?
  [[ -n "$target" ]] && builtin cd -- "$target"
}}
"""
            )
        elif e.python_impl:
            lines.append(
                f"""
# {e.desc}
function {e.name}() {{
  dot run {e.name} "$@"
}}
"""
            )
        else:
            lines.append(f"alias {e.name}='dot run {e.name}'  # {e.desc}")
    return "\n".join(lines).strip() + "\n"

def generate_pwsh(entries: List[Entry]) -> str:
    lines = [PWSH_HEADER]
    lines.append(
        "$dot = (Get-Command dot -ErrorAction SilentlyContinue); if (-not $dot) { function dot { unify_shell.py @args } }"
    )
    for e in entries:
        if not _all_requirements_present(e.requires):
            continue
        if e.python_impl == "mkcd":
            lines.append(
                f"""
# {e.desc}
function {e.name} {{
  $target = dot run {e.name} @args
  if ($LASTEXITCODE -eq 0 -and $target) {{ Set-Location -LiteralPath $target }}
}}
Export-ModuleMember -Function {e.name} 2>$null | Out-Null
"""
            )
        elif e.python_impl:
            lines.append(
                f"""
# {e.desc}
function {e.name} {{
  dot run {e.name} @args
}}
Set-Alias -Name {e.name} -Value {e.name} -Force 2>$null | Out-Null
"""
            )
        else:
            lines.append(
                f"""
function {e.name} {{ dot run {e.name} @args }}
Set-Alias -Name {e.name} -Value {e.name} -Force 2>$null | Out-Null
"""
            )
    return "\n".join(lines).strip() + "\n"


# ---------- CLI ----------

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="dot", description="Unified shell aliases/functions"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="Run an alias/function")
    p_run.add_argument("name")
    p_run.add_argument("argv", nargs=argparse.REMAINDER)

    p_gen = sub.add_parser("generate", help="Generate shell files")
    p_gen.add_argument(
        "--yaml", type=Path, default=Path.home() / "dotfiles/unified"
    )
    p_gen.add_argument("--zsh", type=Path, help="Write zsh aliases to this file")
    p_gen.add_argument(
        "--pwsh", type=Path, help="Write PowerShell aliases to this file"
    )

    p_list = sub.add_parser("list", help="List available entries (optionally filter)")
    p_list.add_argument("filter", nargs="?", default=None)

    args = parser.parse_args()

    # Load once for all subcommands
    yaml_path = getattr(args, "yaml", Path.home() / "dotfiles/unified")
    entries = load_aliases(yaml_path)

    if args.cmd == "run":
        name = args.name
        match = {e.name: e for e in entries}.get(name)
        if not match:
            print(f"Unknown alias/function: {name}", file=sys.stderr)
            return 1
        if not _all_requirements_present(match.requires):
            print(
                f"Missing required tools for '{name}': {match.requires}",
                file=sys.stderr,
            )
            return 127
        return run_entry(match, args.argv, entries)

    if args.cmd == "generate":
        if args.zsh:
            args.zsh.parent.mkdir(parents=True, exist_ok=True)
            args.zsh.write_text(generate_zsh(entries), encoding="utf-8")
            print(f"[OK] Wrote zsh file: {args.zsh}")
        if args.pwsh:
            args.pwsh.parent.mkdir(parents=True, exist_ok=True)
            args.pwsh.write_text(generate_pwsh(entries), encoding="utf-8")
            print(f"[OK] Wrote PowerShell file: {args.pwsh}")
        return 0

    if args.cmd == "list":
        filt = args.filter
        return py_list([filt] if filt else [], entries)

    return 0


if __name__ == "__main__":
    sys.exit(main())
