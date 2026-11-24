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
from .environment import detect_runtime_kind, environment_is_locally_owned
from .errors import ContinuityError, ErrorCode
from .identifiers import generate_id, now_utc_iso
from .terminal_format import (
    clip_display,
    color_enabled,
    format_timestamp,
    pad_display,
    provider_color,
    state_color,
)

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
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Resume named Codex and AGY sessions associated with local GUI conversation aliases.\n\n"
            "Primary: start, continue, switch, review, return, list, open, history.\n"
            "Administration: gui, slot, register.\n"
            "Recovery and diagnostics: attach, pending, recover, doctor."
        ),
        epilog="Register applies by default; legacy mutations and launches require -a/--apply.",
    )
    parser.add_argument("-H", "--home", help="Override the shared agent_continuity registry directory.")
    parser.add_argument("-j", "--json", dest="json_output", action="store_true", help="Output JSON.")
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

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
    listing.add_argument("-N", "--history-count", type=int, default=0,
                         help="Show the N newest activation-history entries under each agent.")

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
            command.add_argument("-R", "--reactivate", action="store_true",
                                 help="Explicitly reactivate an inactive agent before switching providers.")
        command.add_argument("-C", "--cwd")
        command.add_argument("-a", "--apply", action="store_true")
        if command_name == "start":
            command.add_argument("-N", "--new", action="store_true", help="Explicitly authorize a new native conversation.")
            command.add_argument("-r", "--reactivate", action="store_true",
                                 help="Explicitly reactivate an inactive agent before resuming or starting.")

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

    review = sub.add_parser("review", help="Open or resume a reviewer agent linked to an original agent.")
    _add_common_options(review)
    review.add_argument("-g", "--gui", required=True)
    review.add_argument("-n", "--agent-name", required=True, help="Original implementation agent.")
    review.add_argument("-R", "--reviewer-agent", required=True, help="Distinct reviewer slot under the same GUI.")
    review.add_argument("-p", "--provider", required=True, choices=("agy", "codex"))
    review.add_argument("-e", "--environment")
    review.add_argument("-C", "--cwd", help="Reviewer working directory.")
    review.add_argument("-N", "--new", action="store_true", help="Explicitly request a new reviewer conversation.")
    review.add_argument("-a", "--apply", action="store_true")

    returning = sub.add_parser("return", help="Return from an active reviewer cycle to its original agent.")
    _add_common_options(returning)
    returning.add_argument("-g", "--gui", required=True)
    returning.add_argument("-n", "--agent-name", required=True, help="Original implementation agent.")
    returning.add_argument("-a", "--apply", action="store_true")

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
    # argparse renders help=SUPPRESS literally for subparser choices. Keep the
    # parser routable for terminal_launcher while hiding its internal command.
    sub._choices_actions[:] = [action for action in sub._choices_actions if action.dest != "pane-run"]

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
    show_summary: bool = True,
    transition_source: dict[str, Any] | None = None,
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

            if transition_source:
                if transition_source.get("review_cycle"):
                    transition_source["review_cycle"].update({
                        "reviewer_provider": provider,
                        "reviewer_environment_id": environment_id,
                        "reviewer_session_id": captured_session_id,
                    })
                dispatcher.complete_agent_transition(
                    gui=slot["gui_alias"], source_slot_id=transition_source["slot_id"],
                    destination_slot_id=slot_id, provider=provider, environment_id=environment_id,
                    session_id=captured_session_id,
                    source_state=transition_source.get("source_state", "inactive"),
                    destination_state=transition_source.get("destination_state", "active"),
                    expected_source=transition_source["expected_source"], expected_destination=None,
                    cwd=cwd, launch_id=launch_id, provenance=transition_source.get("provenance", "agent_transition"),
                    review_cycle=transition_source.get("review_cycle"), apply=True,
                )
            else:
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
            dispatcher.record_process_observation(
                slot_id=slot_id, launch_id=None, return_code=-1, outcome="spawn_failed",
                session_identity=(provider, environment_id, session_id),
            )
        raise ContinuityError(ErrorCode.PROVIDER_UNAVAILABLE, f"Failed to launch {provider}: {exc}") from exc
    try:
        dispatcher.record_process_observation(
            slot_id=slot_id, launch_id=launch_id, return_code=result.returncode,
            outcome="normal_exit" if result.returncode == 0 else "nonzero_exit",
            session_identity=(provider, environment_id, session_id) if session_id else None,
        )
    except ContinuityError as exc:
        raise ContinuityError(ErrorCode.METADATA_INACCESSIBLE,
            f"{provider} process exited with code {result.returncode}, but LLMD could not record the result. Do not relaunch blindly; run `llmd doctor` and inspect provider state.") from exc
    if result.returncode != 0:
        if launch_id:
            dispatcher.mark_launch_failed(launch_id=launch_id, detail=f"provider exited with {result.returncode}", apply=True)
        print(f"{slot['name']} exited with code {result.returncode}; slot and current session remain unchanged.", file=output_stream)
        return result.returncode
    opposite_provider = "agy" if provider == "codex" else "codex"
    print(f"\n{slot['name']} has exited.\n[1] Keep active (default)\n[2] Mark completed\n[3] Mark inactive\n"
          f"[4] Switch to {opposite_provider.upper()}\n[5] Switch to an existing agent\n[6] Create a new agent", file=output_stream)
    try:
        choice = input_stream.readline().strip()
    except (EOFError, OSError):
        choice = ""
    if choice == "4":
        result = _switch_after_exit(dispatcher, slot, opposite_provider,
                                    input_stream=input_stream, output_stream=output_stream)
        if show_summary:
            _render_scoped_summary(dispatcher, slot, output_stream)
        return result
    if choice == "5":
        result = _switch_to_existing_agent(dispatcher, slot, input_stream=input_stream,
                                           output_stream=output_stream)
        if show_summary:
            _render_scoped_summary(dispatcher, slot, output_stream)
        return result
    if choice == "6":
        result = _create_agent_after_exit(dispatcher, slot, input_stream=input_stream,
                                          output_stream=output_stream)
        if show_summary:
            _render_scoped_summary(dispatcher, slot, output_stream)
        return result
    state = {"2": "completed", "3": "inactive"}.get(choice, "active")
    if state != "active":
        dispatcher.set_slot_state(gui=slot["gui_alias"], name=slot["name"], state=state, apply=True)
    if show_summary:
        _render_scoped_summary(dispatcher, slot, output_stream)
    return 0


