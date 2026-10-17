"""Fingerprints, atomic writes and exact-path backup/restore operations."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def linked(path: Path) -> bool:
    if path.is_symlink() or getattr(path, 'is_junction', lambda: False)():
        return True
    if os.name == 'nt' and path.exists():
        import ctypes
        attributes = ctypes.windll.kernel32.GetFileAttributesW(str(path))
        return attributes != -1 and bool(attributes & 0x400)
    return False


def tree_digest(path: Path) -> str:
    entries = []
    for item in sorted(path.rglob('*')):
        if linked(item):
            raise ValueError(f'Nested links are unsupported in copied resources: {item}')
        relative = item.relative_to(path).as_posix()
        entries.append((relative, digest(item.read_bytes()) if item.is_file() else 'directory'))
    return digest(json.dumps(entries).encode())


def inspect(path: Path) -> dict:
    if linked(path):
        return {'kind': 'link', 'target': str(path.resolve()),
                'hash': tree_digest(path) if path.is_dir() else
                digest(path.read_bytes()) if path.is_file() else 'missing'}
    if path.is_dir():
        return {'kind': 'directory', 'hash': tree_digest(path)}
    if path.is_file():
        return {'kind': 'file', 'hash': digest(path.read_bytes())}
    return {'kind': 'missing'}


def atomic_write(path: Path, data: bytes, *, follow: bool = True) -> None:
    target = path.resolve() if follow else path.absolute()
    before = inspect(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.local-agent-', dir=target.parent)
    try:
        if target.is_file():
            os.chmod(name, target.stat().st_mode & 0o777)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(5):
            if inspect(target) != before or (follow and path.resolve() != target):
                raise ValueError(f'Concurrent change before atomic replacement: {path}')
            try:
                os.replace(name, target)
                break
            except PermissionError:
                if os.name != 'nt' or attempt == 4:
                    raise
                # Windows can deny replacement while a short-lived reader holds
                # the old file. Retry only while the target is unchanged.
                time.sleep((0.02, 0.05, 0.1, 0.2)[attempt])
    finally:
        if os.path.exists(name):
            os.unlink(name)


def write_json(path: Path, value: dict) -> None:
    atomic_write(path, (json.dumps(value, indent=2) + '\n').encode())


def erase(path: Path) -> None:
    """Remove an exact validated entry; never traverse a directory link."""
    if linked(path):
        if path.is_symlink():
            path.unlink()
        else:
            path.rmdir()
    elif path.is_dir():
        # Callers have preflighted this exact managed target and its tree hash.
        if path.absolute() == Path(path.anchor) or len(path.absolute().parts) < 3:
            raise ValueError(f'Refusing directory removal: {path}')
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def create_link(path: Path, source: Path, directory: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name == 'nt' and directory:
        # mklink is a cmd builtin. Arguments are separate, paths are quoted, and
        # command metacharacters are rejected rather than interpolated unsafely.
        if any(ch in str(p) for p in (path, source) for ch in '&|<>^%\r\n"'):
            raise ValueError('Unsupported shell metacharacter in junction path')
        command = f'mklink /J "{path}" "{source}"'
        subprocess.run(['cmd.exe', '/d', '/s', '/c', command], check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    else:
        path.symlink_to(source, target_is_directory=directory)


def capture(path: Path, backup: Path, *, follow: bool) -> dict:
    state = inspect(path)
    result = {'state': state, 'follow': follow, 'backup': str(backup)}
    if state['kind'] == 'link' and not follow:
        result['directory'] = path.is_dir()
    elif path.is_file():
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup)
        os.chmod(backup, 0o600)
    elif path.is_dir():
        shutil.copytree(path, backup)
    return result


def restore(path: Path, snapshot: dict) -> None:
    before = snapshot['state']
    backup = Path(snapshot['backup'])
    if snapshot['follow'] and before['kind'] == 'link':
        if not linked(path) or str(path.resolve()) != before['target']:
            raise ValueError(f'Link target changed during recovery: {path}')
        atomic_write(path, backup.read_bytes())
        return
    erase(path)
    if before['kind'] == 'link':
        create_link(path, Path(before['target']), snapshot.get('directory', False))
    elif before['kind'] == 'file':
        atomic_write(path, backup.read_bytes(), follow=False)
    elif before['kind'] == 'directory':
        shutil.copytree(backup, path)
