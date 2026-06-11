"""agent-sync init command."""

import json
from pathlib import Path

from agent_sync.config import default_config, save_config
from agent_sync.db.connection import get_connection
from agent_sync.db.schema import initialize_schema
from agent_sync.docs_gen.renderer import render_agent_contract
from agent_sync.docs_gen.templates import AGENTS_MD_SECTION, CLAUDE_MD_SECTION, GEMINI_MD_SECTION
from agent_sync.paths import audit_dir, config_path, db_path, docs_dir

_GITIGNORE_ADDITIONS = [
    ".agent_sync/audit/",
    ".agent_sync/tmp/",
    "agent_sync/db/state.sqlite3",
    ".agent_sync/worktrees/",
]


def cmd_init(repo_root: Path, *, dry_run: bool = False, force: bool = False) -> None:
    """Bootstrap agent_sync DB, config, docs, and instruction sections."""
    if dry_run:
        print("agent-sync init — planned changes:")
        print(f"  create/update  {config_path(repo_root)}")
        print(f"  create/update  {db_path(repo_root)}")
        print(f"  create/update  {docs_dir(repo_root) / 'AGENT_CONTRACT.md'}")
        print(f"  create/update  {repo_root / 'AGENTS.md'}")
        print(f"  create/update  {repo_root / 'CLAUDE.md'}")
        print(f"  create/update  {repo_root / 'GEMINI.md'}")
        print(f"  create/update  {repo_root / '.gitignore'}")
        return

    save_config(default_config(), config_path(repo_root), force=force)
    print(f"[init] Wrote {config_path(repo_root)}")

    conn = get_connection(db_path(repo_root))
    initialize_schema(conn)
    conn.close()
    print(f"[init] DB initialized at {db_path(repo_root)}")

    docs = docs_dir(repo_root)
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "AGENT_CONTRACT.md").write_text(render_agent_contract(), encoding="utf-8")
    audit_dir(repo_root).mkdir(parents=True, exist_ok=True)
    print(f"[init] Wrote {docs / 'AGENT_CONTRACT.md'}")

    _append_section(repo_root / "AGENTS.md", AGENTS_MD_SECTION, "## agent_sync")
    _append_section(repo_root / "CLAUDE.md", CLAUDE_MD_SECTION, "## agent_sync")
    _append_section(repo_root / "GEMINI.md", GEMINI_MD_SECTION, "## agent_sync")
    _append_gitignore(repo_root / ".gitignore")
    print("[init] Done. Run `agent-sync doctor` to verify.")


def _append_section(path: Path, section: str, marker: str) -> None:
    if path.exists():
        content = path.read_text(encoding="utf-8")
        if marker in content:
            return
        path.write_text(content.rstrip() + "\n" + section, encoding="utf-8")
    else:
        path.write_text(section.lstrip(), encoding="utf-8")
    print(f"[init] Updated {path}")


def _append_gitignore(path: Path) -> None:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    additions = [item for item in _GITIGNORE_ADDITIONS if item not in existing]
    if not additions:
        return
    with path.open("a", encoding="utf-8") as stream:
        stream.write("\n# agent_sync\n")
        stream.write("\n".join(additions))
        stream.write("\n")
    print(f"[init] Updated {path}")
