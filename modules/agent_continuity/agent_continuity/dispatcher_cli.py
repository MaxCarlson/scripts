"""`llmd` / `llm-dispatcher` CLI for named GUI-agent sessions."""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, TextIO

from . import __version__
from .dispatcher import DispatcherService
from .environment import detect_runtime_kind
from .errors import ContinuityError, ErrorCode

_BOOTSTRAP_PROMPT = "Session initialization only. Reply READY and await further instructions."
_BOOTSTRAP_TIMEOUT_SECONDS = 180


def _json_default(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.asdict(value)
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    return str(value)


def _add_common_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-H", "--home", default=argparse.SUPPRESS, help="Override the shared registry directory.")
    parser.add_argument("-j", "--json", dest="json_output", action="store_true", default=argparse.SUPPRESS,
                        help="Output JSON.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="llmd",
        description="Resume named Codex and AGY sessions associated with local GUI conversation aliases.",
        epilog="Mutations and provider launches are dry-run by default. Pass -a/--apply to proceed.",
    )
    parser.add_argument("-H", "--home", help="Override the shared agent_continuity registry directory.")
    parser.add_argument("-j", "--json", dest="json_output", action="store_true", help="Output JSON.")
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")

    gui = sub.add_parser("gui", help="Register or list local GUI conversation aliases.")
    gui_sub = gui.add_subparsers(dest="gui_command")
    gui_add = gui_sub.add_parser("add", help="Register a local GUI conversation alias.")
    _add_common_options(gui_add)
    gui_add.add_argument("-n", "--name", required=True)
    gui_add.add_argument("-a", "--apply", action="store_true")
    gui_rename = gui_sub.add_parser("rename", help="Rename a local GUI alias while retaining its stable identity and slots.")
    _add_common_options(gui_rename)
    gui_rename.add_argument("-g", "--gui", required=True)
    gui_rename.add_argument("-n", "--name", required=True)
    gui_rename.add_argument("-a", "--apply", action="store_true")
    gui_list = gui_sub.add_parser("list", help="List active GUI conversation aliases.")
    _add_common_options(gui_list)

    slot = sub.add_parser("slot", help="Create and change agent-slot state.")
    slot_sub = slot.add_subparsers(dest="slot_command")
    slot_create = slot_sub.add_parser("create", help="Create a named agent slot.")
    _add_common_options(slot_create)
    slot_create.add_argument("-g", "--gui", required=True)
    slot_create.add_argument("-n", "--agent-name", required=True)
    slot_create.add_argument("-a", "--apply", action="store_true")
    for action in ("disable", "enable", "complete"):
        help_text = {"disable": "Temporarily disable an agent slot.", "enable": "Enable an agent slot.",
                     "complete": "Mark an agent slot's work complete."}[action]
        command = slot_sub.add_parser(action, help=help_text)
        _add_common_options(command)
        command.add_argument("-g", "--gui", required=True)
        command.add_argument("-n", "--agent-name", required=True)
        command.add_argument("-a", "--apply", action="store_true")

    listing = sub.add_parser("list", help="List active named agents for a GUI conversation.")
    _add_common_options(listing)
    listing.add_argument("-g", "--gui", required=True)

    history = sub.add_parser("history", help="Show the full session activation history for one agent.")
    _add_common_options(history)
    history.add_argument("-g", "--gui", required=True)
    history.add_argument("-n", "--agent-name", required=True)

    pending = sub.add_parser("pending", help="List unresolved provider launches for recovery.")
    _add_common_options(pending)
    pending.add_argument("-g", "--gui", help="Filter to one GUI conversation.")

    attach = sub.add_parser("attach", help="Explicitly attach a known native session to a named slot.")
    _add_common_options(attach)
    attach.add_argument("-g", "--gui", required=True)
    attach.add_argument("-n", "--agent-name", required=True)
    attach.add_argument("-p", "--provider", required=True, choices=("agy", "codex"))
    attach.add_argument("-i", "--session-id", required=True)
    attach.add_argument("-e", "--environment")
    attach.add_argument("-C", "--cwd")
    attach.add_argument("-L", "--launch-id")
    attach.add_argument("-a", "--apply", action="store_true")

    for command_name in ("start", "switch"):
        command = sub.add_parser(command_name, help="Start a native session for a named agent slot.")
        _add_common_options(command)
        command.add_argument("-g", "--gui", required=True)
        command.add_argument("-n", "--agent-name", required=True)
        command.add_argument("-p", "--provider", required=True, choices=("agy", "codex"))
        command.add_argument("-e", "--environment", help="Target environment ID or alias (default: local).")
        if command_name == "switch":
            command.add_argument("-r", "--reuse-previous", action="store_true")
        command.add_argument("-C", "--cwd")
        command.add_argument("-a", "--apply", action="store_true")

    cont = sub.add_parser("continue", help="Resume the currently selected native session.")
    _add_common_options(cont)
    cont.add_argument("-g", "--gui", required=True)
    cont.add_argument("-n", "--agent-name", required=True)
    cont.add_argument("-a", "--apply", action="store_true")

    opening = sub.add_parser("open", help="Open active selected sessions through terminal_launcher.")
    _add_common_options(opening)
    opening.add_argument("-g", "--gui", required=True)
    opening.add_argument("-k", "--panes-per-tab", type=int, choices=range(1, 5), default=2)
    opening.add_argument("-t", "--terminal", choices=("windows-terminal",), default="windows-terminal")
    opening.add_argument("-w", "--window", help="Windows Terminal window target.")
    opening.add_argument("-a", "--apply", action="store_true")

    pane = sub.add_parser("pane-run", help=argparse.SUPPRESS)
    _add_common_options(pane)
    pane.add_argument("-s", "--slot-id", required=True)
    pane.add_argument("-L", "--launch-id")

    return parser


def _native_argv(
    dispatcher: DispatcherService,
    provider: str,
    session_id: str | None,
    *,
    environment_id: str,
    cwd: str | None,
) -> list[str]:
    environments = {item.environment_id: item for item in dispatcher.materializer.list_environments()}
    target = environments.get(environment_id)
    if target is None:
        raise ContinuityError(ErrorCode.ENVIRONMENT_NOT_FOUND, f"Native session environment {environment_id!r} is not registered.")
    runtime = detect_runtime_kind()
    provider_args = [provider]
    if session_id:
        provider_args = dispatcher.continuity.adapters[provider].resolve_resume_command(
            session_id, cwd=None if target.runtime_kind == "wsl" else cwd,
            environment_id=environment_id, runtime_kind=target.runtime_kind,
        ).argv
    if target.runtime_kind == "wsl":
        if not target.distro:
            raise ContinuityError(ErrorCode.CROSS_ENVIRONMENT_UNAVAILABLE, "The selected WSL2 session has no recorded distribution identity.")
        if runtime == "windows":
            wsl = shutil.which("wsl.exe") or shutil.which("wsl")
            if not wsl:
                raise ContinuityError(ErrorCode.CROSS_ENVIRONMENT_UNAVAILABLE, "Cannot launch the selected WSL2 environment: wsl.exe is unavailable.")
            argv = [wsl, "--distribution", target.distro]
            if cwd:
                argv.extend(["--cd", cwd])
            return [*argv, "--exec", *provider_args]
        if runtime != "wsl":
            raise ContinuityError(ErrorCode.CROSS_ENVIRONMENT_UNAVAILABLE, f"Cannot launch WSL2 session from runtime {runtime!r}.")
        local = os.environ.get("WSL_DISTRO_NAME")
        if not local or local.casefold() != target.distro.casefold():
            raise ContinuityError(ErrorCode.CROSS_ENVIRONMENT_UNAVAILABLE, "The selected WSL2 session belongs to a different or unknown distribution.")
    elif target.runtime_kind != runtime:
        raise ContinuityError(ErrorCode.CROSS_ENVIRONMENT_UNAVAILABLE, f"Cannot launch {target.runtime_kind} session from runtime {runtime!r}.")
    adapter = dispatcher.continuity.adapters[provider]
    installation = adapter.detect_installation()
    if not installation.installed or not installation.runnable or not installation.executable_path:
        raise ContinuityError(ErrorCode.PROVIDER_UNAVAILABLE, installation.detail or f"{provider} is unavailable.")
    executable = Path(installation.executable_path)
    if executable.suffix.casefold() in {".cmd", ".bat", ".ps1"}:
        script = executable if executable.suffix.casefold() == ".ps1" else executable.with_suffix(".ps1")
        shell = shutil.which("pwsh")
        if script.is_file() and shell:
            return [shell, "-NoLogo", "-NoProfile", "-File", str(script), *provider_args[1:]]
        raise ContinuityError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            f"{provider} resolves to a Windows script wrapper that cannot be launched safely; install PowerShell 7 or a native executable shim.",
        )
    return [installation.executable_path, *provider_args[1:]]


