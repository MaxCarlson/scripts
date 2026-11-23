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
        epilog="Register applies by default; legacy mutations and launches require -a/--apply.",
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

    listing = sub.add_parser("list", help="List conversations and their agents.")
    _add_common_options(listing)
    listing.add_argument("gui_pos", nargs="?")
    listing.add_argument("-g", "--gui")
    listing.add_argument("-l", "--limit", type=int, help="Maximum records (default 10, or unlimited with --all).")
    listing.add_argument("-A", "--all", action="store_true")
    listing.add_argument("-c", "--color", choices=("auto", "always", "never"), default="auto")

    register = sub.add_parser("register", help="Register a GUI, agent, and optional existing session.")
    _add_common_options(register)
    register.add_argument("gui_pos", nargs="?")
    register.add_argument("agent_pos", nargs="?")
    register.add_argument("-g", "--gui")
    register.add_argument("-n", "--agent-name")
    register.add_argument("-p", "--provider", choices=("agy", "codex"))
    register.add_argument("-i", "--session-id")
    register.add_argument("-d", "--dry-run", action="store_true")
    register.add_argument("-a", "--apply", action="store_true", help="Compatibility option; registration applies by default.")
    register.add_argument("-s", "--select", action="store_true", help="Select a different session, preserving history.")

    history = sub.add_parser("history", help="Show the full session activation history for one agent.")
    _add_common_options(history)
    history.add_argument("-g", "--gui", required=True)
    history.add_argument("-n", "--agent-name", required=True)

    pending = sub.add_parser("pending", help="List unresolved provider launches for recovery.")
    _add_common_options(pending)
    pending.add_argument("-g", "--gui", help="Filter to one GUI conversation.")

    doctor = sub.add_parser("doctor", help="Read-only registry, launch, and runtime diagnostics.")
    _add_common_options(doctor)
    doctor.add_argument("-g", "--gui")
    doctor.add_argument("-n", "--agent-name")

    recover = sub.add_parser("recover", help="Reconcile a captured pending session association.")
    _add_common_options(recover)
    recover.add_argument("-g", "--gui", required=True)
    recover.add_argument("-n", "--agent-name", required=True)
    recover.add_argument("-a", "--apply", action="store_true", help="Apply the metadata-only recovery.")

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
        if command_name == "start":
            command.add_argument("gui_pos", nargs="?")
            command.add_argument("agent_pos", nargs="?")
        command.add_argument("-g", "--gui", required=command_name != "start")
        command.add_argument("-n", "--agent-name", required=command_name != "start")
        command.add_argument("-p", "--provider", required=True, choices=("agy", "codex"))
        command.add_argument("-e", "--environment", help="Target environment ID or alias (default: local).")
        if command_name == "switch":
            command.add_argument("-r", "--reuse-previous", action="store_true")
        command.add_argument("-C", "--cwd")
        command.add_argument("-a", "--apply", action="store_true")
        if command_name == "start":
            command.add_argument("-N", "--new", action="store_true", help="Explicitly authorize a new native conversation.")

    cont = sub.add_parser("continue", help="Resume the currently selected native session.")
    _add_common_options(cont)
    cont.add_argument("gui_pos", nargs="?")
    cont.add_argument("agent_pos", nargs="?")
    cont.add_argument("-g", "--gui")
    cont.add_argument("-n", "--agent-name", "--name")
    cont.add_argument("-a", "--apply", action="store_true")
    cont.add_argument("-A", "--all", action="store_true", help="Include completed agents in the interactive picker.")
    cont.add_argument("-p", "--provider", choices=("agy", "codex"), help="Select the most recently activated matching historical provider session.")
    cont.add_argument("-i", "--session-id", help="Select this exact session from the agent's existing history.")
    cont.add_argument("-R", "--reactivate", action="store_true", help="Explicitly reactivate an inactive agent before resuming.")

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
    bootstrap_completed = False
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

            bootstrap_completed = True
            try:
                dispatcher.record_process_observation(
                    slot_id=slot_id,
                    launch_id=launch_id,
                    return_code=0,
                    outcome="bootstrap_id_captured",
                detail="Exact native session ID captured from this provider invocation; persisting slot association.",
                    native_session_id=captured_session_id,
                )
            except ContinuityError as exc:
                print(f"Bootstrap created session {captured_session_id}, but LLMD could not persist its ID. Do not retry the launch; inspect provider state and use `llmd attach` with this exact ID if verified.", file=output_stream)
                raise ContinuityError(ErrorCode.METADATA_INACCESSIBLE,
                    f"Provider bootstrap succeeded with session {captured_session_id}, but its metadata was not persisted; do not relaunch blindly. Run `llmd doctor`.") from exc
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
        if launch_id and not bootstrap_completed:
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
            session_lock = _session_runtime_lock(dispatcher, f"session-{lock_key}.lock", blocking=False)
        with session_lock:
            result = subprocess.run(argv, cwd=process_cwd, check=False)
    except OSError as exc:
        if launch_id:
            dispatcher.mark_launch_failed(launch_id=launch_id, detail=str(exc), apply=True)
        elif session_id:
            dispatcher.record_process_observation(slot_id=slot_id, launch_id=None, return_code=-1, outcome="spawn_failed")
        raise ContinuityError(ErrorCode.PROVIDER_UNAVAILABLE, f"Failed to launch {provider}: {exc}") from exc
    try:
        dispatcher.record_process_observation(
            slot_id=slot_id, launch_id=launch_id, return_code=result.returncode,
            outcome="normal_exit" if result.returncode == 0 else "nonzero_exit",
        )
    except ContinuityError as exc:
        raise ContinuityError(ErrorCode.METADATA_INACCESSIBLE,
            f"{provider} process exited with code {result.returncode}, but LLMD could not record the result. Do not relaunch blindly; run `llmd doctor` and inspect provider state.") from exc
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


