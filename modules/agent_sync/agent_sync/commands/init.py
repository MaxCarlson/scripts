"""agent-sync init — bootstrap DB, provider configs, and shell wrappers."""
import json
from pathlib import Path

from agent_sync.db.connection import get_connection
from agent_sync.db.schema import initialize_schema
from agent_sync.docs_gen.renderer import render_agent_contract
from agent_sync.docs_gen.templates import (
    AGENTS_MD_SECTION, CLAUDE_MD_SECTION, GEMINI_MD_SECTION,
)

_CLAUDE_HOOKS = {
    "hooks": {
        "SessionStart": [{"matcher": "", "hooks": [{"type": "command",
            "command": "${CLAUDE_PROJECT_DIR}/agent_sync/shell/claude-dispatch.sh",
            "args": ["SessionStart"], "timeout": 30}]}],
        "PreToolUse": [{"matcher": "Bash|Edit|Write", "hooks": [{"type": "command",
            "command": "${CLAUDE_PROJECT_DIR}/agent_sync/shell/claude-dispatch.sh",
            "args": ["PreToolUse"], "timeout": 30}]}],
        "PostToolUse": [{"matcher": "Bash|Edit|Write", "hooks": [{"type": "command",
            "command": "${CLAUDE_PROJECT_DIR}/agent_sync/shell/claude-dispatch.sh",
            "args": ["PostToolUse"], "timeout": 30}]}],
        "Stop": [{"hooks": [{"type": "command",
            "command": "${CLAUDE_PROJECT_DIR}/agent_sync/shell/claude-dispatch.sh",
            "args": ["Stop"], "timeout": 30}]}],
    }
}

_CODEX_HOOKS = {
    "hooks": {
        "SessionStart": [{"matcher": "", "hooks": [{"type": "command",
            "command": 'bash "$(git rev-parse --show-toplevel)/agent_sync/shell/codex-dispatch.sh" SessionStart',
            "timeout": 30, "statusMessage": "agent_sync session brief"}]}],
        "PreToolUse": [{"matcher": "Bash|Edit|Write", "hooks": [{"type": "command",
            "command": 'bash "$(git rev-parse --show-toplevel)/agent_sync/shell/codex-dispatch.sh" PreToolUse',
            "timeout": 30, "statusMessage": "agent_sync policy"}]}],
        "PostToolUse": [{"matcher": "Bash|Edit|Write", "hooks": [{"type": "command",
            "command": 'bash "$(git rev-parse --show-toplevel)/agent_sync/shell/codex-dispatch.sh" PostToolUse',
            "timeout": 30, "statusMessage": "agent_sync artifact capture"}]}],
        "Stop": [{"hooks": [{"type": "command",
            "command": 'bash "$(git rev-parse --show-toplevel)/agent_sync/shell/codex-dispatch.sh" Stop',
            "timeout": 30, "statusMessage": "agent_sync handoff"}]}],
    }
}

_GEMINI_HOOKS = {
    "hooks": {
        "SessionStart": [{"matcher": "", "hooks": [{"type": "command",
            "command": 'bash "$(git rev-parse --show-toplevel)/agent_sync/shell/gemini-dispatch.sh" SessionStart',
            "timeout": 30}]}],
        "PreToolUse": [{"matcher": "Bash|Edit|Write", "hooks": [{"type": "command",
            "command": 'bash "$(git rev-parse --show-toplevel)/agent_sync/shell/gemini-dispatch.sh" PreToolUse',
            "timeout": 30}]}],
        "PostToolUse": [{"matcher": "Bash|Edit|Write", "hooks": [{"type": "command",
            "command": 'bash "$(git rev-parse --show-toplevel)/agent_sync/shell/gemini-dispatch.sh" PostToolUse',
            "timeout": 30}]}],
        "Stop": [{"hooks": [{"type": "command",
            "command": 'bash "$(git rev-parse --show-toplevel)/agent_sync/shell/gemini-dispatch.sh" Stop',
            "timeout": 30}]}],
    }
}

_CODEX_CONFIG_TOML = """\
[profile.default]
model = "codex-default"

[mcp]
# Add MCP servers here if needed
"""

_CODEX_RULES = """\
# agent_sync guarded command policy
# These prefixes are blocked unless running through agent-sync integrate
deny git push
deny git commit --amend
deny gh pr create
deny gh pr merge
deny rm -rf /
deny sudo
"""

_GITIGNORE_ADDITIONS = [
    ".agent_sync/worktrees/",
    "agent_sync/db/state.sqlite3",
]


def cmd_init(repo_root: Path, *, dry_run: bool = False) -> None:
    """Bootstrap agent_sync DB, provider configs, and static docs.

    Args:
        repo_root: Repository root directory.
        dry_run: If True, print planned changes but do not write anything.
    """
    if dry_run:
        _print_plan(repo_root)
        return
    _do_init(repo_root)


