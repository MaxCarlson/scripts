"""Read-only discovery and planning; summaries never contain full config text."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path

from .files import digest, inspect, tree_digest
from .manifest import Layout, assets, bridge_settings, role_text
from .profiles import (BEGIN, compose, generic_baseline, instruction_block, leaves,
                       lookup, parse_config, patch_config, strip_block)


@dataclass
class Operation:
    resource_id: str
    client: str
    path: Path
    kind: str
    before: dict
    content: bytes = b''
    source: Path | None = None
    method: str = 'copy'
    action: str = 'create'
    conflict: str = ''
    details: dict = field(default_factory=dict)
    desired_hash: str | None = None

    def summary(self) -> dict:
        return {'resource_id': self.resource_id, 'client': self.client,
                'path': str(self.path), 'kind': self.kind, 'before': self.before,
                'desired_hash': (self.desired_hash if self.desired_hash is not None else
                                 self.details['restore']['state'].get('hash') if 'restore' in self.details
                                 else tree_digest(self.source) if self.kind == 'tree' else digest(self.content)),
                'source': str(self.source) if self.source else None,
                'method': self.method, 'action': self.action, 'conflict': self.conflict,
                'retire': self.details.get('retire', False)}


@dataclass
class Plan:
    layout: Layout
    clients: tuple[str, ...]
    strategy: str
    mode: str
    adopt: tuple[str, ...]
    operations: list[Operation]
    receipt_state: dict
    code_retrieval: bool = False
    structural_retrieval: bool = False
    checkpoint_compaction: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def conflicts(self) -> list[str]:
        return [f'{op.resource_id}: {op.conflict}' for op in self.operations if op.conflict]

    def summary(self) -> dict:
        return {'schema_version': 1, 'home': str(self.layout.home), 'state_dir': str(self.layout.state),
                'clients': list(self.clients), 'strategy': self.strategy, 'mode': self.mode,
                'code_retrieval': self.code_retrieval,
                'structural_retrieval': self.structural_retrieval,
                'checkpoint_compaction': self.checkpoint_compaction,
                'adopt': list(self.adopt), 'receipt_state': self.receipt_state,
                'operations': [op.summary() for op in self.operations],
                'conflicts': self.conflicts, 'warnings': self.warnings}


def load_receipt(layout: Layout) -> dict:
    path = layout.state / 'receipt.json'
    if not path.exists():
        return {'schema_version': 1, 'resources': {}}
    value = json.loads(path.read_text(encoding='utf-8'))
    if value.get('schema_version') != 1 or not isinstance(value.get('resources'), dict):
        raise ValueError('Unsupported installation receipt')
    return value


def build_plan(home: Path, clients: tuple[str, ...] = ('codex', 'agy'), *,
               strategy: str = 'auto', adopt: tuple[str, ...] = (), state_dir: Path | None = None,
               environ: dict | None = None, mode: str = 'local',
               code_retrieval: bool | None = None,
               structural_retrieval: bool | None = None,
               checkpoint_compaction: bool | None = None) -> Plan:
    if not clients or set(clients) - {'codex', 'agy'}:
        raise ValueError('Supported clients: codex, agy')
    if strategy not in {'auto', 'link', 'copy'} or mode not in {'generic', 'local'}:
        raise ValueError('Invalid installation strategy or mode')
    if code_retrieval is not None and type(code_retrieval) is not bool:
        raise ValueError('code_retrieval must be a boolean or None')
    if checkpoint_compaction is not None and type(checkpoint_compaction) is not bool:
        raise ValueError('checkpoint_compaction must be a boolean or None')
    if structural_retrieval is not None and type(structural_retrieval) is not bool:
        raise ValueError('structural_retrieval must be a boolean or None')
    layout = Layout.discover(Path(home), state_dir, environ)
    receipt = load_receipt(layout)
    resources = receipt['resources']
    if code_retrieval is None:
        code_retrieval = any(rid.startswith('shared.code-retrieval.') for rid in resources)
    if structural_retrieval is None:
        structural_retrieval = any(rid.startswith('shared.structural-retrieval.') for rid in resources)
    if structural_retrieval:
        code_retrieval = True
    if checkpoint_compaction is None:
        checkpoint_compaction = any(rid.startswith('shared.checkpoint-compaction.') for rid in resources)
    plan = Plan(layout, tuple(dict.fromkeys(clients)), strategy, mode, tuple(adopt), [],
                inspect(layout.state / 'receipt.json'), code_retrieval=code_retrieval,
                structural_retrieval=structural_retrieval,
                checkpoint_compaction=checkpoint_compaction)
    method_file = 'link' if strategy == 'link' or (strategy == 'auto' and os.name != 'nt') else 'copy'
    method_tree = 'copy' if strategy == 'copy' else 'link'

    def add(rid: str, client: str, path: Path, kind: str, content: str = '',
            source: Path | None = None, method: str = 'copy', details: dict | None = None) -> Operation:
        before = inspect(path)
        op = Operation(rid, client, path, kind, before, content.encode(), source, method,
                       details=details or {})
        prior = resources.get(rid)
        if strategy == 'auto' and prior and kind in {'tree', 'file'}:
            method = prior.get('method', method)
            op.method = method
        if prior and prior['path'] != str(path):
            op.conflict = 'Effective destination changed; remove/reconcile the old destination first'
        elif prior and kind not in {'json', 'toml', 'block'} and before != prior['installed']:
            canonical_update = (before['kind'] == 'link' and method == 'link' and source is not None
                and before.get('target') == str(source.resolve()) and kind == 'tree'
                and before.get('hash') == tree_digest(source))
            if not canonical_update:
                op.conflict = 'Owned resource changed independently'
        elif before['kind'] != 'missing' and not prior and kind not in {'json', 'toml', 'block'} and rid not in adopt:
            op.conflict = 'Existing resource is unowned; inspect and use --adopt with this ID'
        expected = tree_digest(source) if kind == 'tree' else digest(op.content)
        if before.get('hash') == expected and (method != 'link' or
                (before['kind'] == 'link' and before.get('target') == str(source.resolve()))):
            op.action = 'unchanged'
        elif before['kind'] != 'missing':
            op.action = 'update'
        if op.conflict:
            op.action = 'conflict'
        if before['kind'] == 'link' and before['hash'] == 'missing' and rid not in adopt:
            op.conflict = 'Broken existing link requires reconciliation or explicit adoption'
            op.action = 'conflict'
        plan.operations.append(op)
        return op

    def config(rid: str, client: str, path: Path, kind: str, wanted: list[dict]) -> None:
        prior = resources.get(rid, {})
        text = path.read_text(encoding='utf-8-sig') if path.is_file() else ''
        op = add(rid, client, path, kind)
        try:
            if op.conflict or op.before['kind'] == 'directory':
                raise ValueError(op.conflict or 'Configuration path is a directory')
            doc = parse_config(text, kind)
            prefix = ['mcp_servers' if kind == 'toml' else 'mcpServers', 'opencode_worker']
            bridge_node = lookup(doc, prefix).get('value', {})
            if bridge_node and any(item['keys'][:2] == prefix for item in wanted) and not prior and rid not in adopt and (
                    not isinstance(bridge_node, dict) or bridge_node.get('command', bridge['command'])
                    not in {'npx', 'npx.cmd'} or bridge_node.get('args', bridge['args']) != bridge['args']):
                raise ValueError(f'Existing MCP definition differs; inspect and --adopt {rid}')
            rendered, edits = patch_config(text, kind, wanted, prior.get('edits', []))
            op.content = rendered.encode()
            op.details['edits'] = edits
            op.action = 'unchanged' if rendered == text else 'update' if text else 'create'
        except Exception as exc:
            op.conflict = str(exc)
            op.action = 'conflict'

    snippet = (assets() / 'instructions/coordinator.snippet.md').read_text(encoding='utf-8')
    base = (assets() / 'profiles/AGENTS.md').read_text(encoding='utf-8-sig')
    oc_path = layout.opencode / 'opencode.json'
    if (layout.opencode / 'opencode.jsonc').exists():
        raise ValueError('OpenCode JSONC config needs explicit reconciliation; no JSON rewrite was attempted')
    oc = parse_config(oc_path.read_text(encoding='utf-8-sig') if oc_path.exists() else '', 'json')
    model = oc.get('model', '')
    alias = model.split('/', 1)[1] if isinstance(model, str) and model.startswith('lmstudio/') else None
    if mode == 'local' and not alias:
        plan.warnings.append('Local model alias is not configured; use local-agent run before dispatch.')
    bridge = bridge_settings(alias)

    def connection(rid: str) -> dict:
        # Keep an intentional runtime port switch recorded by our writer.
        # Other bridge settings continue to come from the packaged manifest.
        from copy import deepcopy
        desired = deepcopy(bridge)
        for edit in resources.get(rid, {}).get('edits', []):
            if edit['keys'][-2:] == ['env', 'OPENCODE_BASE_URL'] and edit.get('after', {}).get('present'):
                desired['env']['OPENCODE_BASE_URL'] = edit['after']['value']
        return desired

    def original_bridge(rid: str, path: Path, kind: str) -> bool:
        prior = resources.get(rid)
        if prior:
            snapshot = prior['original']
            if snapshot['state']['kind'] == 'missing':
                return False
            text = Path(snapshot['backup']).read_text(encoding='utf-8-sig')
        else:
            text = path.read_text(encoding='utf-8-sig') if path.is_file() else ''
        node = lookup(parse_config(text, kind),
                      ['mcp_servers' if kind == 'toml' else 'mcpServers', 'opencode_worker']).get('value', {})
        return isinstance(node, dict) and node.get('command') in {'npx', 'npx.cmd'} and node.get('args') == bridge['args']

    for client in plan.clients:
        if client == 'codex':
            root = layout.codex
            instructions = root / ('AGENTS.override.md' if (root / 'AGENTS.override.md').is_file()
                                    and (root / 'AGENTS.override.md').stat().st_size else 'AGENTS.md')
            skill = layout.home / '.agents/skills/local-agent-handoff'
            duplicate = root / 'skills/local-agent-handoff'
        else:
            root = layout.home / '.gemini'
            choices = [root / 'AGENTS.md', root / 'GEMINI.md', root / 'config/AGENTS.md', root / 'config/GEMINI.md']
            active = [p for p in choices if p.is_file() and p.stat().st_size]
            if len(active) > 1:
                raise ValueError('Multiple agy global instruction files require reconciliation')
            instructions = active[0] if active else root / 'GEMINI.md'
            skill = root / 'antigravity-cli/skills/local-agent-handoff'
            duplicate = root / 'config/skills/local-agent-handoff'
        rid = client + '.instructions'
        prior = resources.get(rid, {})
        existing = instructions.read_text(encoding='utf-8-sig') if instructions.is_file() else ''
        try:
            if rid in adopt and prior and not prior.get('profile'):
                raise ValueError('Remove the existing block installation before adopting the whole profile')
            if rid in adopt or prior.get('profile') or not existing:
                # On adoption retain the active rules as the composition base.
                # Saved original backup remains immutable for eventual removal.
                origin = prior.get('baseline_origin') or ('adopted' if existing and rid in adopt else 'template')
                baseline = (base if origin == 'template' else
                            prior.get('baseline') or generic_baseline(existing, snippet))
                text = compose(baseline, snippet) if mode == 'local' else baseline
                rendered = layout.state / 'profiles' / client / 'AGENTS.md'
                add(rid + '.rendered', client, rendered, 'file', text)
                add(rid, client, instructions, 'file', text, rendered, method_file,
                    {'profile': True, 'baseline': baseline, 'baseline_origin': origin})
            else:
                previous = prior.get('block')
                if mode == 'local':
                    text = compose(existing, snippet, previous)
                    block = instruction_block(snippet) if BEGIN in text else None
                else:
                    text = strip_block(existing, previous) if previous else existing
                    block = None
                add(rid, client, instructions, 'block', text, details={'block': block})
        except ValueError as exc:
            op = add(rid, client, instructions, 'block', existing)
            op.conflict = str(exc)
            op.action = 'conflict'

        if client == 'codex':
            template = parse_config((assets() / 'profiles/codex.toml').read_text(), 'toml')
            wanted = [{'keys': keys, 'value': value, 'default': True} for keys, value in leaves(template)]
            config_path = root / 'config.toml'
            try:
                current = parse_config(config_path.read_text(encoding='utf-8-sig') if config_path.is_file() else '', 'toml')
            except ValueError:
                current = {}  # The config operation reports malformed TOML as a conflict.
            for key in ['file_opener', 'hide_agent_reasoning', 'show_raw_agent_reasoning',
                        'project_doc_max_bytes', 'project_doc_fallback_filenames']:
                legacy = lookup(current, ['history', key])
                if legacy['present']:
                    # Correct the old template's TOML table scope. Explicit
                    # root values win; otherwise retain the legacy value.
                    for item in wanted:
                        if item['keys'] == [key]:
                            item['value'] = legacy['value']
                wanted.append({'keys': ['history', key], 'present': False})
            if mode == 'local':
                wanted += [{'keys': ['mcp_servers', 'opencode_worker'] + keys, 'value': value}
                           for keys, value in leaves({**connection('codex.config'), 'enabled': True})]
            elif original_bridge('codex.config', root / 'config.toml', 'toml'):
                wanted.append({'keys': ['mcp_servers', 'opencode_worker', 'enabled'], 'value': False})
            config('codex.config', client, config_path, 'toml', wanted)
        else:
            template = parse_config((assets() / 'dotfiles_llms/gemini/settings.json').read_text(), 'json')
            config('agy.defaults', client, root / 'settings.json', 'json',
                   [{'keys': keys, 'value': value, 'default': True} for keys, value in leaves(template)])
            for suffix, path in [('mcp', root / 'antigravity-cli/mcp_config.json'),
                                 ('global-mcp', root / 'config/mcp_config.json')]:
                if mode != 'local' and not original_bridge('agy.' + suffix, path, 'json'):
                    continue
                wanted = [{'keys': ['mcpServers', 'opencode_worker'] + keys, 'value': value}
                          for keys, value in leaves({**connection('agy.' + suffix), 'disabled': False})] if mode == 'local' else [
                              {'keys': ['mcpServers', 'opencode_worker', 'disabled'], 'value': True}]
                config('agy.' + suffix, client, path, 'json', wanted)
            if mode == 'local':
                config('agy.permissions', client, root / 'antigravity-cli/settings.json', 'json',
                       [{'keys': ['permissions', 'allow'], 'list_item': 'mcp(opencode_worker/*)'}])

        for custom in sorted((assets() / 'dotfiles_llms/custom_agents/skills').iterdir()):
            if custom.is_dir() and (custom / 'SKILL.md').is_file():
                destination = skill.parent / custom.name
                custom_id = client + '.custom-skill.' + custom.name
                legacy = duplicate.parent / custom.name
                prior_custom = resources.get(custom_id)
                if prior_custom:
                    destination = Path(prior_custom['path'])
                elif custom_id in adopt and legacy.exists() and not destination.exists():
                    destination = legacy  # Adopt in place; do not create a duplicate.
                op = add(custom_id, client, destination, 'tree', source=custom, method=method_tree)
                if legacy.exists() and legacy.absolute() != destination.absolute():
                    op.conflict = f'Duplicate custom skill at {legacy}; reconcile before installation'
                    op.action = 'conflict'

        if mode == 'local':
            op = add(client + '.skill', client, skill, 'tree',
                     source=assets() / 'skills/local-agent-handoff', method=method_tree)
            if duplicate.exists():
                op.conflict = f'Duplicate skill discovery at {duplicate}; reconcile before installation'
                op.action = 'conflict'

    remaining_local = any(value == 'local' and key not in plan.clients
                          for key, value in receipt.get('modes', {}).items())
    if mode == 'local' or remaining_local:
        for role in ['local-worker', 'local-reviewer']:
            op = add('shared.' + role, 'shared', layout.opencode / 'agents' / (role + '.md'),
                     'file', role_text(role))
            if role in oc.get('agent', {}):
                op.conflict = 'Competing agent definition in OpenCode JSON config'
                op.action = 'conflict'
    if code_retrieval:
        tool_dir = assets() / 'opencode-tools'
        for name in ('local_agent_bridge.js', 'code_locate.js', 'code_context.js'):
            op = add('shared.code-retrieval.' + name.removesuffix('.js'), 'shared',
                     layout.opencode / 'tools' / name, 'file',
                     (tool_dir / name).read_text(encoding='utf-8'), method=method_file)
    if structural_retrieval:
        tool_dir = assets() / 'opencode-tools'
        for name in ('code_symbols.js', 'code_map.js'):
            add('shared.structural-retrieval.' + name.removesuffix('.js'), 'shared',
                layout.opencode / 'tools' / name, 'file',
                (tool_dir / name).read_text(encoding='utf-8'), method=method_file)
    if checkpoint_compaction:
        plugin = assets() / 'opencode-plugins' / 'local_agent_checkpoint.js'
        add('shared.checkpoint-compaction.plugin', 'shared',
            layout.opencode / 'plugins' / plugin.name, 'file',
            plugin.read_text(encoding='utf-8'), method=method_file)


    from .installer import removal_operation
    desired = {op.resource_id for op in plan.operations}
    modes = {**receipt.get('modes', {}), **dict.fromkeys(plan.clients, mode)}
    retired = []
    for rid, record in reversed(list(resources.items())):
        if rid not in desired and (record['client'] in plan.clients or
                record['client'] == 'shared' and ('local' not in modes.values() or
                rid.startswith('shared.code-retrieval.') and not code_retrieval or
                rid.startswith('shared.structural-retrieval.') and not structural_retrieval or
                rid.startswith('shared.checkpoint-compaction.') and not checkpoint_compaction)):
            op = removal_operation(layout, rid, record)
            op.details['retire'] = True
            retired.append(op)
    plan.operations = retired + plan.operations
    unknown = set(adopt) - desired
    if unknown:
        raise ValueError('Unknown adoption IDs: ' + ', '.join(sorted(unknown)))
    for op in plan.operations:
        op.desired_hash = op.summary()['desired_hash']
    return plan