def _session_runtime_lock(dispatcher: DispatcherService, name: str, *, blocking: bool = True):
    from .dispatcher import _mutation_lock

    return _mutation_lock(dispatcher.home_dir, lock_name=name, blocking=blocking)


def _try_session_runtime_lock(dispatcher: DispatcherService, name: str) -> bool:
    path = dispatcher.home_dir / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        try:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            return False
        except OSError:
            return True


def _session_in_use(dispatcher: DispatcherService, provider: str, environment_id: str, session_id: str) -> bool:
    key = hashlib.sha256(f"{provider}\0{environment_id}\0{session_id}".encode()).hexdigest()[:24]
    return _try_session_runtime_lock(dispatcher, f"session-{key}.lock")


def _continue_items(dispatcher: DispatcherService, gui: str | None = None, *, include_completed: bool = False) -> list[dict[str, Any]]:
    conversations = dispatcher.list_guis()
    if gui:
        conversations = [item for item in conversations if item["alias"].casefold() == gui.casefold()]
    items = []
    for conversation in conversations:
        for slot in dispatcher.list_slots(gui=conversation["gui_id"], active_only=False):
            if slot["state"] == "completed" and not include_completed:
                continue
            provider = slot.get("current_provider") or slot.get("pending_provider")
            session = slot.get("current_session_id")
            runtime = "PENDING" if slot.get("pending_launch_id") else (
                _runtime_label(dispatcher, provider, slot.get("current_environment_id"), session)
                if provider and session else "NOT OBSERVED")
            items.append({**slot, "gui_alias": conversation["alias"], "provider": provider,
                          "runtime_status": runtime,
                          "search_text": " ".join(str(v) for v in (conversation["alias"], slot["name"], provider or "", session or "")).casefold()})
    items.sort(key=lambda row: (row["state"] != "active", row.get("last_activity_at") is None,
                                row["last_activity_at"] or "", row["gui_alias"].casefold(), row["name"].casefold()), reverse=False)
    active = [row for row in items if row["state"] == "active"]
    inactive = [row for row in items if row["state"] != "active"]
    active.sort(key=lambda row: (row.get("last_activity_at") is None, row.get("last_activity_at") or "", row["gui_alias"].casefold(), row["name"].casefold()))
    active.sort(key=lambda row: row.get("last_activity_at") or "", reverse=True)
    inactive.sort(key=lambda row: (row.get("last_activity_at") is None, row.get("last_activity_at") or "", row["gui_alias"].casefold(), row["name"].casefold()))
    inactive.sort(key=lambda row: row.get("last_activity_at") or "", reverse=True)
    items = active + inactive
    return items