def _render_scoped_summary(dispatcher: DispatcherService, slot: dict[str, Any], stream: TextIO) -> None:
    args = argparse.Namespace(gui_pos=None, gui=slot["gui_alias"], limit=None, all=True,
                              history_count=0)
    _render_listing(_listing(dispatcher, args), stream, "auto", dispatcher=dispatcher)


def _switch_after_exit(
    dispatcher: DispatcherService,
    slot: dict[str, Any],
    provider: str,
    *,
    input_stream: TextIO,
    output_stream: TextIO,
) -> int:
    """Switch the exited slot to an exact prior provider session or explicitly new one."""
    sessions = dispatcher.sessions_for_provider(gui=slot["gui_alias"], name=slot["name"], provider=provider)
    target = None
    if sessions:
        print(f"Previous {provider.upper()} session: {sessions[0]['native_session_id']}", file=output_stream)
        print("[r] Reuse previous session (default)  [n] Start new conversation  [c] Cancel", file=output_stream)
        choice = input_stream.readline().strip().casefold()
        if choice in {"", "r", "reuse"}:
            target = sessions[0]
        elif choice in {"n", "new"}:
            if not _ask_confirmation(input_stream, output_stream,
                                     f"Start a new {provider.upper()} conversation under this slot?", default=False):
                print("Provider switch canceled; current selection and history were unchanged.", file=output_stream)
                return 0
        else:
            print("Provider switch canceled; current selection and history were unchanged.", file=output_stream)
            return 0
    elif not _ask_confirmation(input_stream, output_stream,
                               f"No previous {provider.upper()} session is registered. Start a new conversation?",
                               default=False):
        print("Provider switch canceled; current selection and history were unchanged.", file=output_stream)
        return 0

    if target:
        dispatcher.attach_session(
            gui=slot["gui_alias"], name=slot["name"], provider=target["provider"],
            session_id=target["native_session_id"], environment_selector=target["environment_id"],
            apply=True, provenance="post_exit_provider_switch",
        )
        current = dispatcher.get_slot(gui=slot["gui_alias"], name=slot["name"])
        return _run_pane(dispatcher, slot_id=current["slot_id"], launch_id=None,
                         input_stream=input_stream, output_stream=output_stream, show_summary=False)

    launch = dispatcher.begin_launch(
        gui=slot["gui_alias"], name=slot["name"], provider=provider,
        cwd=dispatcher.current_working_directory(slot), apply=True,
    )
    return _run_pane(dispatcher, slot_id=slot["slot_id"], launch_id=launch["details"]["launch_id"],
                     input_stream=input_stream, output_stream=output_stream, show_summary=False)


def _session_identity(slot: dict[str, Any]) -> tuple[str, str, str] | None:
    current = slot.get("current")
    if not current:
        return None
    return current["provider"], current["environment_id"], current["native_session_id"]


