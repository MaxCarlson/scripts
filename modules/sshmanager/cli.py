"""
Command line interface for sshmanager.

This module defines a CLI with subcommands for managing SSH host
definitions and connecting to hosts.  Host definitions are stored
encrypted using Fernet keys so they can safely be kept in a version
control repository.  Users must supply a base64 encoded key via the
``SSHMANAGER_KEY`` environment variable when performing operations
that read or write host data【470516398484308†L60-L80】.

Available commands::

    sshmanager generate-key        # print a new random encryption key
    sshmanager add --host <host> --user <user> [--port <port>] [--alias <alias>] [--identity-file <path>]
    sshmanager list                # list all known hosts
    sshmanager remove <alias>      # remove a host definition by alias
    sshmanager connect <alias>     # connect to a host using ssh

The ``connect`` command delegates to the system's ``ssh`` executable.
If the host definition contains an ``identity_file`` it is passed via
the ``-i`` flag.  Otherwise the default identity files configured in
the user's SSH config are used.
"""

from __future__ import annotations

import argparse
import os
import subprocess
from typing import List, Dict, Any

from .storage import load_hosts, save_hosts, get_config_dir


def _ensure_key() -> bytes:
    """Ensure that the encryption key is available in the environment.

    Returns
    -------
    bytes
        The raw key bytes.  Raises a RuntimeError if ``SSHMANAGER_KEY`` is
        not set.
    """
    key = os.environ.get("SSHMANAGER_KEY")
    if not key:
        raise RuntimeError(
            "Missing SSHMANAGER_KEY environment variable. Use 'sshmanager generate-key' to generate a key and set it before running commands."
        )
    return key.encode("utf-8")


def generate_key(args: argparse.Namespace) -> None:
    """Generate and print a new random Fernet key.

    The cryptography documentation explains that the key should be kept
    secret and stored securely because anyone with the key can decrypt
    messages【470516398484308†L60-L80】.  This command prints a fresh key to stdout and
    does not store it anywhere.
    """
    from cryptography.fernet import Fernet

    key = Fernet.generate_key()
    # Print to stdout so that the user can copy it.  Do not write newline to avoid trailing whitespace issues.
    print(key.decode("utf-8"))


def list_hosts(args: argparse.Namespace) -> None:
    """List all host definitions stored in the encrypted file.

    This command reads the hosts file, decrypts it using the key from
    the environment and prints a simple table of hosts.
    """
    # Ensure key exists; will raise if missing.
    _ensure_key()
    hosts = load_hosts()
    if not hosts:
        print("No hosts have been added yet.")
        return
    # Print a table header
    cols = ["Alias", "User", "Host", "Port", "Identity"]
    widths = [max(len(str(row.get("alias", ""))) for row in hosts + [{"alias": cols[0]}]),
              max(len(str(row.get("user", ""))) for row in hosts + [{"user": cols[1]}]),
              max(len(str(row.get("host", ""))) for row in hosts + [{"host": cols[2]}]),
              max(len(str(row.get("port", ""))) for row in hosts + [{"port": cols[3]}]),
              max(len(str(row.get("identity_file", ""))) for row in hosts + [{"identity_file": cols[4]}])]
    header = "  ".join(f"{c:{w}}" for c, w in zip(cols, widths))
    print(header)
    print("  ".join("-" * w for w in widths))
    for row in hosts:
        print(
            "  ".join(
                f"{str(row.get(key.lower().replace(' ', '_'), '')):{width}}"
                for key, width in zip(cols, widths)
            )
        )


def add_host(args: argparse.Namespace) -> None:
    """Add a new host definition.

    This command requires that the encryption key be present.  It reads
    any existing host definitions, appends the new one (or replaces an
    existing entry with the same alias) and writes the result back to the
    encrypted file.
    """
    _ensure_key()
    # Compose host entry
    host_entry: Dict[str, Any] = {
        "alias": args.alias or args.host,
        "host": args.host,
        "user": args.user,
        "port": args.port or 22,
    }
    if args.identity_file:
        host_entry["identity_file"] = os.path.expanduser(args.identity_file)
    # Read existing hosts
    hosts: List[Dict[str, Any]] = load_hosts()
    # Remove any existing entry with the same alias
    hosts = [h for h in hosts if h.get("alias") != host_entry["alias"]]
    hosts.append(host_entry)
    save_hosts(hosts)
    print(f"Added host '{host_entry['alias']}' ({host_entry['user']}@{host_entry['host']}:{host_entry['port']}).")