def _runtime_label(dispatcher: DispatcherService, provider: str, environment: str | None, session: str | None) -> str:
    if not environment or not session:
        return "UNKNOWN"
    env = next((item for item in dispatcher.materializer.list_environments() if item.environment_id == environment), None)
    if env is None or env.runtime_kind != detect_runtime_kind():
        return "UNKNOWN"
    return "IN USE" if _session_in_use(dispatcher, provider, environment, session) else "NOT OBSERVED"


def _run_picker(dispatcher: DispatcherService, args: argparse.Namespace, input_stream: TextIO, output_stream: TextIO) -> int:
    if not (input_stream.isatty() and output_stream.isatty()):
        raise ContinuityError(ErrorCode.INVALID_INPUT, "`llmd continue` without an agent requires an interactive terminal.")
    from .interactive import select_item
    items = _continue_items(dispatcher, args.gui, include_completed=args.all)
    if not items:
        print("No eligible agents have a resumable session.", file=output_stream)
        return 0
    action, item = select_item(items, title="LLMD — Resume Agent",
        render_line=lambda row: f"{row['gui_alias']:<20} {row['name']:<28} {(row.get('provider') or '—').upper():<8} {row['state']} / {row['runtime_status']}",
        input_stream=input_stream, output_stream=output_stream, filter_key="search_text")
    if action != "selected" or item is None:
        return 0
    if not item.get("current_session_id"):
        print("This agent has no selected session. Use `llmd register` or `llmd start` first.", file=output_stream)
        return 2
    if item["state"] == "completed":
        print("Completed agents cannot be resumed by the Phase 3 picker.", file=output_stream)
        return 2
    if item["runtime_status"] == "IN USE":
        print("This session is already in use by an LLMD-managed process.", file=output_stream)
        return 2
    if item["state"] == "inactive":
        print("Inactive agent selected. Confirm reactivation? [y/N] ", end="", file=output_stream, flush=True)
        if input_stream.readline().strip().casefold() not in {"y", "yes"}:
            return 0
        dispatcher.set_slot_state(gui=item["gui_alias"], name=item["name"], state="active", apply=True)
    if not args.apply:
        print("Dry-run: pass -a/--apply to resume this session.", file=output_stream)
        return 0
    return _run_pane(dispatcher, slot_id=item["slot_id"], launch_id=None, input_stream=input_stream, output_stream=output_stream)


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


def _resolve_name(positional: str | None, named: str | None, label: str) -> str | None:
    if positional is not None and named is not None and positional.casefold() != named.casefold():
        raise ContinuityError(ErrorCode.INVALID_INPUT, f"Conflicting positional and named {label} values.")
    return named if named is not None else positional


def _probe_existing_lock(path: Path) -> str:
    if not path.exists():
        return "not_present"
    try:
        stream = path.open("r+b")
    except OSError:
        return "inaccessible"
    try:
        try:
            if os.name == "nt":
                import msvcrt
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            return "available"
        except OSError:
            return "contended"
    finally:
        stream.close()


