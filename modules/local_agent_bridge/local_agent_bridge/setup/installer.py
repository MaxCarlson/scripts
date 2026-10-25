"""Receipt-based application, exact contribution removal and recovery."""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import uuid

from .files import (atomic_write, capture, create_link, digest, erase, inspect,
                    restore, tree_digest, validate_snapshot, write_json)
from .manifest import Layout
from .planner import Operation, Plan, build_plan, load_receipt
from .profiles import parse_config, revert_edit, serialize, strip_block


def alive(pid: int) -> bool:
    if os.name == 'nt':
        import ctypes
        kernel = ctypes.windll.kernel32
        kernel.OpenProcess.restype = ctypes.c_void_p
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return kernel.GetLastError() == 5  # Access denied: conservatively live.
        code = ctypes.c_ulong()
        try:
            return not kernel.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(code)) or code.value == 259
        finally:
            kernel.CloseHandle(ctypes.c_void_p(handle))
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


@contextmanager
def install_lock(layout: Layout):
    layout.state.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock = layout.state / 'setup.lock'
    if lock.exists():
        try:
            owner = json.loads(lock.read_text())
            if alive(int(owner['pid'])):
                raise ValueError('Another setup process owns the installation lock')
        except (KeyError, json.JSONDecodeError):
            raise ValueError('Malformed setup lock requires manual reconciliation') from None
        lock.unlink()
    with lock.open('x', encoding='utf-8') as stream:
        json.dump({'pid': os.getpid()}, stream)
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


def expected_state(op: Operation) -> dict:
    if op.action == 'restore':
        return op.details['restore']['state']
    target_hash = op.desired_hash if op.kind == 'tree' else digest(op.content)
    if op.method == 'link':
        return {'kind': 'link', 'target': str(op.source.resolve()), 'hash': target_hash}
    if op.kind in {'block', 'json', 'toml'} and op.before['kind'] == 'link':
        return {**op.before, 'hash': target_hash}
    return {'kind': 'directory' if op.kind == 'tree' else 'file', 'hash': target_hash}


def install_operation(op: Operation) -> None:
    if op.action == 'restore':
        restore(op.path, op.details['restore'])
    elif op.method == 'link':
        erase(op.path)
        create_link(op.path, op.source, op.kind == 'tree')
    elif op.kind == 'tree':
        import shutil
        erase(op.path)
        op.path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(op.source, op.path)
    else:
        # Adopted whole files replace a link entry; contribution edits follow it.
        if op.kind == 'file' and op.before['kind'] == 'link':
            erase(op.path)
        atomic_write(op.path, op.content, follow=op.kind != 'file')


def _safe_record(layout: Layout, record: dict) -> None:
    path = Path(record['path']).absolute()
    if not any(path.is_relative_to(root) and path != root
               for root in (layout.home, layout.state, layout.codex, layout.opencode)):
        raise ValueError(f'Receipt destination is outside the installation roots: {path}')


def removal_operation(layout: Layout, rid: str, record: dict) -> Operation:
    _safe_record(layout, record)
    path = Path(record['path'])
    current = inspect(path)
    kind = record['kind']
    op = Operation(rid, record['client'], path, kind, current)
    try:
        if kind in {'json', 'toml'}:
            doc = parse_config(path.read_text(encoding='utf-8-sig'), kind)
            for edit in reversed(record.get('edits', [])):
                revert_edit(doc, edit)
            if not doc and record['original']['state']['kind'] == 'missing':
                op.action = 'restore'
                op.details['restore'] = record['original']
            else:
                op.content = serialize(doc, kind).encode()
                op.action = 'update'
        elif kind == 'block':
            text = path.read_text(encoding='utf-8-sig')
            block = record.get('block')
            op.content = (strip_block(text, block) if block else text).encode()
            op.action = 'update'
        else:
            if current != record['installed']:
                raise ValueError('Owned resource changed independently')
            op.action = 'restore'
            op.details['restore'] = record['original']
        if current == expected_state(op):
            op.action = 'unchanged'
        elif op.action == 'restore':
            validate_snapshot(op.details['restore'])
    except (OSError, ValueError, KeyError) as exc:
        op.conflict = str(exc)
        op.action = 'conflict'
    return op


