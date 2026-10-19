"""Shared preserving config writers for the legacy and new run commands."""
from __future__ import annotations

import json
from pathlib import Path

from .files import atomic_write, inspect, write_json
from .manifest import Layout, bridge_settings
from .profiles import leaves, lookup, parse_config, patch_config


def refresh_receipt(path: Path, home: Path, before_text: str) -> None:
    receipt_path = home / '.local/share/local-agent/receipt.json'
    if not receipt_path.is_file():
        return
    receipt = json.loads(receipt_path.read_text())
    for record in receipt.get('resources', {}).values():
        if record['path'] != str(path) or record['kind'] not in {'json', 'toml'}:
            continue
        doc = parse_config(path.read_text(encoding='utf-8-sig'), record['kind'])
        before = parse_config(before_text, record['kind'])
        prefix = ['mcp_servers' if record['kind'] == 'toml' else 'mcpServers', 'opencode_worker']
        owned = {tuple(edit['keys']) for edit in record.get('edits', [])}
        # A first run may add a model field absent during setup. Track its
        # original absence so removal does not leave an orphan bridge behind.
        for keys, value in leaves(doc):
            if keys[:2] != prefix or tuple(keys) in owned:
                continue
            original = lookup(before, keys)
            if original != {'present': True, 'value': value}:
                record.setdefault('edits', []).append({
                    'keys': keys, 'before': original, 'after': lookup(doc, keys),
                    'keep_empty': [keys[:n] for n in range(1, len(keys))
                                   if lookup(before, keys[:n])['present']],
                })
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
        before_text = path.read_text(encoding='utf-8-sig') if path.exists() else ''
        before = parse_config(before_text, 'json')
        if before == data:
            return False
        atomic_write(path, (json.dumps(data, indent=2) + '\n').encode())
        refresh_receipt(path, home, before_text)
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
        refresh_receipt(path, home, before)
        return True


def remove_codex_bridge(path: Path, home: Path) -> None:
    """Remove the runtime connection with preserving TOML and receipt writers."""
    from .installer import install_lock
    from .profiles import serialize
    layout = Layout.discover(home, None, {})
    with install_lock(layout):
        before = path.read_text(encoding='utf-8-sig')
        doc = parse_config(before, 'toml')
        servers = doc.get('mcp_servers', {})
        servers.pop('opencode_worker', None)
        atomic_write(path, serialize(doc, 'toml').encode())
        refresh_receipt(path, home, before)