def _valid_existing_session(row: dict[str, Any]) -> bool:
    session = str(row.get("current_session_id") or "").strip().casefold()
    return bool(session) and session not in {"pending", "unknown", "unresolved", "none", "null"} \
        and not (session.startswith("<") and session.endswith(">")) \
        and bool(row.get("current_provider")) and bool(row.get("current_environment_id")) \
        and not row.get("pending_launch_id")


def _switch_to_existing_agent(
    dispatcher: DispatcherService,
    source: dict[str, Any],
    *,
    input_stream: TextIO,
    output_stream: TextIO,
) -> int:
    if not (input_stream.isatty() and output_stream.isatty()):
        print("Agent switching requires an interactive terminal; no slot state changed.", file=output_stream)
        return 2
    from .interactive import _agent_selector_line, select_item

    rows = [row for row in dispatcher.list_slots(gui=source["gui_alias"], active_only=False)
            if row["state"] == "inactive" and row["slot_id"] != source["slot_id"]
            and _valid_existing_session(row)]
    cycle = dispatcher.active_review_cycle(slot_id=source["slot_id"])
    preferred_original = cycle["original_slot_id"] if cycle and cycle["reviewer_slot_id"] == source["slot_id"] else None
    rows.sort(key=lambda row: (row["slot_id"] != preferred_original,
                               row.get("last_activity_at") is None,
                               row.get("last_activity_at") or "", row["name"].casefold()))
    if not rows:
        print("No inactive agents with an exact selected session are available under this GUI.", file=output_stream)
        return 0
    for row in rows:
        row["search_text"] = " ".join(str(row.get(key) or "") for key in
                                      ("name", "current_provider", "current_session_id", "state")).casefold()
    action, selected = select_item(
        rows, title=f"LLMD — Switch agent in {source['gui_alias']}",
        render_line=lambda row: _agent_selector_line(row, shutil.get_terminal_size((100, 24)).columns),
        header=lambda: _agent_selector_line({}, shutil.get_terminal_size((100, 24)).columns, header=True),
        input_stream=input_stream, output_stream=output_stream, filter_key="search_text",
    )
    if action != "selected" or selected is None:
        return 0
    destination = dispatcher.get_slot(gui=source["gui_alias"], name=selected["slot_id"])
    if destination["state"] != "inactive" or not destination["current"]:
        print("Destination is no longer inactive with a selected session; no slot state changed.", file=output_stream)
        return 2
    current = destination["current"]
    selected_identity = (selected.get("current_provider"), selected.get("current_environment_id"),
                         selected.get("current_session_id"))
    if selected_identity != (current["provider"], current["environment_id"], current["native_session_id"]):
        print("Destination session changed while the picker was open; no slot state changed.", file=output_stream)
        return 2
    if _session_in_use(dispatcher, current["provider"], current["environment_id"], current["native_session_id"]):
        print("Destination session is already in use; no slot state changed.", file=output_stream)
        return 2
    current_cycle = dispatcher.active_review_cycle(slot_id=source["slot_id"])
    returning = bool(current_cycle and current_cycle["reviewer_slot_id"] == source["slot_id"]
                     and current_cycle["original_slot_id"] == destination["slot_id"])
    cycle_payload = None
    destination_state = "active"
    provenance = "post_exit_agent_switch"
    if returning:
        current_cycle = dict(current_cycle)
        destination_state = current_cycle["original_state"]
        cycle_payload = {**current_cycle, "status": "returned"}
        provenance = "review_return"
    dispatcher.complete_agent_transition(
        gui=source["gui_alias"], source_slot_id=source["slot_id"],
        destination_slot_id=destination["slot_id"], provider=current["provider"],
        environment_id=current["environment_id"], session_id=current["native_session_id"],
        source_state="inactive", destination_state=destination_state,
        expected_source=_session_identity(source), expected_destination=_session_identity(destination),
        cwd=dispatcher.current_working_directory(destination), provenance=provenance,
        review_cycle=cycle_payload, apply=True,
    )
    refreshed = dispatcher.get_slot(gui=source["gui_alias"], name=destination["slot_id"])
    return _run_pane(dispatcher, slot_id=refreshed["slot_id"], launch_id=None,
                     input_stream=input_stream, output_stream=output_stream, show_summary=False)