def _print_plan(repo_root: Path) -> None:
    print("agent-sync init — planned changes (dry run):")
    print(f"  create  {repo_root}/agent_sync/db/state.sqlite3")
    print(f"  create  {repo_root}/agent_sync/docs/AGENT_CONTRACT.md")
    print(f"  update  {repo_root}/.claude/settings.json  (merge hooks)")
    print(f"  create  {repo_root}/.codex/hooks.json")
    print(f"  create  {repo_root}/.codex/config.toml")
    print(f"  create  {repo_root}/.codex/rules/agent_sync.rules")
    print(f"  create  {repo_root}/.gemini/settings.json")
    print(f"  update  {repo_root}/AGENTS.md  (append agent_sync section)")
    print(f"  update  {repo_root}/CLAUDE.md   (append agent_sync section)")
    print(f"  create  {repo_root}/GEMINI.md")
    print(f"  update  {repo_root}/.gitignore  (append worktree + db paths)")


def _do_init(repo_root: Path) -> None:
    # 1. DB
    db_path = repo_root / "agent_sync" / "db" / "state.sqlite3"
    conn = get_connection(db_path)
    initialize_schema(conn)
    conn.close()
    print(f"[init] DB initialized at {db_path}")

    # 2. AGENT_CONTRACT.md
    contract_path = repo_root / "agent_sync" / "docs" / "AGENT_CONTRACT.md"
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    contract_path.write_text(render_agent_contract(), encoding="utf-8")
    print(f"[init] Wrote {contract_path}")

    # 3. Claude hooks — merge into .claude/settings.json
    claude_settings = repo_root / ".claude" / "settings.json"
    claude_settings.parent.mkdir(parents=True, exist_ok=True)
    existing: dict = {}
    if claude_settings.exists():
        existing = json.loads(claude_settings.read_text(encoding="utf-8"))
    existing.setdefault("hooks", {}).update(_CLAUDE_HOOKS["hooks"])
    claude_settings.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    print(f"[init] Updated {claude_settings}")

    # 4. Codex config
    codex_dir = repo_root / ".codex"
    codex_dir.mkdir(exist_ok=True)
    (codex_dir / "hooks.json").write_text(
        json.dumps(_CODEX_HOOKS, indent=2), encoding="utf-8"
    )
    (codex_dir / "config.toml").write_text(_CODEX_CONFIG_TOML, encoding="utf-8")
    rules_dir = codex_dir / "rules"
    rules_dir.mkdir(exist_ok=True)
    (rules_dir / "agent_sync.rules").write_text(_CODEX_RULES, encoding="utf-8")
    print(f"[init] Wrote Codex config to {codex_dir}")

    # 5. Gemini hooks
    gemini_dir = repo_root / ".gemini"
    gemini_dir.mkdir(exist_ok=True)
    existing_gemini: dict = {}
    gemini_settings = gemini_dir / "settings.json"
    if gemini_settings.exists():
        existing_gemini = json.loads(gemini_settings.read_text(encoding="utf-8"))
    existing_gemini.setdefault("hooks", {}).update(_GEMINI_HOOKS["hooks"])
    gemini_settings.write_text(
        json.dumps(existing_gemini, indent=2), encoding="utf-8"
    )
    print(f"[init] Updated {gemini_settings}")

    # 6. Instruction file sections
    _append_section(repo_root / "AGENTS.md", AGENTS_MD_SECTION, "## agent_sync")
    _append_section(repo_root / "CLAUDE.md", CLAUDE_MD_SECTION, "## agent_sync")
    gemini_md = repo_root / "GEMINI.md"
    if not gemini_md.exists():
        gemini_md.write_text(
            f"# Gemini CLI project instructions\n{GEMINI_MD_SECTION}",
            encoding="utf-8",
        )
        print(f"[init] Created {gemini_md}")

    # 7. .gitignore additions
    gitignore = repo_root / ".gitignore"
    existing_ignore = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    additions = [p for p in _GITIGNORE_ADDITIONS if p not in existing_ignore]
    if additions:
        with gitignore.open("a", encoding="utf-8") as f:
            f.write("\n# agent_sync\n" + "\n".join(additions) + "\n")
        print(f"[init] Updated {gitignore}")

    print("[init] Done. Run `agent-sync doctor` to verify.")


def _append_section(path: Path, section: str, marker: str) -> None:
    """Append section to a Markdown file if the marker is not already present."""
    if path.exists():
        content = path.read_text(encoding="utf-8")
        if marker in content:
            return
        path.write_text(content + "\n" + section, encoding="utf-8")
    else:
        path.write_text(section, encoding="utf-8")
    print(f"[init] Updated {path}")