def _doctor_report(dispatcher: DispatcherService, gui: str | None = None, agent: str | None = None) -> dict[str, Any]:
    try:
        db = dispatcher.materializer.get_diagnostics_snapshot()
    except Exception as exc:
        db = {"db_exists": (dispatcher.home_dir / "index.sqlite").exists(), "integrity": "unavailable",
              "diagnostic_error": f"{type(exc).__name__}: {exc}"}
    lock = _probe_existing_lock(dispatcher.home_dir / "dispatcher.lock")
    report: dict[str, Any] = {
        "schema_version": 1,
        "registry": {"home": str(dispatcher.home_dir), "accessible": dispatcher.home_dir.exists(),
                     "database": {key: db.get(key) for key in ("db_exists", "schema_version", "supported_schema_version", "integrity", "counts", "diagnostic_error")},
                     "mutation_lock": lock},
        "scope": {"gui": gui, "agent": agent}, "agents": [], "pending_launches": [],
        "inconsistencies": [],
        "limitations": ["Lock observations cover this local runtime only; they do not prove external provider inactivity.",
                        "A lock timeout does not establish a stale lock or identify the blocked operation."],
    }
    rows = dispatcher._rows("""SELECT s.slot_id, s.name, s.state, g.alias,
                   a.provider AS current_provider, a.environment_id AS current_environment_id,
                   a.native_session_id AS current_session_id,
                   p.launch_id AS pending_launch_id, p.provider AS pending_provider
               FROM agent_slots s JOIN dispatcher_gui_conversations g USING(gui_id)
               LEFT JOIN agent_slot_activations a ON a.activation_id = (
                   SELECT cur.activation_id FROM agent_slot_activations cur WHERE cur.slot_id=s.slot_id
                   ORDER BY cur.sequence DESC LIMIT 1)
               LEFT JOIN dispatcher_pending_launches p ON p.launch_id = (
                   SELECT q.launch_id FROM dispatcher_pending_launches q WHERE q.slot_id=s.slot_id AND q.status='pending'
                   ORDER BY q.requested_at DESC, q.launch_id DESC LIMIT 1)
               WHERE (? IS NULL OR g.alias_key = ?) AND (? IS NULL OR s.name_key = ?)
               ORDER BY g.alias_key, s.name_key""",
               (gui.casefold() if gui else None, gui.casefold() if gui else None,
                agent.casefold() if agent else None, agent.casefold() if agent else None))
    environments = dispatcher.materializer.list_environments()
    for row in rows:
        provider = row["current_provider"] or row["pending_provider"]
        sid = row["current_session_id"]
        env_id = row["current_environment_id"]
        runtime = "PENDING" if row["pending_launch_id"] else "NOT OBSERVED"
        if sid and row["current_provider"]:
            env = next((value for value in environments if value.environment_id == env_id), None)
            if env is None or env.runtime_kind != detect_runtime_kind():
                runtime = "UNKNOWN"
            else:
                lock_key = hashlib.sha256(f"{provider}\0{env_id}\0{sid}".encode()).hexdigest()[:24]
                observation = _probe_existing_lock(dispatcher.home_dir / f"session-{lock_key}.lock")
                runtime = "IN USE" if observation == "contended" else "UNKNOWN" if observation == "inaccessible" else "NOT OBSERVED"
        report["agents"].append({"gui": row["alias"], "name": row["name"], "slot_id": row["slot_id"],
            "lifecycle": row["state"], "provider": provider, "session_id": sid, "runtime": runtime,
            "duplicate_resume": "blocked" if runtime == "IN USE" else "uncertain"})
        if row["pending_launch_id"]:
            pending = dispatcher._row("SELECT * FROM dispatcher_pending_launches WHERE launch_id = ?", (row["pending_launch_id"],))
            if pending:
                report["pending_launches"].append(dispatcher._with_captured_bootstrap_id(pending))
    report["pending_launches"].sort(key=lambda value: value["launch_id"])
    report["agents"].sort(key=lambda value: (value["gui"].casefold(), value["name"].casefold()))
    if db.get("db_exists") and db.get("integrity") not in ("ok", None):
        report["inconsistencies"].append({"kind": "sqlite_integrity", "detail": db["integrity"]})
    report["duplicate_resume_risk"] = "blocked" if any(a["runtime"] == "IN USE" for a in report["agents"]) else "uncertain"
    return report


