"""Command-line interface for vm and vm-lab."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from vm_lab import __version__
from vm_lab.backend import BackendAdapter
from vm_lab.exceptions import EXIT_INPUT_ERROR, EXIT_SUCCESS, VmLabError


def _emit_json(data: object) -> None:
    print(json.dumps(data, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vm",
        description="Disposable Windows Hyper-V lab manager and workflow automation CLI (aliases: vm, vm-lab).",
    )
    parser.add_argument("--version", action="store_true", help="Print vm_lab version and exit.")

    sub = parser.add_subparsers(dest="command", metavar="<command>")

    p_ver = sub.add_parser("version", help="Show vm_lab version and backend path.")
    p_ver.add_argument("-j", "--json", action="store_true", help="Emit JSON output.")

    p_list = sub.add_parser("list", help="List Hyper-V VMs.")
    p_list.add_argument("-oo", "--owned-only", action="store_true", help="Show only vm_lab-owned VMs.")
    p_list.add_argument("-mr", "--manifest-root", help="Override vm_lab ownership manifest root.")
    p_list.add_argument("-j", "--json", action="store_true", help="Emit JSON output.")

    p_doc = sub.add_parser("doctor", help="Check host Hyper-V and stale lock health.")
    p_doc.add_argument("-j", "--json", action="store_true", help="Emit JSON output.")

    return parser


def main(argv: Sequence[str] | None = None, *, adapter: BackendAdapter | None = None) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)

    # Preserve legacy PowerShell `-o <operation> ...` compatibility
    if raw_args and raw_args[0] in {"-o", "-Operation"}:
        be = adapter or BackendAdapter()
        try:
            json_mode = any(a in {"-j", "-Json"} for a in raw_args)
            interactive = any(a in {"wizard", "-PromptCredential"} for a in raw_args)
            res = be.invoke(raw_args, json_mode=json_mode, interactive=interactive)
            if res.stdout:
                sys.stdout.write(res.stdout)
                if not res.stdout.endswith("\n"):
                    sys.stdout.write("\n")
            if res.stderr:
                sys.stderr.write(res.stderr)
            return res.exit_code
        except VmLabError as exc:
            print(f"vm_lab error: {exc}", file=sys.stderr)
            return exc.exit_code

    parser = build_parser()
    ns = parser.parse_args(raw_args)

    if ns.version:
        print(f"vm_lab {__version__}")
        return EXIT_SUCCESS

    if not ns.command:
        parser.print_help()
        return EXIT_SUCCESS

    if ns.command == "version":
        be = adapter or BackendAdapter()
        try:
            backend_path = str(be.backend_root)
        except VmLabError:
            backend_path = None
        info = {"package": "vm_lab", "version": __version__, "backend_root": backend_path}
        if ns.json:
            _emit_json(info)
        else:
            print(f"vm_lab {__version__} (backend: {backend_path or 'unavailable'})")
        return EXIT_SUCCESS

    be = adapter or BackendAdapter()
    try:
        if ns.command == "list":
            ps_args = ["-o", "list"]
            if ns.owned_only:
                ps_args.append("-OwnedOnly")
            if ns.manifest_root:
                ps_args.extend(["-ManifestRoot", ns.manifest_root])
            if ns.json:
                ps_args.append("-Json")
            res = be.invoke(ps_args, json_mode=ns.json)
        elif ns.command == "doctor":
            ps_args = ["-o", "doctor"]
            if ns.json:
                ps_args.append("-Json")
            res = be.invoke(ps_args, json_mode=ns.json)
        else:
            parser.print_help()
            return EXIT_INPUT_ERROR

        if res.stdout:
            sys.stdout.write(res.stdout)
            if not res.stdout.endswith("\n"):
                sys.stdout.write("\n")
        if res.stderr:
            sys.stderr.write(res.stderr)
        return res.exit_code
    except VmLabError as exc:
        if getattr(ns, "json", False):
            _emit_json({"status": "error", "error": str(exc)})
        else:
            print(f"vm_lab error: {exc}", file=sys.stderr)
        return exc.exit_code