def _rollback(layout: Layout, journal: dict) -> list[str]:
    errors = []
    for change in reversed(journal['changes']):
        path = Path(change['path'])
        current = inspect(path)
        if current == change['before']['state']:
            continue
        if current != change['after']:
            errors.append(f'Preserved concurrent/partial change: {path}')
            continue
        try:
            restore(path, change['before'])
        except (OSError, ValueError):
            errors.append(f'Could not restore: {path}')
    if not errors:
        journal['status'] = 'rolled_back'
    else:
        journal['status'] = 'recovery_required'
    write_json(layout.state / 'journal.json', journal)
    return errors


def recover_installation(home: Path, *, state_dir: Path | None = None, environ: dict | None = None) -> dict:
    layout = Layout.discover(home, state_dir, environ)
    with install_lock(layout):
        journal_path = layout.state / 'journal.json'
        if not journal_path.exists():
            return {'code': 0, 'message': 'No interrupted installation'}
        journal = json.loads(journal_path.read_text())
        if journal['status'] not in {'applying', 'recovery_required'}:
            return {'code': 0, 'message': 'No interrupted installation'}
        for item in journal['changes']:
            _safe_record(layout, item)
        errors = _rollback(layout, journal)
        return {'code': 5 if errors else 0, 'errors': errors, 'message': 'Recovery checked'}


def _transact(plan: Plan, operations: list[Operation], receipt: dict) -> dict:
    if any(op.conflict for op in operations):
        raise ValueError('Installation conflict: ' + '; '.join(op.conflict for op in operations if op.conflict))
    # All inputs are checked before even creating the state/lock directory.
    for op in operations:
        if inspect(op.path) != op.before:
            raise ValueError(f'stale plan: {op.path}')
        if op.kind == 'tree' and op.source and tree_digest(op.source) != op.desired_hash:
            raise ValueError(f'stale source resource: {op.source}')
    if inspect(plan.layout.state / 'receipt.json') != plan.receipt_state:
        raise ValueError('stale installation receipt')
    layout = plan.layout
    changed = [op for op in operations if op.action != 'unchanged']
    if not changed and receipt == load_receipt(layout) and all(
            record.get('installed') == inspect(Path(record['path']))
            for record in receipt['resources'].values()):
        return {'schema_version': 1, 'code': 0, 'changed': [], 'warnings': plan.warnings}
    with install_lock(layout):
        journal_path = layout.state / 'journal.json'
        if journal_path.exists() and json.loads(journal_path.read_text())['status'] in {'applying', 'recovery_required'}:
            raise ValueError('Interrupted setup: run local-agent setup recover first')
        if inspect(layout.state / 'receipt.json') != plan.receipt_state:
            raise ValueError('stale installation receipt')
        run = uuid.uuid4().hex
        journal = {'schema_version': 1, 'status': 'applying', 'changes': []}
        old_resources = load_receipt(layout)['resources']
        try:
            for index, op in enumerate(operations):
                if op.kind == 'tree' and op.source and tree_digest(op.source) != op.desired_hash:
                    raise ValueError(f'stale source resource: {op.source}')
                current = inspect(op.path)
                generated_update = op.method == 'link' and current == expected_state(op)
                if current != op.before and not generated_update:
                    raise ValueError(f'stale plan: {op.path}')
                if generated_update:
                    op.action = 'unchanged'
                backup = None
                if op.action != 'unchanged' or (op.resource_id in receipt['resources'] and
                                               op.resource_id not in old_resources):
                    backup = capture(op.path, layout.state / 'backups' / run / str(index),
                                     follow=op.kind in {'block', 'json', 'toml'} and op.action != 'restore')
                if op.action != 'unchanged':
                    journal['changes'].append({'path': str(op.path), 'before': backup, 'after': expected_state(op)})
                    write_json(journal_path, journal)
                    try:
                        install_operation(op)
                    except Exception:
                        if plan.strategy != 'auto' or op.method != 'link' or inspect(op.path)['kind'] != 'missing':
                            raise
                        op.method = 'copy'
                        journal['changes'][-1]['after'] = expected_state(op)
                        write_json(journal_path, journal)
                        install_operation(op)
                    if inspect(op.path) != expected_state(op):
                        raise OSError(f'Post-write verification failed: {op.path}')
                if op.resource_id in receipt['resources']:
                    old = old_resources.get(op.resource_id)
                    receipt['resources'][op.resource_id].update(
                        {'installed': inspect(op.path), 'method': op.method,
                         'original': old['original'] if old else backup,
                         **op.details})
            # Receipt publication participates in recovery, too.
            receipt_path = layout.state / 'receipt.json'
            backup = capture(receipt_path, layout.state / 'backups' / run / 'receipt', follow=False)
            data = (json.dumps(receipt, indent=2) + '\n').encode()
            journal['changes'].append({'path': str(receipt_path), 'before': backup,
                                       'after': {'kind': 'file', 'hash': digest(data)}})
            write_json(journal_path, journal)
            atomic_write(receipt_path, data)
            journal['status'] = 'complete'
            write_json(journal_path, journal)
        except BaseException:
            errors = _rollback(layout, journal)
            if errors:
                raise RuntimeError('Incomplete rollback; run setup recover. ' + '; '.join(errors)) from None
            raise
    return {'schema_version': 1, 'code': 0, 'changed': [op.resource_id for op in changed], 'warnings': plan.warnings}