def _create_agent_after_exit(
    dispatcher: DispatcherService,
    source: dict[str, Any],
    *,
    input_stream: TextIO,
    output_stream: TextIO,
) -> int:
    if not (input_stream.isatty() and output_stream.isatty()):
        print("Creating and switching agents requires an interactive terminal; no slot state changed.", file=output_stream)
        return 2
    print("New agent name: ", end="", file=output_stream, flush=True)
    name = input_stream.readline().strip()
    if not name or len(name) > 120 or name.casefold() == source["name"].casefold():
        print("A distinct agent name of 1–120 characters is required; no slot was created.", file=output_stream)
        return 2
    if any(row["name"].casefold() == name.casefold()
           for row in dispatcher.list_slots(gui=source["gui_alias"], active_only=False)):
        print("That agent name already exists under this GUI; no slot was created.", file=output_stream)
        return 2
    print("Provider [1] Codex  [2] AGY: ", end="", file=output_stream, flush=True)
    provider_choice = input_stream.readline().strip().casefold()
    provider = {"1": "codex", "codex": "codex", "2": "agy", "agy": "agy"}.get(provider_choice)
    if provider is None:
        print("Provider selection canceled; no slot was created.", file=output_stream)
        return 0
    default_cwd = str(Path.cwd())
    print(f"Working directory [{default_cwd}]: ", end="", file=output_stream, flush=True)
    raw_cwd = input_stream.readline().strip()
    cwd = Path(raw_cwd or default_cwd).expanduser()
    if not cwd.is_dir():
        print(f"Working directory does not exist: {cwd}; no slot was created.", file=output_stream)
        return 2
    cwd = cwd.resolve()
    if not _ask_confirmation(input_stream, output_stream,
                             f"Create {name!r} under {source['gui_alias']!r}, initialize {provider.upper()} in {cwd}, and switch to it?",
                             default=False):
        print("New agent canceled; no slot or provider launch was created.", file=output_stream)
        return 0
    launch = dispatcher.prepare_start(gui=source["gui_alias"], name=name, provider=provider,
                                       cwd=str(cwd), apply=True)
    return _run_pane(
        dispatcher, slot_id=launch["details"]["slot_id"], launch_id=launch["details"]["launch_id"],
        input_stream=input_stream, output_stream=output_stream, show_summary=False,
        transition_source={"slot_id": source["slot_id"], "expected_source": _session_identity(source),
                          "source_state": "inactive", "destination_state": "active",
                          "provenance": "post_exit_new_agent"},
    )


def _review_cycle_payload(original: dict[str, Any], reviewer_slot_id: str, reviewer_identity=None,
                          *, status: str = "active") -> dict[str, Any]:
    original_current = original["current"]
    return {"cycle_id": generate_id("review"), "original_slot_id": original["slot_id"],
            "reviewer_slot_id": reviewer_slot_id,
            "original_provider": original_current["provider"],
            "original_environment_id": original_current["environment_id"],
            "original_session_id": original_current["native_session_id"],
            "original_state": original["state"],
            "reviewer_provider": reviewer_identity["provider"] if reviewer_identity else None,
            "reviewer_environment_id": reviewer_identity["environment_id"] if reviewer_identity else None,
            "reviewer_session_id": reviewer_identity["native_session_id"] if reviewer_identity else None,
            "status": status, "created_at": now_utc_iso()}


