"""Pure instruction composition and preserving JSON/TOML contribution edits."""
from __future__ import annotations

from collections.abc import Mapping
import json
from typing import Any

import tomlkit

BEGIN = '<!-- local-agent-bridge:begin -->'
END = '<!-- local-agent-bridge:end -->'
SLOT = '<!-- local_agent:insert capabilities -->'


def render_template(template: str, insertions: dict[str, str]) -> str:
    """Insert named fragments at unique anchors without modifying the source."""
    import re
    for name, content in insertions.items():
        if not re.fullmatch(r'[a-z][a-z0-9_-]*', name):
            raise ValueError(f'Invalid insertion name: {name}')
        anchor = f'<!-- local_agent:insert {name} -->'
        if template.count(anchor) != 1:
            raise ValueError(f'Expected one insertion anchor: {name}')
        template = template.replace(anchor, anchor + ('\n\n' + content.strip() if content.strip() else ''))
    return template


def instruction_block(snippet: str) -> str:
    return f'{BEGIN}\n{snippet.strip()}\n{END}'


def compose(existing: str, snippet: str, previous: str | None = None) -> str:
    block = instruction_block(snippet)
    if BEGIN in existing or END in existing:
        if existing.count(BEGIN) != 1 or existing.count(END) != 1:
            raise ValueError('Ambiguous delegation markers')
        start, finish = existing.index(BEGIN), existing.index(END) + len(END)
        if finish < start or (previous and existing[start:finish] != previous):
            raise ValueError('Delegation block was independently edited')
        if not previous and existing[start:finish] != block:
            raise ValueError('Unowned delegation block differs')
        return existing[:start] + block + existing[finish:]
    if snippet.strip() in existing:
        if existing.count(snippet.strip()) != 1:
            raise ValueError('Duplicate unmarked delegation snippet')
        return existing  # Existing unmarked policy is not owned or removed.
    if SLOT in existing:
        return render_template(existing, {'capabilities': block})
    return existing.rstrip() + '\n\n' + SLOT + '\n\n' + block + '\n'


def strip_block(existing: str, previous: str) -> str:
    if existing.count(previous) != 1:
        raise ValueError('Managed delegation block changed or missing')
    return existing.replace(previous, '', 1)


def generic_baseline(existing: str, snippet: str) -> str:
    """Separate a recognized pre-existing local contribution during adoption."""
    if BEGIN in existing or END in existing:
        compose(existing, snippet)  # Reject malformed or independently edited markers.
        return strip_block(existing, instruction_block(snippet))
    if existing.count(snippet.strip()) > 1:
        raise ValueError('Duplicate local delegation text requires reconciliation')
    return existing.replace(snippet.strip(), '', 1) if snippet.strip() in existing else existing


def parse_config(text: str, kind: str) -> Any:
    doc = tomlkit.parse(text) if kind == 'toml' else json.loads(text or '{}')
    if not isinstance(doc, Mapping):
        raise ValueError('Configuration root must be an object')
    return doc


def serialize(doc: Any, kind: str) -> str:
    return tomlkit.dumps(doc) if kind == 'toml' else json.dumps(doc, indent=2) + '\n'


def lookup(doc: Any, keys: list[str]) -> dict:
    node = doc
    for key in keys:
        if not isinstance(node, Mapping) or key not in node:
            return {'present': False}
        node = node[key]
    # Unwrap tomlkit values and avoid storing library-specific objects in receipts.
    return {'present': True, 'value': json.loads(json.dumps(node))}


def assign(doc: Any, keys: list[str], value: dict, keep_empty: list[list[str]] = ()) -> None:
    node = doc
    parents = []
    for key in keys[:-1]:
        if key not in node:
            if not value['present']:
                return
            node[key] = {}
        if not isinstance(node[key], Mapping):
            raise ValueError(f'Configuration parent is not an object: {key}')
        parents.append((node, key))
        node = node[key]
    if value['present']:
        node[keys[-1]] = value['value']
    else:
        node.pop(keys[-1], None)
        for depth, (parent, key) in reversed(list(enumerate(parents, 1))):
            if keys[:depth] in keep_empty:
                break
            if len(parent[key]):
                break
            del parent[key]


def leaves(doc: Mapping, prefix: tuple[str, ...] = ()) -> list[tuple[list[str], Any]]:
    result = []
    for key, value in doc.items():
        if isinstance(value, Mapping):
            result.extend(leaves(value, prefix + (key,)))
        else:
            result.append((list(prefix + (key,)), value))
    return result


def patch_config(text: str, kind: str, wanted: list[dict], previous: list[dict]) -> tuple[str, list[dict]]:
    doc = parse_config(text, kind)
    original = parse_config(text, kind)
    old = {tuple(edit['keys']): edit for edit in previous}
    edits = []
    for item in wanted:
        keys = item['keys']
        current = lookup(doc, keys)
        prior = old.get(tuple(keys))
        keep_empty = prior.get('keep_empty', []) if prior else [keys[:n] for n in range(1, len(keys))
            if lookup(original, keys[:n])['present']]
        if 'list_item' in item:
            values = current.get('value', [])
            if not isinstance(values, list):
                raise ValueError('Permission allow configuration must be a list')
            rule = item['list_item']
            if prior and prior.get('added') and values.count(rule) != 1:
                raise ValueError('Owned permission rule was changed')
            added = prior.get('added') if prior else rule not in values
            updated = values + [rule] if rule not in values else values
            if updated != values:
                assign(doc, keys, {'present': True, 'value': updated})
            if added:
                edits.append({'keys': keys, 'list_item': rule, 'added': True,
                              'before': prior['before'] if prior else current, 'keep_empty': keep_empty})
            continue
        desired = {'present': True, 'value': item['value']} if item.get('present', True) else {'present': False}
        if prior and current != prior['after']:
            if item.get('default'):
                # Defaults seed missing settings; later user choices belong to
                # the user and must also survive uninstall.
                continue
            raise ValueError(f'Managed configuration field changed: {".".join(keys)}')
        if item.get('default') and current['present']:
            if prior:
                edits.append(prior)
            continue
        before = prior['before'] if prior else current
        if current != desired:
            assign(doc, keys, desired)
        if prior or before != desired:
            edits.append({'keys': keys, 'before': before, 'after': desired, 'keep_empty': keep_empty})
    # A feature was disabled or removed from the desired profile.
    for keys, prior in old.items():
        if not any(tuple(item['keys']) == keys for item in wanted):
            revert_edit(doc, prior)
    rendered = serialize(doc, kind)
    return (text if parse_config(text, kind) == doc else rendered), edits


def revert_edit(doc: Any, edit: dict) -> None:
    current = lookup(doc, edit['keys'])
    if 'list_item' in edit:
        values = current.get('value')
        if not isinstance(values, list) or values.count(edit['list_item']) != 1:
            raise ValueError('Owned permission rule changed independently')
        values = [value for value in values if value != edit['list_item']]
        desired = {'present': True, 'value': values} if values or edit['before']['present'] else {'present': False}
    else:
        if current != edit['after']:
            raise ValueError('Owned configuration field changed independently')
        desired = edit['before']
    assign(doc, edit['keys'], desired, edit.get('keep_empty', []))