def remove_host(args: argparse.Namespace) -> None:
    """Remove a host definition by alias."""
    _ensure_key()
    hosts = load_hosts()
    new_hosts = [h for h in hosts if h.get("alias") != args.alias]
    if len(new_hosts) == len(hosts):
        print(f"No host with alias '{args.alias}' found.")
        return
    save_hosts(new_hosts)
    print(f"Removed host '{args.alias}'.")


def connect_host(args: argparse.Namespace) -> None:
    """Connect to a host using the system ssh command.

    Looks up the host definition by alias and then executes ``ssh`` with
    the appropriate arguments.  If ``identity_file`` is present it is
    passed via ``-i``.  Any additional arguments after the alias are
    forwarded to ssh verbatim.
    """
    _ensure_key()
    hosts = load_hosts()
    entry = next((h for h in hosts if h.get("alias") == args.alias), None)
    if not entry:
        raise SystemExit(f"Unknown host alias '{args.alias}'. Use 'sshmanager list' to see available hosts.")
    cmd = ["ssh", f"{entry['user']}@{entry['host']}", "-p", str(entry.get("port", 22))]
    identity_file = entry.get("identity_file")
    if identity_file:
        cmd.extend(["-i", identity_file])
    # Forward any additional arguments after alias directly to ssh.  This
    # allows users to specify remote commands such as 'sshmanager connect myhost ls -l'.
    cmd.extend(args.ssh_args)
    # Execute the ssh command.  We call subprocess.run without
    # capturing output so the user sees the usual ssh prompts.
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode)


def get_arg_parser() -> argparse.ArgumentParser:
    """Construct and return the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="sshmanager",
        description="A simple SSH connection manager with encrypted host definitions.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # generate-key
    parser_gen = subparsers.add_parser(
        "generate-key", help="Generate and print a new Fernet encryption key."
    )
    parser_gen.set_defaults(func=generate_key)

    # add
    parser_add = subparsers.add_parser("add", help="Add a new host definition.")
    parser_add.add_argument("--host", required=True, help="Hostname or IP address of the remote host.")
    parser_add.add_argument(
        "--user",
        required=True,
        help="Username for SSH login.",
    )
    parser_add.add_argument(
        "--port", type=int, default=22, help="SSH port number (default: 22)."
    )
    parser_add.add_argument(
        "--alias",
        help="Optional alias to identify the host (defaults to the host itself).",
    )
    parser_add.add_argument(
        "--identity-file",
        help="Path to a private key file to use when connecting to this host.",
    )
    parser_add.set_defaults(func=add_host)

    # list
    parser_list = subparsers.add_parser("list", help="List all stored hosts.")
    parser_list.set_defaults(func=list_hosts)

    # remove
    parser_rm = subparsers.add_parser("remove", help="Remove a host by alias.")
    parser_rm.add_argument("alias", help="Alias of the host to remove.")
    parser_rm.set_defaults(func=remove_host)

    # connect
    parser_conn = subparsers.add_parser("connect", help="Connect to a host by alias using ssh.")
    parser_conn.add_argument("alias", help="Alias of the host to connect to.")
    parser_conn.add_argument(
        "ssh_args",
        nargs=argparse.REMAINDER,
        help="Additional arguments to pass directly to ssh (e.g., remote command).",
    )
    parser_conn.set_defaults(func=connect_host)

    return parser


def main(argv: List[str] | None = None) -> None:
    """Entry point for the sshmanager CLI.

    Parses command-line arguments and dispatches to the appropriate
    function.  If an exception escapes from a subcommand it is
    re-raised as a ``SystemExit`` with non‑zero exit code so the
    process fails cleanly.
    """
    parser = get_arg_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except RuntimeError as exc:
        # Print the message and exit with an error code
        parser.error(str(exc))


if __name__ == "__main__":  # pragma: no cover
    main()