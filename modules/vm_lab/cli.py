"""Command-line interface for vm and vm-lab."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from vm_lab import __version__
from vm_lab.backend import BackendAdapter
from vm_lab.commands import register_commands
from vm_lab.exceptions import EXIT_INPUT_ERROR, EXIT_SUCCESS, VmLabError
from vm_lab.results import format_human_output, redact_sensitive


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

    register_commands(sub)
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
            elif json_mode and res.data is not None:
                _emit_json(res.data)
            if res.stderr:
                sys.stderr.write(res.stderr)
            return res.exit_code
        except VmLabError as exc:
            print(f"vm_lab error: {exc}", file=sys.stderr)
            return exc.exit_code

    tail_args: list[str] = []
    if "--" in raw_args:
        split_idx = raw_args.index("--")
        parse_args_list = raw_args[:split_idx]
        tail_args = raw_args[split_idx + 1 :]
    else:
        parse_args_list = raw_args

    parser = build_parser()
    ns = parser.parse_args(parse_args_list)
    if tail_args:
        existing = list(getattr(ns, "exec_args", []) or [])
        ns.exec_args = existing + tail_args

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

    builder = getattr(ns, "_builder", None)
    if builder is None:
        parser.print_help()
        return EXIT_INPUT_ERROR

    be = adapter or BackendAdapter()
    try:
        try:
            ps_args, interactive = builder(ns)
        except ValueError as exc:
            if getattr(ns, "json", False):
                _emit_json({"status": "ERROR", "reason_code": "invalid_arguments", "error": str(exc)})
            else:
                print(f"vm_lab error: {exc}", file=sys.stderr)
            return EXIT_INPUT_ERROR

        script_name = getattr(ns, "_script_name", "Invoke-VmLab.ps1")
        user_json = bool(getattr(ns, "json", False))
        is_wizard = getattr(ns, "command", None) == "wizard"

        if is_wizard:
            res = be.invoke(ps_args, script_name=script_name, json_mode=False, interactive=True)
            if res.stdout:
                sys.stdout.write(res.stdout)
                if not res.stdout.endswith("\n"):
                    sys.stdout.write("\n")
            elif json_mode and res.data is not None:
                _emit_json(res.data)
            if res.stderr:
                sys.stderr.write(res.stderr)
            return res.exit_code

        # Request structured JSON internally for all non-wizard subcommands so status & exit codes are classified accurately
        invoke_args = list(ps_args)
        if script_name == "Invoke-VmLab.ps1" and not any(a in {"-j", "-Json"} for a in invoke_args):
            invoke_args.append("-Json")

        res = be.invoke(invoke_args, script_name=script_name, json_mode=True, interactive=interactive)
        if user_json:
            if res.stdout.strip():
                sys.stdout.write(res.stdout)
                if not res.stdout.endswith("\n"):
                    sys.stdout.write("\n")
            elif res.data is not None:
                _emit_json(res.data)
        else:
            rendered = format_human_output(res.data) if res.data is not None else res.stdout.rstrip("\r\n")
            if rendered:
                print(rendered)
        if res.stderr:
            sys.stderr.write(res.stderr)
        return res.exit_code
    except VmLabError as exc:
        msg = redact_sensitive(str(exc))
        if getattr(ns, "json", False):
            _emit_json({"status": "ERROR", "reason_code": "backend_execution_error", "error": msg})
        else:
            print(f"vm_lab error: {msg}", file=sys.stderr)
        return exc.exit_code