def _review(dispatcher: DispatcherService, args: argparse.Namespace,
            input_stream: TextIO, output_stream: TextIO) -> int:
    original = dispatcher.get_slot(gui=args.gui, name=args.agent_name)
    if original["state"] != "active" or original["current"] is None:
        raise ContinuityError(ErrorCode.INVALID_INPUT, "Review requires an active original agent with an exact selected session.")
    if args.reviewer_agent.casefold() == original["name"].casefold():
        raise ContinuityError(ErrorCode.INVALID_INPUT, "Reviewer must use a distinct agent slot.")
    original_identity = _session_identity(original)
    if _session_in_use(dispatcher, *original_identity):
        raise ContinuityError(ErrorCode.INVALID_INPUT, "Original session is in use; review cannot switch it yet.")
    existing_cycle = dispatcher.open_review_cycle(slot_id=original["slot_id"])
    if existing_cycle:
        status_hint = "inspect `llmd pending` and recover it" if existing_cycle["status"] == "pending" else "return first"
        raise ContinuityError(ErrorCode.INVALID_INPUT,
                              f"This original agent already has an open review cycle; {status_hint}.")
    reviewer = None
    with contextlib.suppress(ContinuityError):
        reviewer = dispatcher.get_slot(gui=args.gui, name=args.reviewer_agent)
    if reviewer and dispatcher.open_review_cycle(slot_id=reviewer["slot_id"]):
        raise ContinuityError(ErrorCode.INVALID_INPUT, "Reviewer slot is linked to another open review cycle.")
    reviewer_identity = _session_identity(reviewer) if reviewer else None
    if not args.new:
        if reviewer_identity is None:
            raise ContinuityError(ErrorCode.INVALID_INPUT, "Reviewer has no selected session; use -N -a to create one.")
        if reviewer_identity[0] != args.provider:
            raise ContinuityError(ErrorCode.INVALID_INPUT, "Reviewer provider differs from the selected session; use -N -a for a new one.")
        if _session_in_use(dispatcher, *reviewer_identity):
            raise ContinuityError(ErrorCode.INVALID_INPUT, "Reviewer session is already in use.")
    elif not args.apply:
        print("New reviewer sessions require both -N and -a; preview only.", file=output_stream)
        return 0
    if args.new and not args.apply:
        print("New reviewer sessions require both -N and -a; no provider was launched.", file=output_stream)
        return 0
    if not args.apply:
        print(f"Preview: link {original['name']} to reviewer {args.reviewer_agent} and resume its selected session.", file=output_stream)
        return 0
    if args.new:
        prepared = dispatcher.prepare_start(
            gui=args.gui, name=args.reviewer_agent, provider=args.provider, cwd=args.cwd,
            environment_selector=args.environment, expected_current=reviewer_identity,
            reactivate=bool(reviewer and reviewer["state"] == "inactive"), defer_reactivate=True, apply=True,
        )
        target_slot_id = prepared["details"]["slot_id"]
        cycle = _review_cycle_payload(original, target_slot_id, status="pending")
        dispatcher.record_pending_review_cycle(gui=args.gui, cycle=cycle,
                                              expected_original=original_identity, apply=True)
        return _run_pane(
            dispatcher, slot_id=target_slot_id, launch_id=prepared["details"]["launch_id"],
            input_stream=input_stream, output_stream=output_stream,
            transition_source={"slot_id": original["slot_id"], "expected_source": original_identity,
                              "review_cycle": {**cycle, "status": "active"},
                              "provenance": "reviewer_bootstrap"},
        )
    cycle = _review_cycle_payload(original, reviewer["slot_id"], reviewer["current"])
    dispatcher.complete_agent_transition(
        gui=args.gui, source_slot_id=original["slot_id"], destination_slot_id=reviewer["slot_id"],
        provider=reviewer_identity[0], environment_id=reviewer_identity[1], session_id=reviewer_identity[2],
        source_state="inactive", destination_state="active", expected_source=original_identity,
        expected_destination=reviewer_identity, cwd=args.cwd or dispatcher.current_working_directory(reviewer),
        provenance="reviewer_resume", review_cycle=cycle, apply=True,
    )
    latest = dispatcher.get_slot(gui=args.gui, name=reviewer["slot_id"])
    return _run_pane(dispatcher, slot_id=latest["slot_id"], launch_id=None,
                     input_stream=input_stream, output_stream=output_stream)