def _bootstrap_native_argv(
    dispatcher: DispatcherService,
    provider: str,
    *,
    environment_id: str,
    cwd: str | None,
) -> list[str]:
    """Build a controlled, machine-readable provider invocation that creates one resumable session."""
    if provider not in {"codex", "agy"}:
        raise ContinuityError(ErrorCode.INVALID_INPUT, f"Unsupported bootstrap provider {provider!r}.")
    argv = _native_argv(dispatcher, provider, None, environment_id=environment_id, cwd=cwd)
    if provider == "codex":
        return [*argv, "exec", "--json", "--sandbox", "read-only", _BOOTSTRAP_PROMPT]
    return [*argv, "--print", _BOOTSTRAP_PROMPT, "--output-format", "json", "--sandbox"]


def _extract_bootstrap_session_id(provider: str, stdout: str) -> str | None:
    """Return an ID only when the provider reports a successful invocation with one unambiguous ID."""
    if provider == "codex":
        session_ids: set[str] = set()
        completed = False
        for line in stdout.splitlines():
            try:
                event = json.loads(line)
            except (TypeError, ValueError):
                continue
            if not isinstance(event, dict):
                continue
            if event.get("type") == "thread.started":
                value = event.get("thread_id")
                if isinstance(value, str) and value.strip():
                    session_ids.add(value.strip())
            elif event.get("type") == "turn.completed":
                completed = True
        if len(session_ids) > 1:
            raise ValueError("Codex bootstrap output reported conflicting session IDs.")
        return next(iter(session_ids)) if completed and session_ids else None
    if provider == "agy":
        try:
            result = json.loads(stdout)
        except (TypeError, ValueError):
            return None
        if not isinstance(result, dict) or result.get("status") != "SUCCESS":
            return None
        value = result.get("conversation_id")
        return value.strip() if isinstance(value, str) and value.strip() else None
    raise ValueError(f"Unsupported bootstrap provider {provider!r}.")


