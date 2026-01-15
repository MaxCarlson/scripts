import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class OwnershipCandidate:
    manager: str
    confidence: float
    evidence: str
    package_id: Optional[str] = None
    upgrade_hint: Optional[str] = None


@dataclass(frozen=True)
class DetectionResult:
    command_name: str
    executable_path: Optional[str]
    candidates: List[OwnershipCandidate]
    recommended: Optional[OwnershipCandidate]


def _is_windows() -> bool:
    return os.name == "nt"


def _now_epoch() -> float:
    return time.time()


def _default_cache_dir() -> Path:
    if _is_windows():
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "cross_platform" / "install_ownership"
    return Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "cross_platform" / "install_ownership"


def _cache_path() -> Path:
    return _default_cache_dir() / "cache.json"


def _load_cache() -> Dict[str, Any]:
    p = _cache_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(cache: Dict[str, Any]) -> None:
    p = _cache_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cache, indent=2, sort_keys=True), encoding="utf-8")


def _run_cmd(argv: Sequence[str], timeout_s: float = 20.0) -> Tuple[int, str, str]:
    try:
        cp = subprocess.run(
            list(argv),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
        return cp.returncode, cp.stdout or "", cp.stderr or ""
    except FileNotFoundError:
        return 127, "", f"missing: {argv[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except Exception as e:
        return 1, "", f"error: {e}"


def _which(command_name: str) -> Optional[str]:
    p = shutil.which(command_name)
    if not p:
        return None
    try:
        return str(Path(p).resolve())
    except Exception:
        return p


def _path_heuristics(exe_path: Optional[str]) -> List[OwnershipCandidate]:
    if not exe_path:
        return []

    p = exe_path.lower().replace("/", "\\") if _is_windows() else exe_path.lower()
    cands: List[OwnershipCandidate] = []

    # Windows-focused strong hints.
    if _is_windows():
        if "\\scoop\\shims\\" in p:
            cands.append(OwnershipCandidate("scoop", 0.95, f"path contains scoop shims: {exe_path}"))
        if "\\chocolatey\\bin\\" in p or "\\programdata\\chocolatey\\" in p:
            cands.append(OwnershipCandidate("choco", 0.95, f"path contains chocolatey: {exe_path}"))
        if "\\.cargo\\bin\\" in p:
            cands.append(OwnershipCandidate("cargo", 0.90, f"path contains cargo bin: {exe_path}"))
        if "\\go\\bin\\" in p:
            cands.append(OwnershipCandidate("go", 0.75, f"path contains go bin: {exe_path}"))
        if "\\pipx\\" in p or "\\.local\\bin\\" in p:
            cands.append(OwnershipCandidate("pipx", 0.70, f"path suggests pipx/user bin: {exe_path}"))
        if "\\uv\\" in p:
            cands.append(OwnershipCandidate("uv", 0.60, f"path suggests uv-managed dir: {exe_path}"))
    else:
        if "/.cargo/bin/" in p:
            cands.append(OwnershipCandidate("cargo", 0.90, f"path contains cargo bin: {exe_path}"))
        if "/.local/bin/" in p:
            cands.append(OwnershipCandidate("pipx_or_user_bin", 0.50, f"path contains ~/.local/bin: {exe_path}"))
        if "/home/linuxbrew/" in p or "/opt/homebrew/" in p:
            cands.append(OwnershipCandidate("brew", 0.85, f"path contains homebrew: {exe_path}"))

    return cands


def _parse_winget_table(text: str) -> List[Dict[str, str]]:
    """
    winget list / winget upgrade output is typically a fixed-width table.
    We do a resilient parse using the header line and column start indices.
    """
    lines = [ln.rstrip("\r\n") for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        return []

    header_idx = None
    for i, ln in enumerate(lines[:10]):
        if "Name" in ln and "Id" in ln and "Version" in ln:
            header_idx = i
            break
    if header_idx is None or header_idx + 1 >= len(lines):
        return []

    header = lines[header_idx]
    # Identify column starts by finding sequences of 2+ spaces.
    # We'll locate the known headers.
    cols = ["Name", "Id", "Version"]
    starts: Dict[str, int] = {}
    for col in cols:
        m = re.search(rf"\b{re.escape(col)}\b", header)
        if m:
            starts[col] = m.start()

    if "Name" not in starts or "Id" not in starts:
        return []

    # Determine slice endpoints by sorting starts.
    ordered = sorted(starts.items(), key=lambda kv: kv[1])
    slices: List[Tuple[str, int, Optional[int]]] = []
    for idx, (col, start) in enumerate(ordered):
        end = ordered[idx + 1][1] if idx + 1 < len(ordered) else None
        slices.append((col, start, end))

    rows: List[Dict[str, str]] = []
    for ln in lines[header_idx + 2:]:
        if set(ln.strip()) == {"-"}:
            continue
        row: Dict[str, str] = {}
        for col, start, end in slices:
            cell = ln[start:end].strip() if end is not None else ln[start:].strip()
            row[col] = cell
        if row.get("Name") or row.get("Id"):
            rows.append(row)
    return rows


def _probe_winget(command_name: str) -> List[OwnershipCandidate]:
    if shutil.which("winget") is None:
        return []

    # Prefer winget upgrade first: it directly answers "can winget upgrade it?"
    rc_u, out_u, _ = _run_cmd(["winget", "upgrade", "--name", command_name], timeout_s=25.0)
    if rc_u == 0 and out_u.strip():
        rows = _parse_winget_table(out_u)
        cands: List[OwnershipCandidate] = []
        for r in rows[:5]:
            pkg_id = r.get("Id") or None
            name = r.get("Name") or command_name
            hint = f'winget upgrade --id "{pkg_id}"' if pkg_id else f'winget upgrade --name "{command_name}"'
            cands.append(
                OwnershipCandidate(
                    manager="winget",
                    confidence=0.70,
                    evidence=f"winget upgrade matches: {name} ({pkg_id or 'unknown id'})",
                    package_id=pkg_id,
                    upgrade_hint=hint,
                )
            )
        if cands:
            return cands

    # Fall back to winget list: "winget recognizes it as installed"
    rc_l, out_l, _ = _run_cmd(["winget", "list", "--name", command_name], timeout_s=25.0)
    if rc_l == 0 and out_l.strip():
        rows = _parse_winget_table(out_l)
        cands = []
        for r in rows[:5]:
            pkg_id = r.get("Id") or None
            name = r.get("Name") or command_name
            hint = f'winget upgrade --id "{pkg_id}"' if pkg_id else f'winget upgrade --name "{command_name}"'
            cands.append(
                OwnershipCandidate(
                    manager="winget",
                    confidence=0.45,
                    evidence=f"winget list matches: {name} ({pkg_id or 'unknown id'})",
                    package_id=pkg_id,
                    upgrade_hint=hint,
                )
            )
        return cands

    return []


def _probe_pipx(command_name: str) -> List[OwnershipCandidate]:
    if shutil.which("pipx") is None:
        return []

    rc, out, _ = _run_cmd(["pipx", "list", "--json"], timeout_s=25.0)
    if rc != 0 or not out.strip():
        return []

    try:
        data = json.loads(out)
    except Exception:
        return []

    venvs = data.get("venvs", {}) if isinstance(data, dict) else {}
    matches: List[OwnershipCandidate] = []
    for pkg_name, pkg_info in venvs.items():
        apps = pkg_info.get("apps", []) if isinstance(pkg_info, dict) else []
        for app in apps:
            if str(app).strip().lower() == command_name.lower():
                hint = f"pipx upgrade {pkg_name}"
                matches.append(
                    OwnershipCandidate(
                        manager="pipx",
                        confidence=0.95,
                        evidence=f"pipx reports app '{command_name}' from package '{pkg_name}'",
                        package_id=pkg_name,
                        upgrade_hint=hint,
                    )
                )
    return matches


def _probe_uv(command_name: str) -> List[OwnershipCandidate]:
    if shutil.which("uv") is None:
        return []

    # uv tool list output is text; we match the tool name as the first token.
    rc, out, _ = _run_cmd(["uv", "tool", "list"], timeout_s=25.0)
    if rc != 0 or not out.strip():
        return []

    matches: List[OwnershipCandidate] = []
    for ln in out.splitlines():
        s = ln.strip()
        if not s or s.lower().startswith("installed"):
            continue
        tool = s.split()[0]
        if tool.lower() == command_name.lower():
            matches.append(
                OwnershipCandidate(
                    manager="uv",
                    confidence=0.85,
                    evidence=f"uv tool list contains '{command_name}'",
                    package_id=tool,
                    upgrade_hint=f"uv tool upgrade {tool}",
                )
            )
    return matches


def detect_ownership(
    command_name: str,
    executable_path: Optional[str] = None,
    cache_ttl_seconds: int = 300,
    no_cache: bool = False,
) -> DetectionResult:
    exe = executable_path or _which(command_name)

    cache_key = f"{command_name}::{exe or ''}"
    cache = _load_cache() if not no_cache else {}
    if not no_cache:
        cached = cache.get(cache_key)
        if isinstance(cached, dict):
            ts = float(cached.get("ts", 0))
            if _now_epoch() - ts <= float(cache_ttl_seconds):
                candidates = [
                    OwnershipCandidate(**c) for c in cached.get("candidates", []) if isinstance(c, dict)
                ]
                rec = cached.get("recommended")
                recommended = OwnershipCandidate(**rec) if isinstance(rec, dict) else None
                return DetectionResult(command_name=command_name, executable_path=exe, candidates=candidates, recommended=recommended)

    candidates: List[OwnershipCandidate] = []
    candidates.extend(_path_heuristics(exe))
    candidates.extend(_probe_pipx(command_name))
    candidates.extend(_probe_uv(command_name))
    candidates.extend(_probe_winget(command_name))

    # Deduplicate by (manager, package_id, evidence)
    seen = set()
    unique: List[OwnershipCandidate] = []
    for c in candidates:
        key = (c.manager, c.package_id or "", c.evidence)
        if key not in seen:
            seen.add(key)
            unique.append(c)

    unique_sorted = sorted(unique, key=lambda c: c.confidence, reverse=True)
    recommended = unique_sorted[0] if unique_sorted else None

    if not no_cache:
        cache[cache_key] = {
            "ts": _now_epoch(),
            "candidates": [asdict(c) for c in unique_sorted],
            "recommended": asdict(recommended) if recommended else None,
        }
        _save_cache(cache)

    return DetectionResult(command_name=command_name, executable_path=exe, candidates=unique_sorted, recommended=recommended)


def _prompt_yes_no(question: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    while True:
        resp = input(f"{question} [y/n]: ").strip().lower()
        if resp in ("y", "yes"):
            return True
        if resp in ("n", "no"):
            return False


def guard_install(
    command_name: str,
    install_method: str,
    assume_yes: bool,
    cache_ttl_seconds: int,
    no_cache: bool,
) -> int:
    res = detect_ownership(
        command_name=command_name,
        cache_ttl_seconds=cache_ttl_seconds,
        no_cache=no_cache,
    )

    if not res.executable_path:
        return 0  # not installed; safe

    # If we have a high-confidence owner and we're attempting a different method (especially "manual"), block/prompt.
    blockers = [c for c in res.candidates if c.confidence >= 0.80]
    if not blockers:
        return 0

    # If install_method matches one of the strong candidates, allow.
    if any(b.manager.lower() == install_method.lower() for b in blockers):
        return 0

    strongest = blockers[0]
    msg = (
        f"\nBLOCK: '{command_name}' already exists at:\n"
        f"  {res.executable_path}\n\n"
        f"Likely managed by: {strongest.manager} (confidence {strongest.confidence:.2f})\n"
        f"Evidence: {strongest.evidence}\n"
    )
    if strongest.upgrade_hint:
        msg += f"\nRecommended upgrade path:\n  {strongest.upgrade_hint}\n"
    msg += f"\nYou are trying to install via: {install_method}\n"

    sys.stderr.write(msg)

    ok = _prompt_yes_no("Proceed anyway (may shadow/conflict)?", assume_yes=assume_yes)
    return 0 if ok else 2


def _print_result(res: DetectionResult, json_output: bool) -> None:
    if json_output:
        payload = {
            "command_name": res.command_name,
            "executable_path": res.executable_path,
            "candidates": [asdict(c) for c in res.candidates],
            "recommended": asdict(res.recommended) if res.recommended else None,
        }
        print(json.dumps(payload, indent=2))
        return

    print(f"Command: {res.command_name}")
    print(f"Path: {res.executable_path or 'NOT FOUND'}")
    if not res.candidates:
        print("Candidates: (none)")
        return
    print("Candidates:")
    for c in res.candidates:
        extra = []
        if c.package_id:
            extra.append(f"id={c.package_id}")
        if c.upgrade_hint:
            extra.append(f"upgrade={c.upgrade_hint}")
        suffix = f" ({', '.join(extra)})" if extra else ""
        print(f"  - {c.manager:8s} conf={c.confidence:.2f} :: {c.evidence}{suffix}")
    if res.recommended:
        print(f"\nRecommended: {res.recommended.manager} :: {res.recommended.upgrade_hint or '(no hint)'}")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="install-ownership",
        description="Detect how a CLI tool is likely managed (winget/pipx/uv + path heuristics) and guard against shadow installs.",
    )
    sub = p.add_subparsers(dest="subcmd", required=False)

    detect = sub.add_parser("detect", help="Detect ownership for a command.")
    detect.add_argument("-c", "--command_name", required=True, help="Command name to detect (e.g. ripgrep, ruff).")
    detect.add_argument("-p", "--executable_path", default=None, help="Optional explicit path to the executable.")
    detect.add_argument("-j", "--json_output", action="store_true", help="Emit JSON.")
    detect.add_argument("-n", "--no_cache", action="store_true", help="Disable cache.")
    detect.add_argument("-t", "--cache_ttl_seconds", type=int, default=300, help="Cache TTL seconds.")

    guard = sub.add_parser("guard", help="Guard an install attempt (warn/block on shadow installs).")
    guard.add_argument("-c", "--command_name", required=True, help="Command name you are about to install.")
    guard.add_argument(
        "-m",
        "--install_method",
        required=True,
        choices=["manual", "winget", "pipx", "uv", "choco", "scoop", "cargo", "go"],
        help="The method you are about to use.",
    )
    guard.add_argument("-y", "--assume_yes", action="store_true", help="Auto-approve prompts.")
    guard.add_argument("-n", "--no_cache", action="store_true", help="Disable cache.")
    guard.add_argument("-t", "--cache_ttl_seconds", type=int, default=300, help="Cache TTL seconds.")

    p.set_defaults(subcmd="detect")
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)

    if args.subcmd == "guard":
        return guard_install(
            command_name=args.command_name,
            install_method=args.install_method,
            assume_yes=bool(args.assume_yes),
            cache_ttl_seconds=int(args.cache_ttl_seconds),
            no_cache=bool(args.no_cache),
        )

    res = detect_ownership(
        command_name=args.command_name,
        executable_path=getattr(args, "executable_path", None),
        cache_ttl_seconds=int(getattr(args, "cache_ttl_seconds", 300)),
        no_cache=bool(getattr(args, "no_cache", False)),
    )
    _print_result(res, json_output=bool(getattr(args, "json_output", False)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