def _return(dispatcher: DispatcherService, args: argparse.Namespace,
            input_stream: TextIO, output_stream: TextIO) -> int:
    original = dispatcher.get_slot(gui=args.gui, name=args.agent_name)
    cycle = dispatcher.active_review_cycle(slot_id=original["slot_id"])
    if not cycle or cycle["original_slot_id"] != original["slot_id"]:
        raise ContinuityError(ErrorCode.INVALID_INPUT, "No active reviewer cycle is linked to this original agent.")
    reviewer = dispatcher.get_slot(gui=args.gui, name=cycle["reviewer_slot_id"])
    reviewer_identity = _session_identity(reviewer)
    original_identity = (cycle["original_provider"], cycle["original_environment_id"], cycle["original_session_id"])
    if reviewer_identity is None or _session_identity(original) != original_identity:
        raise ContinuityError(ErrorCode.INVALID_INPUT, "Original or reviewer session changed; return was not applied.")
    if not args.apply:
        print(f"Preview: return from {reviewer['name']} to exact {original_identity[0]} session {original_identity[2]}.", file=output_stream)
        return 0
    if _session_in_use(dispatcher, *reviewer_identity) or _session_in_use(dispatcher, *original_identity):
        raise ContinuityError(ErrorCode.INVALID_INPUT, "A review session is in use; return was not applied.")
    dispatcher.complete_agent_transition(
        gui=args.gui, source_slot_id=reviewer["slot_id"], destination_slot_id=original["slot_id"],
        provider=original_identity[0], environment_id=original_identity[1], session_id=original_identity[2],
        source_state="inactive", destination_state=cycle["original_state"], expected_source=reviewer_identity,
        expected_destination=original_identity, cwd=dispatcher.current_working_directory(original),
        provenance="review_return", review_cycle={**cycle, "status": "returned"}, apply=True,
    )
    selected = dispatcher.get_slot(gui=args.gui, name=original["slot_id"])
    return _run_pane(dispatcher, slot_id=selected["slot_id"], launch_id=None,
                     input_stream=input_stream, output_stream=output_stream)


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
            if slot.get("pending_launch_id"):
                pending = dispatcher._row("SELECT environment_id FROM dispatcher_pending_launches WHERE launch_id = ?",
                                          (slot["pending_launch_id"],))
                runtime = _runtime_label(dispatcher, provider, pending["environment_id"], None, pending=True) if pending else "UNKNOWN"
            else:
                runtime = (_runtime_label(dispatcher, provider, slot.get("current_environment_id"), session)
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


def _runtime_label(dispatcher: DispatcherService, provider: str, environment: str | None,
                   session: str | None, *, pending: bool = False) -> str:
    if not environment or (not session and not pending):
        return "UNKNOWN"
    env = next((item for item in dispatcher.materializer.list_environments() if item.environment_id == environment), None)
    if env is None or not environment_is_locally_owned(dispatcher.home_dir, env):
        return "UNKNOWN"
    if pending:
        return "PENDING"
    if not session:
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
        if args.apply:
            if _session_in_use(dispatcher, item["provider"], item["current_environment_id"], item["current_session_id"]):
                print("This session is already in use by an LLMD-managed process.", file=output_stream)
                return 2
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
                   p.launch_id AS pending_launch_id, p.provider AS pending_provider,
                   p.environment_id AS pending_environment_id
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
        runtime = "NOT OBSERVED"
        if row["pending_launch_id"]:
            pending_env = next((value for value in environments if value.environment_id == row["pending_environment_id"]), None)
            runtime = "PENDING" if pending_env and environment_is_locally_owned(dispatcher.home_dir, pending_env) else "UNKNOWN"
        elif sid and row["current_provider"]:
            env = next((value for value in environments if value.environment_id == env_id), None)
            if env is None or not environment_is_locally_owned(dispatcher.home_dir, env):
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


def _render_doctor_report(report: dict[str, Any], stream: TextIO) -> None:
    registry = report["registry"]
    database = registry["database"]
    print("LLMD Doctor", file=stream)
    print(f"Registry: {'accessible' if registry['accessible'] else 'unavailable'} ({registry['home']})", file=stream)
    print(f"Registry integrity: {database.get('integrity') or 'unknown'}", file=stream)
    if database.get("diagnostic_error"):
        print(f"  Diagnostic error: {database['diagnostic_error']}", file=stream)
    print(f"Registry lock: {registry['mutation_lock']}", file=stream)
    print("Agents:", file=stream)
    if not report["agents"]:
        print("  No matching agents.", file=stream)
    for agent in report["agents"]:
        provider = (agent.get("provider") or "unassigned").upper()
        session = agent.get("session_id") or "no selected session"
        print(f"  {agent['gui']} / {agent['name']}  {provider}  {agent['lifecycle']}  {agent['runtime']}", file=stream)
        print(f"    Session: {session}; duplicate resume: {agent['duplicate_resume']}", file=stream)
    print("Pending launches:", file=stream)
    if not report["pending_launches"]:
        print("  None.", file=stream)
    for pending in report["pending_launches"]:
        captured = pending.get("captured_session_id") or "no captured session ID"
        print(f"  {pending['launch_id']}  {pending.get('provider', 'unknown')}  {captured}", file=stream)
    print("Inconsistencies:", file=stream)
    if not report["inconsistencies"]:
        print("  None positively established.", file=stream)
    for issue in report["inconsistencies"]:
        print(f"  {issue['kind']}: {issue['detail']}", file=stream)
    print("Limitations:", file=stream)
    for limitation in report["limitations"]:
        print(f"  - {limitation}", file=stream)


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
    if args.history_count < 0:
            raise ContinuityError(ErrorCode.INVALID_INPUT, "history count must be a nonnegative integer.")
    limit = args.limit if args.limit is not None else (None if args.all else 10)

    def include_history(rows: list[dict[str, Any]], gui_name: str) -> None:
        if args.history_count == 0:
            return
        for row in rows:
            slot = dispatcher.get_slot(gui=gui_name, name=row["name"])
            latest_activation = slot["history"][-1]["activation_id"] if slot["history"] else None
            history = []
            for activation in reversed(slot["history"][-args.history_count:]):
                session_id = activation.get("native_session_id")
                normalized = str(session_id or "").strip().casefold()
                unresolved = (not normalized or normalized in {"pending", "unknown", "unresolved", "none", "null"}
                              or (normalized.startswith("<") and normalized.endswith(">")))
                history.append({**activation, "selected": activation["activation_id"] == latest_activation,
                                "unresolved": unresolved})
            row["activation_history"] = history

    gui = _resolve_name(args.gui_pos, args.gui, "GUI")
    if gui:
        rows = dispatcher.list_slots(gui=gui, active_only=False)
        rows = [row for row in rows if args.all or row['state'] != 'completed']
        rows = _sort_slot_rows(rows)
        total = len(rows)
        selected = rows if limit is None else rows[:limit]
        include_history(selected, gui)
        return {'action': 'list', 'gui': gui, 'slots': selected, 'total': total,
                'shown': len(selected), 'omitted': total - len(selected), 'limit': limit}
    guis = dispatcher.list_guis()
    total = len(guis)
    selected = guis if limit is None else guis[:limit]
    conversations = []
    for item in selected:
        slots = dispatcher.list_slots(gui=item['gui_id'], active_only=False)
        slots = [row for row in slots if args.all or row['state'] != 'completed']
        slots = _sort_slot_rows(slots)
        shown = slots if args.all else slots[:10]
        include_history(shown, item['gui_id'])
        conversations.append({**item, 'slots': shown, 'total': len(slots), 'shown': len(shown),
                              'omitted': len(slots) - len(shown)})
    return {'action': 'list', 'schema_version': 1, 'conversations': conversations, 'total': total,
            'shown': len(conversations), 'omitted': total - len(conversations), 'limit': limit}


def _sort_slot_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped = []
    for state in ("active", "inactive", "completed"):
        group = [row for row in rows if row["state"] == state]
        group.sort(key=lambda row: (row.get("last_activity_at") is not None, row.get("last_activity_at") or ""),
                   reverse=True)
        grouped.extend(group)
    return grouped


def _render_listing(
    result: dict[str, Any], stream: TextIO, color: str, *, dispatcher: DispatcherService | None = None,
) -> None:
    use_color = color_enabled(color, is_tty=stream.isatty())
    width = shutil.get_terminal_size((100, 24)).columns

    def rows(items: list[dict[str, Any]]) -> None:
        name_width = max(12, min(28, (width - 64) // 2))
        session_width = max(8, width - name_width - 68)
        for row in items:
            provider = row.get('current_provider') or row.get('pending_provider') or '—'
            provider_text = provider_color(pad_display(provider, 7), enabled=use_color)
            state_text = state_color(pad_display(row['state'], 9), enabled=use_color)
            session = row.get('current_session_id') or '—'
            activity = format_timestamp(row.get('last_activity_at'))
            runtime = (_runtime_label(dispatcher, provider, row.get('current_environment_id'),
                                      row.get('current_session_id'), pending=bool(row.get('pending_launch_id')))
                       if dispatcher else 'UNKNOWN')
            if width < 96:
                print(f"  {clip_display(row['name'], max(8, width - 31))}  {provider_text}  {state_text}", file=stream)
                print(f"    {activity}  {runtime}  {clip_display(session, max(8, width - 6))}", file=stream)
            else:
                line = (f"  {pad_display(row['name'], name_width)}  {provider_text}  {activity}  "
                        f"{state_text}  {runtime:<12}  {clip_display(session, session_width)}")
                print(line, file=stream)
            for entry in row.get("activation_history", []):
                entry_date = format_timestamp(entry.get("activated_at"))
                entry_provider = provider_color(pad_display(entry.get("provider") or "—", 7), enabled=use_color)
                entry_id = "<unresolved>" if entry.get("unresolved") else entry["native_session_id"]
                marker = " *" if entry.get("selected") else ""
                history_line = (f"    {pad_display(entry_date, 16)}  {entry_provider}  "
                                f"{clip_display(entry_id, max(8, width - 32))}{marker}")
                print(history_line, file=stream)

    if 'conversations' in result:
        for index, conversation in enumerate(result['conversations']):
            if index:
                print(file=stream)
            activity = format_timestamp(conversation.get('last_activity_at'))
            print(f"{conversation['alias']}  Last activity: {activity}", file=stream)
            if width >= 96:
                print("  Agent                         Provider  Last activity     Lifecycle  Runtime       Session", file=stream)
            rows(conversation['slots'])
            if conversation['omitted']:
                print(f"  {conversation['omitted']} agents omitted.", file=stream)
        print(f"Showing {result['shown']} of {result['total']} conversations ({result['omitted']} omitted).", file=stream)
    else:
        print(f"{result['gui']}  Last activity: {format_timestamp(result.get('last_activity_at'))}", file=stream)
        if width >= 96:
            print("  Agent                         Provider  Last activity     Lifecycle  Runtime       Session", file=stream)
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
    elif args.command == "start":
        return _start(dispatcher, args, input_stream=input_stream, output_stream=output_stream)
    elif args.command == "review":
        return _review(dispatcher, args, input_stream, output_stream)
    elif args.command == "return":
        return _return(dispatcher, args, input_stream, output_stream)
    elif args.command == "switch":
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
            current_slot = dispatcher.get_slot(gui=args.gui, name=args.agent_name)
            current = current_slot["current"]
            expected_current = ((current["provider"], current["environment_id"], current["native_session_id"])
                                if current else None)
            result = dispatcher.begin_launch(gui=args.gui, name=args.agent_name, provider=args.provider,
                                             cwd=args.cwd, environment_selector=args.environment,
                                             expected_current=expected_current, check_current=True,
                                             reactivate=args.reactivate, apply=args.apply)
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
        if args.apply and _session_in_use(dispatcher, target["provider"], target["environment_id"], target["native_session_id"]):
            raise ContinuityError(ErrorCode.INVALID_INPUT, "Requested session is already in use.")
        if slot["state"] == "inactive":
            if not args.reactivate:
                raise ContinuityError(ErrorCode.INVALID_INPUT,
                    "This agent is inactive; pass --reactivate to confirm its lifecycle change.")
            if args.apply:
                dispatcher.set_slot_state(gui=args.gui, name=args.agent_name, state="active", apply=True)
        if target != slot["current"]:
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
            _render_listing(result, output_stream, args.color, dispatcher=dispatcher)
            return 0
        if result.get("schema_version") == 1 and "registry" in result and "agents" in result:
            _render_doctor_report(result, output_stream)
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


def _ask_confirmation(input_stream: TextIO, output_stream: TextIO, prompt: str, *, default: bool) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    print(f"{prompt} {suffix} ", end="", file=output_stream, flush=True)
    response = input_stream.readline().strip().casefold()
    if not response:
        return default
    return response in {"y", "yes"}


def _start(
    dispatcher: DispatcherService,
    args: argparse.Namespace,
    *,
    input_stream: TextIO,
    output_stream: TextIO,
) -> int:
    dispatcher._sync()
    gui_row = dispatcher._row(
        "SELECT gui_id FROM dispatcher_gui_conversations WHERE alias_key = ?", (args.gui.strip().casefold(),)
    )
    slot_row = (dispatcher._row("SELECT slot_id FROM agent_slots WHERE gui_id = ? AND name_key = ?",
                                (gui_row["gui_id"], args.agent_name.strip().casefold())) if gui_row else None)
    slot = dispatcher.get_slot(gui=args.gui, name=args.agent_name) if slot_row else None
    current = slot["current"] if slot else None
    expected_current = ((current["provider"], current["environment_id"], current["native_session_id"])
                        if current else None)

    if current and not args.new:
        if args.provider != current["provider"]:
            raise ContinuityError(ErrorCode.INVALID_INPUT,
                                  f"Requested provider differs from the selected {current['provider']} session; use `llmd switch` explicitly.")
        if slot["state"] == "completed":
            raise ContinuityError(ErrorCode.INVALID_INPUT,
                                  "Completed agents require an explicit lifecycle change before resuming.")
        if slot["state"] == "inactive" and not args.reactivate:
            raise ContinuityError(ErrorCode.INVALID_INPUT,
                                  "This agent is inactive; pass --reactivate to confirm its lifecycle change.")
        if not args.apply:
            print(f"{args.gui} / {args.agent_name} already selects {current['provider']} session "
                  f"{current['native_session_id']}. Preview only; pass -a to resume it.", file=output_stream)
            return 0
        if input_stream.isatty() and output_stream.isatty() and not _ask_confirmation(
            input_stream, output_stream,
            f"Resume selected {current['provider']} session {current['native_session_id']}?", default=True,
        ):
            print("Start canceled; the selected session and slot state were unchanged.", file=output_stream)
            return 0
        if _session_in_use(dispatcher, current["provider"], current["environment_id"], current["native_session_id"]):
            raise ContinuityError(ErrorCode.INVALID_INPUT, "Requested session is already in use.")
        if slot["state"] == "inactive":
            dispatcher.set_slot_state(gui=args.gui, name=args.agent_name, state="active", apply=True)
        return _run_pane(dispatcher, slot_id=slot["slot_id"], launch_id=None,
                         input_stream=input_stream, output_stream=output_stream)

    if not args.new and args.apply:
        raise ContinuityError(ErrorCode.INVALID_INPUT,
                              "Starting a new conversation requires --new and -a/--apply.")
    if (current and args.new and args.apply and input_stream.isatty() and output_stream.isatty()
            and not _ask_confirmation(
                input_stream, output_stream,
                f"Start a NEW {args.provider} conversation and retain the selected session in history?",
                default=False)):
        print("New conversation canceled; no provider was launched.", file=output_stream)
        return 0

    result = dispatcher.prepare_start(
        gui=args.gui,
        name=args.agent_name,
        provider=args.provider,
        cwd=args.cwd,
        environment_selector=args.environment,
        reactivate=args.reactivate,
        expected_current=expected_current,
        apply=args.apply,
    )
    if args.apply:
        return _run_pane(dispatcher, slot_id=result["details"]["slot_id"],
                         launch_id=result["details"]["launch_id"],
                         input_stream=input_stream, output_stream=output_stream)
    print(f"{result['summary']} New provider session preview only; execution requires --new -a.",
          file=output_stream)
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