def _bootstrap_attempt_error(dispatcher: DispatcherService, *, slot_id: str, launch_id: str, detail: str) -> None:
    dispatcher.record_process_observation(
        slot_id=slot_id,
        launch_id=launch_id,
        return_code=1,
        outcome="bootstrap_capture_failed",
        detail=detail,
    )


def _run_pane(
    dispatcher: DispatcherService,
    *,
    slot_id: str,
    launch_id: str | None,
    input_stream: TextIO,
    output_stream: TextIO,
) -> int:
    slot = dispatcher.get_slot_by_id(slot_id)
    if launch_id:
        pending = dispatcher.get_pending_launch(launch_id)
        if pending["slot_id"] != slot_id:
            raise ContinuityError(ErrorCode.INVALID_INPUT, "Pending launch belongs to a different agent slot.")
        if pending.get("failure_detail"):
            raise ContinuityError(
                ErrorCode.INVALID_INPUT,
                "This launch already has an incomplete bootstrap attempt. It was not retried automatically; inspect the provider session and attach its exact ID, or create a new launch.",
            )
        provider = pending["provider"]
        environment_id = pending["environment_id"]
        target_environment = next(
            (item for item in dispatcher.materializer.list_environments() if item.environment_id == environment_id),
            None,
        )
        cross_wsl = target_environment and target_environment.runtime_kind == "wsl" and detect_runtime_kind() == "windows"
        cwd = pending.get("cwd") or (None if cross_wsl else dispatcher.current_working_directory(slot))
        session_id = None
    else:
        current = slot["current"]
        if current is None:
            raise ContinuityError(ErrorCode.INVALID_INPUT, "This slot has no selected session; use `llmd start` first.")
        provider = current["provider"]
        session_id = current["native_session_id"]
        environment_id = current["environment_id"]
        native = dispatcher.materializer.get_session(provider, current["environment_id"], session_id)
        cwd = native.cwd_native if native else None
        target_environment = next(
            (item for item in dispatcher.materializer.list_environments() if item.environment_id == environment_id),
            None,
        )
        if target_environment and target_environment.runtime_kind == "wsl" and detect_runtime_kind() == "windows":
            process_cwd = None
        else:
            process_cwd = cwd
    if launch_id:
        process_cwd = None if cross_wsl else cwd
    try:
        if launch_id:
            dispatcher.record_process_observation(
                slot_id=slot_id,
                launch_id=launch_id,
                return_code=0,
                outcome="bootstrap_attempt_started",
                detail="Provider bootstrap started; automatic retry is disabled until this launch is resolved.",
            )
            bootstrap_argv = _bootstrap_native_argv(
                dispatcher, provider, environment_id=environment_id, cwd=cwd
            )
            try:
                bootstrap = subprocess.run(
                    bootstrap_argv,
                    cwd=process_cwd,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=_BOOTSTRAP_TIMEOUT_SECONDS,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                _bootstrap_attempt_error(
                    dispatcher, slot_id=slot_id, launch_id=launch_id,
                    detail=f"{provider} bootstrap exceeded {_BOOTSTRAP_TIMEOUT_SECONDS} seconds; automatic retry is disabled.",
                )
                print(
                    f"{provider} bootstrap timed out. The pending launch was preserved and will not be retried automatically; inspect provider sessions, then use `llmd attach` with the exact ID.",
                    file=output_stream,
                )
                return 124
            except OSError as exc:
                _bootstrap_attempt_error(
                    dispatcher, slot_id=slot_id, launch_id=launch_id,
                    detail=f"Provider bootstrap could not start ({type(exc).__name__}); do not retry automatically.",
                )
                print(
                    f"{provider} bootstrap could not start. This launch was preserved without automatic retry; inspect provider state before attaching or starting again.",
                    file=output_stream,
                )
                return 1
            try:
                captured_session_id = _extract_bootstrap_session_id(provider, bootstrap.stdout or "")
            except ValueError as exc:
                captured_session_id = None
                capture_detail = f"{provider} bootstrap reported conflicting IDs ({exc}); automatic retry is disabled."
            else:
                if bootstrap.returncode != 0:
                    capture_detail = (
                        f"{provider} bootstrap exited with code {bootstrap.returncode}; any captured ID was not accepted and automatic retry is disabled."
                    )
                else:
                    capture_detail = (
                        f"{provider} bootstrap completed without a successful, unambiguous session ID; automatic retry is disabled."
                    )
            if bootstrap.returncode != 0 or not captured_session_id:
                _bootstrap_attempt_error(
                    dispatcher, slot_id=slot_id, launch_id=launch_id, detail=capture_detail
                )
                print(
                    f"{provider} session ID was not safely captured. The pending launch was preserved and will not be retried automatically; inspect provider sessions, then use `llmd attach` with the exact ID.",
                    file=output_stream,
                )
                return bootstrap.returncode or 1

            dispatcher.record_process_observation(
                slot_id=slot_id,
                launch_id=launch_id,
                return_code=0,
                outcome="bootstrap_id_captured",
                detail="Exact native session ID captured from this provider invocation; persisting slot association.",
                native_session_id=captured_session_id,
            )
            other_slot = dispatcher._row(
                """SELECT slot_id FROM agent_slot_activations
                   WHERE provider = ? AND environment_id = ? AND native_session_id = ?
                     AND slot_id != ? LIMIT 1""",
                (provider, environment_id, captured_session_id, slot_id),
            )
            if other_slot:
                _bootstrap_attempt_error(
                    dispatcher, slot_id=slot_id, launch_id=launch_id,
                    detail="Provider bootstrap returned a native ID already associated with another slot; automatic retry is disabled.",
                )
                print(
                    "The captured native session is already assigned to another slot. The current selection was preserved; resolve the conflict explicitly.",
                    file=output_stream,
                )
                return 1

            dispatcher.attach_session(
                gui=slot["gui_alias"],
                name=slot["name"],
                provider=provider,
                session_id=captured_session_id,
                environment_selector=environment_id,
                cwd=cwd,
                launch_id=launch_id,
                apply=True,
                provenance="provider_bootstrap_output",
            )
            session_id = captured_session_id
            launch_id = None
            argv = _native_argv(dispatcher, provider, session_id, environment_id=environment_id, cwd=cwd)
        else:
            argv = _native_argv(dispatcher, provider, session_id, environment_id=environment_id, cwd=cwd)
    except ContinuityError as exc:
        if launch_id:
            pending_now = dispatcher._row(
                "SELECT failure_detail FROM dispatcher_pending_launches WHERE launch_id = ? AND status = 'pending'",
                (launch_id,),
            )
            if pending_now is not None and not pending_now["failure_detail"]:
                dispatcher.mark_launch_failed(launch_id=launch_id, detail=str(exc), apply=True)
        raise
    print(f"Launching {slot['name']}: {provider} {session_id or '(new session)'}", file=output_stream)
    try:
        session_lock = contextlib.nullcontext()
        if session_id:
            lock_key = hashlib.sha256(f"{provider}\0{environment_id}\0{session_id}".encode()).hexdigest()[:24]
            session_lock = _session_runtime_lock(dispatcher, f"session-{lock_key}.lock")
        with session_lock:
            result = subprocess.run(argv, cwd=process_cwd, check=False)
    except OSError as exc:
        if launch_id:
            dispatcher.mark_launch_failed(launch_id=launch_id, detail=str(exc), apply=True)
        elif session_id:
            dispatcher.record_process_observation(slot_id=slot_id, launch_id=None, return_code=-1, outcome="spawn_failed")
        raise ContinuityError(ErrorCode.PROVIDER_UNAVAILABLE, f"Failed to launch {provider}: {exc}") from exc
    dispatcher.record_process_observation(
        slot_id=slot_id, launch_id=launch_id, return_code=result.returncode,
        outcome="normal_exit" if result.returncode == 0 else "nonzero_exit",
    )
    if result.returncode != 0:
        if launch_id:
            dispatcher.mark_launch_failed(launch_id=launch_id, detail=f"provider exited with {result.returncode}", apply=True)
        print(f"{slot['name']} exited with code {result.returncode}; slot and current session remain unchanged.", file=output_stream)
        return result.returncode
    print(f"\n{slot['name']} has exited.\n[1] Keep active (default)\n[2] Mark completed\n[3] Mark inactive", file=output_stream)
    try:
        choice = input_stream.readline().strip()
    except (EOFError, OSError):
        choice = ""
    state = {"2": "completed", "3": "inactive"}.get(choice, "active")
    if state != "active":
        dispatcher.set_slot_state(gui=slot["gui_alias"], name=slot["name"], state=state, apply=True)
    return 0


def _session_runtime_lock(dispatcher: DispatcherService, name: str):
    from .dispatcher import _mutation_lock

    return _mutation_lock(dispatcher.home_dir, lock_name=name)


def _open(dispatcher: DispatcherService, args: argparse.Namespace) -> dict[str, Any]:
    if args.terminal != "windows-terminal":
        raise ContinuityError(ErrorCode.INVALID_INPUT, "Only the windows-terminal backend is currently supported.")
    request = dispatcher.open_request(gui=args.gui)
    try:
        from terminal_launcher import PaneSpec, WindowsTerminalBackend, group_panes
    except ModuleNotFoundError as exc:
        if exc.name != "terminal_launcher":
            raise
        return {
            "action": "open",
            "applied": False,
            "summary": "Terminal launch plan prepared; install or integrate the terminal_launcher package to execute it.",
            "terminal_launcher_available": False,
            "request": request,
            "panes_per_tab": args.panes_per_tab,
            "target_window": args.window,
        }
    panes = [
        PaneSpec(title=item["title"], argv=tuple(item["argv"]), cwd=item.get("cwd"))
        for item in request["panes"]
    ]
    plan = group_panes(panes, panes_per_tab=args.panes_per_tab, target_window=args.window)
    backend = WindowsTerminalBackend()
    preview = backend.preview(plan)
    result = {
        "action": "open",
        "applied": bool(args.apply),
        "request": request,
        "preview": preview,
        "panes_per_tab": args.panes_per_tab,
        "target_window": args.window,
    }
    if args.apply:
        result["launch"] = backend.launch(plan)
    else:
        result["summary"] = "Dry-run: pass -a/--apply to launch the selected sessions."
    return result


def dispatch(args: argparse.Namespace, parser: argparse.ArgumentParser, *, input_stream: TextIO, output_stream: TextIO) -> int:
    if args.command is None:
        if not (input_stream.isatty() and output_stream.isatty()):
            parser.print_help(file=output_stream)
            return 2
        from .interactive import run_interactive

        return run_interactive(DispatcherService(home_dir=args.home), input_stream=input_stream, output_stream=output_stream)

    dispatcher = DispatcherService(home_dir=args.home)
    if args.command == "gui":
        if args.gui_command == "add":
            result = dispatcher.create_gui(args.name, apply=args.apply)
        elif args.gui_command == "rename":
            result = dispatcher.rename_gui(gui=args.gui, alias=args.name, apply=args.apply)
        elif args.gui_command == "list":
            result = {"action": "gui-list", "conversations": dispatcher.list_guis()}
        else:
            parser.parse_args(["gui", "--help"])
            return 2
    elif args.command == "slot":
        if args.slot_command == "create":
            result = dispatcher.create_slot(gui=args.gui, name=args.agent_name, apply=args.apply)
        elif args.slot_command in {"disable", "enable", "complete"}:
            state = {"disable": "inactive", "enable": "active", "complete": "completed"}[args.slot_command]
            result = dispatcher.set_slot_state(gui=args.gui, name=args.agent_name, state=state, apply=args.apply)
        else:
            parser.parse_args(["slot", "--help"])
            return 2
    elif args.command == "list":
        result = {"action": "list", "gui": args.gui, "slots": dispatcher.list_slots(gui=args.gui)}
    elif args.command == "history":
        result = {"action": "history", "slot": dispatcher.get_slot(gui=args.gui, name=args.agent_name)}
    elif args.command == "pending":
        result = {"action": "pending", "launches": dispatcher.list_pending_launches(gui=args.gui)}
    elif args.command == "attach":
        result = dispatcher.attach_session(gui=args.gui, name=args.agent_name, provider=args.provider,
                                           session_id=args.session_id, environment_selector=args.environment,
                                           cwd=args.cwd, launch_id=args.launch_id, apply=args.apply)
    elif args.command in {"start", "switch"}:
        if args.command == "switch" and args.reuse_previous:
            old = dispatcher.latest_session_for_provider(gui=args.gui, name=args.agent_name, provider=args.provider)
            if old is None:
                raise ContinuityError(ErrorCode.INVALID_INPUT, f"No previous {args.provider} session exists in this slot.")
            result = dispatcher.attach_session(gui=args.gui, name=args.agent_name, provider=args.provider,
                                               session_id=old["native_session_id"],
                                               environment_selector=old["environment_id"], apply=args.apply,
                                               provenance="dispatcher_reuse")
            if args.apply:
                slot = dispatcher.get_slot(gui=args.gui, name=args.agent_name)
                return _run_pane(dispatcher, slot_id=slot["slot_id"], launch_id=None,
                                 input_stream=input_stream, output_stream=output_stream)
        else:
            result = dispatcher.begin_launch(gui=args.gui, name=args.agent_name, provider=args.provider,
                                             cwd=args.cwd, environment_selector=args.environment, apply=args.apply)
            if args.apply:
                return _run_pane(dispatcher, slot_id=result["details"]["slot_id"],
                                 launch_id=result["details"]["launch_id"],
                                 input_stream=input_stream, output_stream=output_stream)
    elif args.command == "continue":
        slot = dispatcher.get_slot(gui=args.gui, name=args.agent_name)
        if slot["current"] is None:
            raise ContinuityError(ErrorCode.INVALID_INPUT, "This slot has no selected session; use `llmd start`.")
        result = {"action": "continue", "applied": False, "slot": slot,
                  "summary": "Dry-run: pass -a/--apply to resume the current session."}
        if args.apply:
            return _run_pane(dispatcher, slot_id=slot["slot_id"], launch_id=None,
                             input_stream=input_stream, output_stream=output_stream)
    elif args.command == "open":
        result = _open(dispatcher, args)
        if args.apply and result.get("terminal_launcher_available") is False:
            print(json.dumps(result, indent=2, ensure_ascii=False, default=_json_default) if args.json_output else result["summary"], file=output_stream)
            return 2
    elif args.command == "pane-run":
        return _run_pane(dispatcher, slot_id=args.slot_id, launch_id=args.launch_id,
                         input_stream=input_stream, output_stream=output_stream)
    else:
        parser.error("command required")
        return 2

    json_mode = bool(args.json_output)
    if json_mode:
        print(json.dumps(result, indent=2, ensure_ascii=False, default=_json_default), file=output_stream)
    else:
        if "summary" in result:
            print(result["summary"], file=output_stream)
        for slot_row in result.get("slots", []):
            provider = slot_row.get("current_provider") or slot_row.get("pending_provider") or "unresolved"
            session = slot_row.get("current_session_id") or ("pending" if slot_row.get("pending_launch_id") else "unresolved")
            print(f"{slot_row['name']}\t{provider}\t{session}", file=output_stream)
        if result.get("unresolved"):
            for item in result["unresolved"]:
                print(f"Unresolved: {item['agent_name']}: {item['reason']}", file=output_stream)
        if result.get("action") == "history":
            for index, item in enumerate(result["slot"]["history"], 1):
                print(f"{index}. {item['provider']} {item['native_session_id']} [{item['environment_id']}] ({item['provenance']})", file=output_stream)
        if result.get("action") == "pending":
            for launch in result["launches"]:
                captured_id = launch.get("captured_session_id") or "unresolved"
                print(
                    f"{launch['launch_id']}\t{launch.get('gui_alias', '')}\t{launch.get('agent_name', '')}\t"
                    f"{launch['provider']}\t{launch['environment_id']}\t{captured_id}",
                    file=output_stream,
                )
                if launch.get("failure_detail"):
                    print(f"  Recovery: {launch['failure_detail']}", file=output_stream)
        if result.get("action") == "open":
            print(json.dumps(result, indent=2, ensure_ascii=False, default=_json_default), file=output_stream)
        if not result.get("applied", True) and result.get("events"):
            print("Preview only. Pass -a / --apply to persist this operation.", file=output_stream)
    launch = result.get("launch") if result.get("action") == "open" and args.apply else None
    if getattr(getattr(launch, "status", None), "value", None) == "failed":
        return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        return dispatch(args, parser, input_stream=sys.stdin, output_stream=sys.stdout)
    except ContinuityError as exc:
        if bool(getattr(args, "json_output", False)):
            print(json.dumps({"ok": False, "error": exc.to_dict()}), file=sys.stdout)
        else:
            print(f"Error {exc}", file=sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:
        print("Cancelled.", file=sys.stderr)
        return 130
    except Exception as exc:  # pragma: no cover - top-level CLI boundary
        if bool(getattr(args, "json_output", False)):
            print(json.dumps({"ok": False, "error": {"message": str(exc)}}), file=sys.stdout)
        else:
            print(f"Unexpected error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