def _resolve_historical_session(dispatcher: DispatcherService, *, gui: str, name: str,
                                provider: str | None, session_id: str | None,
                                allow_latest: bool = False) -> dict[str, Any] | None:
    slot = dispatcher.get_slot(gui=gui, name=name)
    history = slot["history"]
    if session_id:
        matches = [row for row in history if row["native_session_id"] == session_id]
        if provider:
            matches = [row for row in matches if row["provider"] == provider]
        if not matches:
            raise ContinuityError(ErrorCode.INVALID_INPUT, "Requested session ID is not in this agent's activation history.")
        return matches[-1]
    if provider:
        matches = dispatcher.sessions_for_provider(gui=gui, name=name, provider=provider)
        if not matches:
            raise ContinuityError(ErrorCode.INVALID_INPUT, f"No historical {provider} session exists for this agent.")
        if len(matches) > 1 and not allow_latest:
            raise ContinuityError(ErrorCode.INVALID_INPUT,
                f"Multiple historical {provider} sessions exist; specify --session-id from `llmd history`.")
        return matches[0]
    return None


def _listing(dispatcher: DispatcherService, args: argparse.Namespace) -> dict[str, Any]:
    if args.limit is not None and args.limit < 1:
        raise ContinuityError(ErrorCode.INVALID_INPUT, "Limit must be a positive integer.")
    limit = args.limit if args.limit is not None else (None if args.all else 10)
    gui = _resolve_name(args.gui_pos, args.gui, "GUI")
    if gui:
        rows = dispatcher.list_slots(gui=gui, active_only=False)
        rows = [row for row in rows if args.all or row['state'] != 'completed']
        rows.sort(key=lambda row: 0 if row['state'] == 'active' else 1 if row['state'] == 'inactive' else 2)
        total = len(rows)
        selected = rows if limit is None else rows[:limit]
        return {'action': 'list', 'gui': gui, 'slots': selected, 'total': total,
                'shown': len(selected), 'omitted': total - len(selected), 'limit': limit}
    guis = dispatcher.list_guis()
    total = len(guis)
    selected = guis if limit is None else guis[:limit]
    conversations = []
    for item in selected:
        slots = dispatcher.list_slots(gui=item['gui_id'])
        shown = slots if args.all else slots[:10]
        conversations.append({**item, 'slots': shown, 'total': len(slots), 'shown': len(shown),
                              'omitted': len(slots) - len(shown)})
    return {'action': 'list', 'schema_version': 1, 'conversations': conversations, 'total': total,
            'shown': len(conversations), 'omitted': total - len(conversations), 'limit': limit}


