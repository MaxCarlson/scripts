"""Top level package for sshmanager.

This module provides a simple CLI for managing SSH connection details and
making it easy to connect to multiple hosts.  Host definitions are stored
locally in an encrypted file so that sensitive information such as
usernames or port numbers are not exposed in plain text.  The encryption
is performed using the ``cryptography`` package's Fernet implementation,
which provides authenticated symmetric encryption.  For details on Fernet
and how to generate keys see the cryptography documentation【470516398484308†L60-L80】.

The CLI is exposed via the ``sshmanager`` console script defined in
``pyproject.toml``.  See ``sshmanager.cli`` for details on available
commands.
"""

__all__ = ["cli"]

from . import cli  # noqa: F401