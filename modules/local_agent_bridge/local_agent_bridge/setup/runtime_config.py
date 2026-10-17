"""Shared preserving config writers for the legacy and new run commands."""
from __future__ import annotations

import json
from pathlib import Path

from .files import atomic_write, inspect, write_json
from .manifest import Layout, bridge_settings
from .profiles import leaves, lookup, parse_config, patch_config


def refresh_receipt(path: Path, home: Path) -> None:
    receipt_path = home / '.local/share/local-agent/receipt.json'
    if not receipt_path.is_file():
        return
    receipt = json.loads(receipt_path.read_text())
    for record in receipt.get('resources', {}).values():
        if record['path'] != str(path) or record['kind'] not in {'json', 'toml'}:
            continue
        doc = parse_config(path.read_text(encoding='utf-8-sig'), record['kind'])
        for edit in record.get('edits', []):
            # Runtime intentionally switches only bridge connection fields.
            if edit['keys'][:2] in [['mcp_servers', 'opencode_worker'], ['mcpServers', 'opencode_worker']]:
                edit['after'] = lookup(doc, edit['keys'])
        record['installed'] = inspect(path)
    write_json(receipt_path, receipt)


def save_json(path: Path, data: dict, home: Path) -> bool:
    from .installer import install_lock
    layout = Layout.discover(home, None, {})
    with install_lock(layout):
        before = parse_config(path.read_text(encoding='utf-8-sig') if path.exists() else '', 'json')
        if before == data:
            return False
        atomic_write(path, (json.dumps(data, indent=2) + '\n').encode())
        refresh_receipt(path, home)
        return True


def save_codex(path: Path, nickname: str, port: int, home: Path) -> bool:
    from .installer import install_lock
    layout = Layout.discover(home, None, {})
    with install_lock(layout):
        before = path.read_text(encoding='utf-8-sig') if path.exists() else ''
        wanted = [{'keys': ['mcp_servers', 'opencode_worker'] + keys, 'value': value}
                  for keys, value in leaves({**bridge_settings(nickname, port), 'enabled': True})]
        after, _ = patch_config(before, 'toml', wanted, [])
        if after == before:
            return False
        atomic_write(path, after.encode())
        refresh_receipt(path, home)
        return True