def apply_plan(plan: Plan, expected: dict | None = None) -> dict:
    # Regenerate from trusted code; never execute arbitrary saved JSON operations.
    fresh = build_plan(plan.layout.home, plan.clients, strategy=plan.strategy, adopt=plan.adopt,
                       state_dir=plan.layout.state, mode=plan.mode,
                       code_retrieval=plan.code_retrieval,
                       checkpoint_compaction=plan.checkpoint_compaction)
    if fresh.summary() != (expected or plan.summary()):
        raise ValueError('stale plan: targets or sources changed; regenerate the plan')
    receipt = load_receipt(plan.layout)
    modes = {**receipt.get('modes', {}), **dict.fromkeys(plan.clients, plan.mode)}
    for op in plan.operations:
        if op.details.get('retire'):
            receipt['resources'].pop(op.resource_id, None)
            continue
        receipt['resources'].setdefault(op.resource_id, {})
        receipt['resources'][op.resource_id].update(
            {'path': str(op.path), 'kind': op.kind, 'client': op.client, 'method': op.method})
    receipt['modes'] = modes
    return _transact(plan, plan.operations, receipt)


def remove_installation(home: Path, clients: tuple[str, ...] = ('codex', 'agy'), *, execute: bool = False,
                        state_dir: Path | None = None, environ: dict | None = None) -> dict:
    layout = Layout.discover(home, state_dir, environ)
    receipt = load_receipt(layout)
    modes = {k: v for k, v in receipt.get('modes', {}).items() if k not in clients}
    selected = {rid: record for rid, record in receipt['resources'].items()
                if record['client'] in clients or record['client'] == 'shared' and 'local' not in modes.values()}
    # Reverse installation order so links are restored before generated targets.
    ops = [removal_operation(layout, rid, record) for rid, record in reversed(list(selected.items()))]
    conflicts = [op.conflict for op in ops if op.conflict]
    if conflicts:
        return {'schema_version': 1, 'code': 3, 'conflicts': conflicts}
    if not execute:
        return {'schema_version': 1, 'code': 0, 'operations': [op.summary() for op in ops]}
    for rid in selected:
        del receipt['resources'][rid]
    receipt['modes'] = modes
    plan = Plan(layout, clients, 'copy', 'generic', (), ops, inspect(layout.state / 'receipt.json'))
    return _transact(plan, ops, receipt)