def _render_listing(result: dict[str, Any], stream: TextIO, color: str) -> None:
    use_color = color == 'always' or (color == 'auto' and stream.isatty() and 'NO_COLOR' not in os.environ)
    width = shutil.get_terminal_size((100, 24)).columns
    def style(value: str, code: str) -> str:
        return f"\033[{code}m{value}\033[0m" if use_color else value
    def clip(value: str, size: int) -> str:
        return value if len(value) <= size else value[:max(1, size - 1)] + '…'
    def rows(items: list[dict[str, Any]]) -> None:
        for row in items:
            provider = (row.get('current_provider') or row.get('pending_provider') or '—').upper()
            session = row.get('current_session_id') or '—'
            if width < 70:
                line = f"  {clip(row['name'], max(8, width - 25))} [{row['state']}] {provider}\n    {clip(session, max(8, width - 4))}"
            else:
                name_width = min(30, max(12, width // 3))
                session_width = max(8, width - name_width - 29)
                line = f"  {clip(row['name'], name_width):<{name_width}}  {style(f'{provider:<8}', '36')}  {clip(session, session_width):<{session_width}}  {row['state']}"
            print(style(line, '2') if row['state'] == 'inactive' else line, file=stream)
    if 'conversations' in result:
        for conversation in result['conversations']:
            print(style(conversation['alias'], '1'), file=stream)
            rows(conversation['slots'])
            if conversation['omitted']:
                print(f"  {conversation['omitted']} agents omitted.", file=stream)
        print(f"Showing {result['shown']} of {result['total']} conversations ({result['omitted']} omitted).", file=stream)
    else:
        print(style(result['gui'], '1'), file=stream)
        rows(result['slots'])
        print(f"Showing {result['shown']} of {result['total']} agents ({result['omitted']} omitted).", file=stream)


def dispatch(args: argparse.Namespace, parser: argparse.ArgumentParser, *, input_stream: TextIO, output_stream: TextIO) -> int:
    if args.command is None:
        if not (input_stream.isatty() and output_stream.isatty()):
            parser.print_help(file=output_stream)
            return 2
        from .interactive import run_interactive

        return run_interactive(DispatcherService(home_dir=args.home), input_stream=input_stream, output_stream=output_stream)

    if args.command in {"start", "continue"}:
        args.gui = _resolve_name(args.gui_pos, args.gui, "GUI")
        args.agent_name = _resolve_name(args.agent_pos, args.agent_name, "agent")
        if args.command == "start" and (not args.gui or not args.agent_name):
            raise ContinuityError(ErrorCode.INVALID_INPUT, "Both GUI and agent are required.")
        if args.command == "continue" and args.agent_name and not args.gui:
            raise ContinuityError(ErrorCode.INVALID_INPUT, "A GUI is required when an agent is specified.")
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
        result = _listing(dispatcher, args)
    elif args.command == "register":
        gui = _resolve_name(args.gui_pos, args.gui, "GUI")
        name = _resolve_name(args.agent_pos, args.agent_name, "agent")
        if not gui:
            raise ContinuityError(ErrorCode.INVALID_INPUT, "A GUI name is required.")
        if args.dry_run and args.apply:
            raise ContinuityError(ErrorCode.INVALID_INPUT, "Choose either --dry-run or --apply.")
        result = dispatcher.register(gui, name, provider=args.provider, session_id=args.session_id,
                                     apply=not args.dry_run, select=args.select)
    elif args.command == "history":
        result = {"action": "history", "slot": dispatcher.get_slot(gui=args.gui, name=args.agent_name)}
    elif args.command == "pending":
        result = {"action": "pending", "launches": dispatcher.list_pending_launches(gui=args.gui)}
    elif args.command == "doctor":
        result = _doctor_report(dispatcher, args.gui, args.agent_name)
    elif args.command == "recover":
        result = dispatcher.recover_captured_launch(gui=args.gui, name=args.agent_name, apply=args.apply)
    elif args.command == "attach":
        result = dispatcher.attach_session(gui=args.gui, name=args.agent_name, provider=args.provider,
                                           session_id=args.session_id, environment_selector=args.environment,
                                           cwd=args.cwd, launch_id=args.launch_id, apply=args.apply)
    elif args.command in {"start", "switch"}:
        positional_start = args.command == "start" and args.gui_pos is not None
        if positional_start:
            if not args.apply:
                preview = dispatcher.register(args.gui, args.agent_name, apply=False)
                print(f"{preview['summary']} New provider session preview only; execution requires --new -a.", file=output_stream)
                return 0
            if not args.new:
                raise ContinuityError(ErrorCode.INVALID_INPUT,
                    "Positional start execution requires --new and -a/--apply to authorize a provider launch.")
            dispatcher.register(args.gui, args.agent_name, apply=True)
            slot = dispatcher.get_slot(gui=args.gui, name=args.agent_name)
            if slot["current"]:
                raise ContinuityError(ErrorCode.INVALID_INPUT,
                    f"{args.gui!r} / {args.agent_name!r} already selects {slot['current']['provider']} session "
                    f"{slot['current']['native_session_id']}; use continue or switch explicitly.")
        reuse = args.command == "switch" and args.reuse_previous
        if reuse:
            old = _resolve_historical_session(dispatcher, gui=args.gui, name=args.agent_name,
                                              provider=args.provider, session_id=None, allow_latest=True)
            result = dispatcher.attach_session(gui=args.gui, name=args.agent_name, provider=old["provider"],
                session_id=old["native_session_id"], environment_selector=old["environment_id"],
                apply=args.apply, provenance="dispatcher_reuse")
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
        if not args.agent_name:
            return _run_picker(dispatcher, args, input_stream, output_stream)
        slot = dispatcher.get_slot(gui=args.gui, name=args.agent_name)
        target = _resolve_historical_session(dispatcher, gui=args.gui, name=args.agent_name,
            provider=args.provider, session_id=args.session_id) if (args.provider or args.session_id) else slot["current"]
        if target is None:
            raise ContinuityError(ErrorCode.INVALID_INPUT, "This slot has no selected session; use `llmd start`.")
        if slot["state"] == "completed":
            raise ContinuityError(ErrorCode.INVALID_INPUT, "Completed agents require an explicit lifecycle change before resumption.")
        if slot["state"] == "inactive":
            if not args.reactivate:
                raise ContinuityError(ErrorCode.INVALID_INPUT,
                    "This agent is inactive; pass --reactivate to confirm its lifecycle change.")
            if args.apply:
                dispatcher.set_slot_state(gui=args.gui, name=args.agent_name, state="active", apply=True)
        if target != slot["current"]:
            if args.apply and _session_in_use(dispatcher, target["provider"], target["environment_id"], target["native_session_id"]):
                raise ContinuityError(ErrorCode.INVALID_INPUT, "Requested historical session is already in use.")
            if not args.apply:
                result = {"action": "continue", "applied": False, "slot": slot,
                          "summary": f"Dry-run: would select historical {target['provider']} session {target['native_session_id']}."}
            else:
                dispatcher.attach_session(gui=args.gui, name=args.agent_name, provider=target["provider"],
                    session_id=target["native_session_id"], environment_selector=target["environment_id"],
                    apply=True, provenance="dispatcher_reuse")
        else:
            result = {"action": "continue", "applied": False, "slot": slot,
                      "summary": "Dry-run: pass -a/--apply to resume the selected session."}
        if args.apply:
            current_slot = dispatcher.get_slot(gui=args.gui, name=args.agent_name)
            return _run_pane(dispatcher, slot_id=current_slot["slot_id"], launch_id=None,
                             input_stream=input_stream, output_stream=output_stream)
    elif args.command == "open":
        result = _open(dispatcher, args)
        if args.apply and result.get("terminal_launcher_available") is False:
            print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True, default=_json_default) if args.json_output else result["summary"], file=output_stream)
            return 2
    elif args.command == "pane-run":
        return _run_pane(dispatcher, slot_id=args.slot_id, launch_id=args.launch_id,
                         input_stream=input_stream, output_stream=output_stream)
    else:
        parser.error("command required")
        return 2

    json_mode = bool(args.json_output)
    if json_mode:
        print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True, default=_json_default), file=output_stream)
    else:
        if result.get("action") == "list":
            _render_listing(result, output_stream, args.color)
            return 0
        if result.get("action") == "gui-list":
            for conversation in result["conversations"]:
                print(conversation["alias"], file=output_stream)
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
            print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True, default=_json_default), file=output_stream)
        if result.get("action") != "register" and not result.get("applied", True) and result.get("events"):
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
