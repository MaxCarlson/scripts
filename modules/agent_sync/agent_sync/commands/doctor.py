"""agent-sync doctor — verify hooks, DB, worktrees, provider installations."""
import json
import shutil
from pathlib import Path

from agent_sync.db.connection import get_connection


def _check(label: str, ok: bool, detail: str = "") -> bool:
    icon = "✓" if ok else "✗"
    print(f"  {icon}  {label}" + (f": {detail}" if detail else ""))
    return ok


def cmd_doctor(repo_root: Path, *, verbose: bool = False) -> int:
    """Print a health report. Returns 0 if all checks pass, 1 otherwise."""
    print("agent-sync doctor")
    failures = 0

    # DB
    db_path = repo_root / "agent_sync" / "db" / "state.sqlite3"
    db_ok = db_path.exists()
    if not _check("DB exists", db_ok, str(db_path)):
        failures += 1
        print("    → Run `agent-sync init` to create it.")
    else:
        try:
            conn = get_connection(db_path)
            conn.execute("SELECT schema_version FROM schema_meta").fetchone()
            conn.close()
            _check("DB schema valid", True)
        except Exception as exc:
            _check("DB schema valid", False, str(exc))
            failures += 1

    # Provider binaries
    for binary in ("claude", "codex", "gemini"):
        found = shutil.which(binary) is not None
        if not _check(f"{binary} binary found", found):
            failures += 1

    # Claude settings.json
    claude_settings = repo_root / ".claude" / "settings.json"
    if claude_settings.exists():
        try:
            data = json.loads(claude_settings.read_text(encoding="utf-8"))
            has_hooks = "Stop" in data.get("hooks", {})
            _check("Claude hooks configured", has_hooks)
            if not has_hooks:
                failures += 1
        except Exception as exc:
            _check("Claude settings.json parseable", False, str(exc))
            failures += 1
    else:
        _check("Claude settings.json exists", False)
        failures += 1

    # Codex hooks
    codex_hooks = repo_root / ".codex" / "hooks.json"
    _check("Codex hooks.json exists", codex_hooks.exists())
    if not codex_hooks.exists():
        failures += 1

    # Gemini settings
    gemini_settings = repo_root / ".gemini" / "settings.json"
    _check("Gemini settings.json exists", gemini_settings.exists())
    if not gemini_settings.exists():
        failures += 1

    # Shell wrappers
    for wrapper in ("claude-dispatch.sh", "codex-dispatch.sh", "gemini-dispatch.sh"):
        p = repo_root / "agent_sync" / "shell" / wrapper
        ok = p.exists() and bool(p.stat().st_mode & 0o111)
        _check(f"Shell wrapper {wrapper} executable", ok)
        if not ok:
            failures += 1

    # AGENT_CONTRACT.md
    contract = repo_root / "agent_sync" / "docs" / "AGENT_CONTRACT.md"
    _check("AGENT_CONTRACT.md exists", contract.exists())
    if not contract.exists():
        failures += 1

    # .gitignore
    gitignore = repo_root / ".gitignore"
    if gitignore.exists():
        content = gitignore.read_text(encoding="utf-8")
        _check(".gitignore excludes worktrees", ".agent_sync/worktrees/" in content)
    else:
        _check(".gitignore exists", False)

    print(f"\n{'All checks passed.' if failures == 0 else f'{failures} check(s) failed.'}")
    return 0 if failures == 0 else 1
