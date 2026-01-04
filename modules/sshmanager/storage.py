"""
Storage utilities for sshmanager.

This module is responsible for reading and writing host configuration data
from an encrypted JSON file located under the user's home directory.

The file ``hosts.json.enc`` contains a list of dictionaries, each
describing a host.  Each dictionary may include keys such as
``alias``, ``host``, ``user``, ``port`` and ``identity_file``.  The
exact structure is not enforced by the storage layer; validation is
performed by the CLI before writing.

Encryption/decryption is performed using Fernet, which guarantees that
an encrypted message cannot be modified or read without the key【470516398484308†L60-L80】.  A
32‑byte base64 encoded key must be supplied via the ``SSHMANAGER_KEY``
environment variable or passed explicitly when calling ``load_hosts``
or ``save_hosts``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List, Dict, Any

from cryptography.fernet import Fernet, InvalidToken

CONFIG_DIRNAME = ".sshmanager"
DATA_FILENAME = "hosts.json.enc"


def get_config_dir() -> Path:
    """Return the directory used to store sshmanager data and ensure it exists.

    The configuration directory resides under the user's home directory in
    ``~/.sshmanager``.  If the directory does not exist it is created.

    Returns
    -------
    pathlib.Path
        Path object pointing to the configuration directory.
    """
    home = Path.home()
    cfg = home / CONFIG_DIRNAME
    cfg.mkdir(parents=True, exist_ok=True)
    return cfg


def _get_data_path() -> Path:
    """Return the path to the encrypted hosts file."""
    return get_config_dir() / DATA_FILENAME


def _get_key(key: str | bytes | None = None) -> bytes:
    """Retrieve the encryption key from a parameter or environment variable.

    The key must be a base64‑encoded 32‑byte value.  If ``key`` is
    ``None`` then the value is read from the ``SSHMANAGER_KEY``
    environment variable.  If the key is missing or empty a
    ``RuntimeError`` is raised.  See the cryptography documentation for
    more information on generating Fernet keys and the importance of
    keeping them secret【470516398484308†L60-L80】.

    Parameters
    ----------
    key : str | bytes | None
        A base64 encoded key or ``None`` to read from the environment.

    Returns
    -------
    bytes
        The raw key bytes to use with ``Fernet``.
    """
    if key is None:
        key = os.environ.get("SSHMANAGER_KEY")
        if not key:
            raise RuntimeError(
                "Missing encryption key. Set the SSHMANAGER_KEY environment variable or pass a key to the function."
            )
    if isinstance(key, bytes):
        return key
    return key.encode("utf-8")


def load_hosts(key: str | bytes | None = None) -> List[Dict[str, Any]]:
    """Load the list of hosts from the encrypted file.

    If the encrypted file does not exist, an empty list is returned.  If
    decryption fails due to an invalid key or corrupted data, a
    ``RuntimeError`` is raised.

    Parameters
    ----------
    key : str | bytes | None
        Base64 encoded key used to decrypt the file.  If None, the
        ``SSHMANAGER_KEY`` environment variable is used.

    Returns
    -------
    list of dict
        A list of host definitions.
    """
    path = _get_data_path()
    if not path.exists():
        return []
    raw = path.read_bytes()
    f = Fernet(_get_key(key))
    try:
        decrypted = f.decrypt(raw)
    except InvalidToken as exc:
        raise RuntimeError("Failed to decrypt hosts file: invalid key or corrupted data") from exc
    try:
        return json.loads(decrypted.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError("Hosts file contains invalid JSON") from exc


def save_hosts(hosts: List[Dict[str, Any]], key: str | bytes | None = None) -> None:
    """Save the list of hosts to an encrypted file.

    Parameters
    ----------
    hosts : list of dict
        A list of host definitions to persist.
    key : str | bytes | None
        Base64 encoded key used to encrypt the data.  If None, the
        ``SSHMANAGER_KEY`` environment variable is used.

    Raises
    ------
    RuntimeError
        If the encryption key is missing.
    """
    data = json.dumps(hosts, indent=2, sort_keys=True).encode("utf-8")
    f = Fernet(_get_key(key))
    token = f.encrypt(data)
    path = _get_data_path()
    path.write_bytes(token)