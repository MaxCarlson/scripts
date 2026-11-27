"""`llmd` / `llm-dispatcher` CLI for named GUI-agent sessions."""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import hashlib
import json
import ntpath
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Sequence
from contextvars import ContextVar
from pathlib import Path, PurePosixPath
from typing import Any, TextIO
from uuid import uuid4

from . import __version__
from .dispatcher import DispatcherService
from .environment import (
    detect_runtime_kind,
    environment_is_locally_owned,
    load_or_create_environment,
    resolve_environment_selector,
)
from .errors import ContinuityError, ErrorCode
from .identifiers import generate_id, now_utc_iso
from .terminal_format import (
    clip_display,
    color_enabled,
    display_width,
    format_timestamp,
    outcome_semantic,
    pad_semantic,
    provider_semantic,
    runtime_semantic,
    semantic_color,
    state_color,
    temporary_vt_processing,
)

_BOOTSTRAP_PROMPT = "Session initialization only. Reply READY and await further instructions."
_BOOTSTRAP_TIMEOUT_SECONDS = 180
_NATIVE_ARG_COMMANDS = {"continue", "start", "switch", "review", "return", "last", "open"}
_COLOR_MODE: ContextVar[str] = ContextVar("llmd_color_mode", default="auto")
_STARTUP_PROGRESS: ContextVar[bool] = ContextVar("llmd_startup_progress", default=False)
_STARTUP_STARTED: ContextVar[float | None] = ContextVar("llmd_startup_started", default=None)


def _current_color_mode() -> str:
    return _COLOR_MODE.get()


def _startup_progress(message: str) -> None:
    started = _STARTUP_STARTED.get()
    if not _STARTUP_PROGRESS.get() or started is None:
        return
    print(f"LLMD startup +{time.monotonic() - started:.2f}s: {message}", file=sys.stderr, flush=True)


def _run_provider_with_progress(
    argv: Sequence[str], *, label: str, progress_interval: float = 4.0, **kwargs: Any
) -> subprocess.CompletedProcess:
    """Run a provider process while periodically reporting elapsed wait time to stderr."""
    done = threading.Event()
    stage_started = time.monotonic()
    startup_started = _STARTUP_STARTED.get()

    def report_wait() -> None:
        while not done.wait(progress_interval):
            total = time.monotonic() - startup_started if startup_started is not None else time.monotonic() - stage_started
            print(f"LLMD startup +{total:.2f}s: {label} still running ({time.monotonic() - stage_started:.0f}s elapsed)",
                  file=sys.stderr, flush=True)

    reporter = None
    if _STARTUP_PROGRESS.get():
        reporter = threading.Thread(target=report_wait, name="llmd-startup-progress", daemon=True)
        reporter.start()
    try:
        return subprocess.run(argv, **kwargs)
    finally:
        done.set()
        if reporter is not None:
            reporter.join(timeout=0.2)


class _LLMDArgumentParser(argparse.ArgumentParser):
    """Keep provider argv opaque after LLMD's explicit `--` separator."""

    def parse_args(self, args=None, namespace=None):
        values = list(sys.argv[1:] if args is None else args)
        if self.prog == "llmd" and "--" in values:
            separator = values.index("--")
            provider_args = values[separator + 1 :]
            parsed = super().parse_args(values[:separator], namespace)
            parsed.native_args = provider_args
            return parsed
        parsed = super().parse_args(values, namespace)
        if self.prog == "llmd":
            parsed.native_args = []
        return parsed


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
    parser.add_argument("-c", "--color", choices=("auto", "always", "never"), default=argparse.SUPPRESS,
                        help="Color human-readable output (default: auto).")


def _add_execution_options(parser: argparse.ArgumentParser, *, help_text: str = "Execute (compatibility alias; execution is the default).") -> None:
    parser.add_argument("-d", "--dry-run", action="store_true", help="Preview without performing this operation.")
    parser.add_argument("-a", "--apply", action="store_true", help=help_text)


def build_parser() -> argparse.ArgumentParser:
    parser = _LLMDArgumentParser(
        prog="llmd",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Resume named Codex and AGY sessions associated with local GUI conversation aliases.\n\n"
            "Primary: start, continue, switch, review, return, list, open, history.\n"
            "Administration: gui, slot, register.\n"
            "Recovery and diagnostics: attach, pending, recover, doctor."
        ),
        epilog="Operational commands execute by default; use -d/--dry-run to preview. -a/--apply remains a compatibility alias.",
    )
    parser.add_argument("-H", "--home", help="Override the shared agent_continuity registry directory.")
    parser.add_argument("-j", "--json", dest="json_output", action="store_true", help="Output JSON.")
    parser.add_argument("-c", "--color", choices=("auto", "always", "never"), default="auto",
                        help="Color human-readable output (default: auto).")
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    gui = sub.add_parser("gui", help="Register or list local GUI conversation aliases.")
    gui_sub = gui.add_subparsers(dest="gui_command")
    gui_add = gui_sub.add_parser("add", help="Register a local GUI conversation alias.")
    _add_common_options(gui_add)
    gui_add.add_argument("-n", "--name", required=True)
    _add_execution_options(gui_add)
    gui_rename = gui_sub.add_parser("rename", help="Rename a local GUI alias while retaining its stable identity and slots.")
    _add_common_options(gui_rename)
    gui_rename.add_argument("-g", "--gui", required=True)
    gui_rename.add_argument("-n", "--name", required=True)
    _add_execution_options(gui_rename)
    gui_list = gui_sub.add_parser("list", help="List active GUI conversation aliases.")
    _add_common_options(gui_list)

    slot = sub.add_parser("slot", help="Create and change agent-slot state.")
    slot_sub = slot.add_subparsers(dest="slot_command")
    slot_create = slot_sub.add_parser("create", help="Create a named agent slot.")
    _add_common_options(slot_create)
    slot_create.add_argument("-g", "--gui", required=True)
    slot_create.add_argument("-n", "--agent-name", required=True)
    _add_execution_options(slot_create)
    for action in ("disable", "enable", "complete"):
        help_text = {"disable": "Temporarily disable an agent slot.", "enable": "Enable an agent slot.",
                     "complete": "Mark an agent slot's work complete."}[action]
        command = slot_sub.add_parser(action, help=help_text)
        _add_common_options(command)
        command.add_argument("-g", "--gui", required=True)
        command.add_argument("-n", "--agent-name", required=True)
        _add_execution_options(command)

    listing = sub.add_parser("list", help="List conversations and their agents.")
    _add_common_options(listing)
    listing.add_argument("gui_pos", nargs="?")
    listing.add_argument("-g", "--gui")
    listing.add_argument("-l", "--limit", type=int, help="Maximum records (default 10, or unlimited with --all).")
    listing.add_argument("-A", "--all", action="store_true")
    listing.add_argument("-N", "--history-count", type=int, default=0,
                         help="Show the N newest activation-history entries under each agent.")

    last = sub.add_parser("last", help="Show or resume the exact session last launched by this terminal.")
    _add_common_options(last)
    last.add_argument("-N", "--count", type=int, help="Show the N newest launches from this terminal.")
    last.add_argument("-a", "--apply", action="store_true", help="Resume the exact recorded session.")
    last.add_argument("-r", "--resume", action="store_true", help="Resume the exact recorded session (preferred spelling).")
    last.add_argument("-R", "--reactivate", action="store_true",
                      help="Explicitly reactivate an inactive slot before resuming it.")
    last.add_argument("-C", "--cwd", help="Use this working directory for this invocation only.")
    last.add_argument("-U", "--allow-native-unknown", action="store_true",
                      help="Authorize validated generic provider options after `--`.")

    recent = sub.add_parser("recent", help="Read-only launch history across all terminals.")
    _add_common_options(recent)
    recent.add_argument("-N", "--count", type=int, default=20, help="Maximum records to show (1–1000).")

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
    _add_execution_options(attach)

    for command_name in ("start", "switch"):
        command = sub.add_parser(
            command_name,
            help="Start or switch a native session for a named agent slot.",
            epilog="Pass supported provider options after `--`; LLMD-managed identity, bootstrap, and directory flags are rejected.",
        )
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
        command.add_argument("-U", "--allow-native-unknown", action="store_true",
                             help="Authorize validated generic provider options after `--`.")
        _add_execution_options(command)
        if command_name == "start":
            command.add_argument("-N", "--new", action="store_true", help="Start a new native conversation instead of resuming the selected session.")
            command.add_argument("-r", "--reactivate", action="store_true",
                                 help="Explicitly reactivate an inactive agent before resuming or starting.")

    cont = sub.add_parser(
        "continue", help="Resume the currently selected native session.",
        epilog="Pass supported provider options after `--` (for example: -- --sandbox workspace-write).",
    )
    _add_common_options(cont)
    cont.add_argument("gui_pos", nargs="?")
    cont.add_argument("agent_pos", nargs="?")
    cont.add_argument("-g", "--gui")
    cont.add_argument("-n", "--agent-name", "--name")
    _add_execution_options(cont)
    cont.add_argument("-A", "--all", action="store_true", help="Include completed agents in the interactive picker.")
    cont.add_argument("-p", "--provider", choices=("agy", "codex"), help="Select the most recently activated matching historical provider session.")
    cont.add_argument("-i", "--session-id", help="Select this exact session from the agent's existing history.")
    cont.add_argument("-R", "--reactivate", action="store_true", help="Explicitly reactivate an inactive agent before resuming.")
    cont.add_argument("-C", "--cwd", help="Use this working directory for this invocation only.")
    cont.add_argument("-U", "--allow-native-unknown", action="store_true",
                      help="Authorize validated generic provider options after `--`.")

    review = sub.add_parser(
        "review", help="Open or resume a reviewer agent linked to an original agent.",
        epilog="An empty reviewer slot is initialized automatically; pass -N to replace a selected reviewer session. Use -d to preview.",
    )
    _add_common_options(review)
    review.add_argument("-g", "--gui", required=True)
    review.add_argument("-n", "--agent-name", required=True, help="Original implementation agent.")
    review.add_argument("-R", "--reviewer-agent", required=True, help="Distinct reviewer slot under the same GUI.")
    review.add_argument("-p", "--provider", required=True, choices=("agy", "codex"))
    review.add_argument("-e", "--environment")
    review.add_argument("-C", "--cwd", help="Reviewer working directory.")
    review.add_argument("-U", "--allow-native-unknown", action="store_true",
                        help="Authorize validated generic provider options after `--`.")
    review.add_argument("-N", "--new", action="store_true", help="Start a new reviewer conversation instead of resuming its selected session.")
    _add_execution_options(review)

    returning = sub.add_parser(
        "return", help="Return from an active reviewer cycle to its original agent.",
        epilog="Pass supported provider options after `--` for the exact original session.",
    )
    _add_common_options(returning)
    returning.add_argument("-g", "--gui", required=True)
    returning.add_argument("-n", "--agent-name", required=True, help="Original implementation agent.")
    _add_execution_options(returning)
    returning.add_argument("-C", "--cwd", help="Use this working directory for this invocation only.")
    returning.add_argument("-U", "--allow-native-unknown", action="store_true",
                           help="Authorize validated generic provider options after `--`.")

    opening = sub.add_parser("open", help="Open active selected sessions through terminal_launcher.")
    _add_common_options(opening)
    opening.add_argument("-g", "--gui", required=True)
    opening.add_argument("-k", "--panes-per-tab", type=int, choices=range(1, 5), default=2)
    opening.add_argument("-t", "--terminal", choices=("windows-terminal",), default="windows-terminal")
    opening.add_argument("-w", "--window", help="Windows Terminal window target.")
    _add_execution_options(opening)

    pane = sub.add_parser("pane-run", help=argparse.SUPPRESS)
    _add_common_options(pane)
    pane.add_argument("-s", "--slot-id", required=True)
    pane.add_argument("-L", "--launch-id")
    pane.add_argument("-T", "--launcher-terminal-context", help=argparse.SUPPRESS)
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
    native_args: Sequence[str] = (),
    allow_native_unknown: bool = False,
) -> list[str]:
    validated_native_args = _validated_native_args(provider, native_args, allow_unknown=allow_native_unknown)
    target = _resolve_environment(dispatcher, environment_id)
    environment_id = target.environment_id
    _validate_additional_directories(dispatcher, provider, environment_id, validated_native_args,
                                     allow_native_unknown=allow_native_unknown)
    runtime = detect_runtime_kind()
    provider_args = [provider]
    if session_id:
        provider_args = dispatcher.continuity.adapters[provider].resolve_resume_command(
            session_id, cwd=None if target.runtime_kind == "wsl" else cwd,
            environment_id=environment_id, runtime_kind=target.runtime_kind,
            native_args=validated_native_args,
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
    find_executable = getattr(adapter, "find_executable", None)
    executable_path = find_executable() if callable(find_executable) else adapter.detect_installation().executable_path
    if not executable_path:
        raise ContinuityError(ErrorCode.PROVIDER_UNAVAILABLE, f"{provider} executable was not found on PATH.")
    executable = Path(executable_path)
    if executable.suffix.casefold() in {".cmd", ".bat", ".ps1"}:
        script = executable if executable.suffix.casefold() == ".ps1" else executable.with_suffix(".ps1")
        shell = shutil.which("pwsh")
        if script.is_file() and shell:
            return [shell, "-NoLogo", "-NoProfile", "-File", str(script), *provider_args[1:]]
        raise ContinuityError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            f"{provider} resolves to a Windows script wrapper that cannot be launched safely; install PowerShell 7 or a native executable shim.",
        )
    return [executable_path, *provider_args[1:]]


def _validate_additional_directories(
    dispatcher: DispatcherService, provider: str, environment_id: str, native_args: Sequence[str],
    *, allow_native_unknown: bool = False,
) -> None:
    directories: list[str] = []
    index = 0
    while index < len(native_args):
        token = native_args[index]
        option, equals, value = token.partition("=")
        if option == "--add-dir":
            if not equals and index + 1 < len(native_args):
                index += 1
                value = native_args[index]
            directories.append(value)
        elif provider == "agy" and option == "--settings":
            if not equals and index + 1 < len(native_args):
                index += 1
                value = native_args[index]
            settings = _validate_agy_settings(value, allow_unknown=allow_native_unknown)
            directories.extend(settings.get("additional_directories", []))
        index += 1
    environment = _resolve_environment(dispatcher, environment_id)
    for directory in directories:
        absolute = PurePosixPath(directory).is_absolute() if environment.runtime_kind == "wsl" else ntpath.isabs(directory)
        if not absolute:
            raise ContinuityError(
                ErrorCode.INVALID_INPUT,
                "Provider additional directories must be absolute paths in the selected provider runtime.",
            )
        _validate_cwd_override(dispatcher, environment_id, directory)


def _managed_native_spec(provider: str) -> tuple[dict[str, str], dict[str, str], dict[str, set[str]]]:
    if provider == "codex":
        values = {
            "--sandbox": "sandbox", "-s": "sandbox", "--ask-for-approval": "approval",
            "-a": "approval", "--model": "model", "-m": "model", "--profile": "profile",
            "-p": "profile", "--add-dir": "repeat", "--enable": "repeat", "--disable": "repeat",
            "-c": "config", "--config": "config",
        }
        flags = {"--search": "search", "--no-alt-screen": "flag", "--no-daemon": "flag",
                 "--strict-config": "flag", "--approve-for-me": "auto_approval"}
        enums = {"sandbox": {"read-only", "workspace-write", "danger-full-access"},
                 "approval": {"on-request", "never"}}
    elif provider == "agy":
        values = {"--model": "model", "--effort": "effort", "--add-dir": "repeat",
                  "--agent": "profile", "--settings": "settings"}
        flags = {"--sandbox": "sandbox"}
        enums = {"effort": {"low", "medium", "high", "xhigh", "max"}}
    else:
        raise ContinuityError(ErrorCode.INVALID_INPUT, f"Native options are unsupported for provider {provider!r}.")
    return values, flags, enums


_ALWAYS_FORBIDDEN_NATIVE_OPTIONS = {
    "resume", "exec", "e", "--resume", "--conversation", "--last", "--session-id", "--session",
    "--thread", "--id", "--worktree", "--cd", "-C", "-cdir", "--cwd", "--exec", "--print",
    "-i", "--image", "--prompt", "--prompt-interactive", "--continue", "-continue", "--new-project",
    "--project", "--remote", "--remote-agent", "--remote-control", "--remote-auth-token-env",
    "--local-provider", "--oss", "--dangerously-bypass-approvals-and-sandbox",
    "--dangerously-bypass-hook-trust", "--dangerously-skip-permissions", "--mode", "--output-format",
    "--input-format", "--json-schema", "--print-timeout", "--log-file",
    "-h", "--help", "-V", "--version",
}
_SECRET_KEY_PARTS = ("secret", "token", "password", "api_key", "api-key", "apikey", "credential", "prompt", "content")
_PROTECTED_UNKNOWN_PARTS = (
    "session", "thread", "conversation", "identity", "resume", "worktree", "cwd", "directory",
    "bootstrap", "executable", "provider", "remote", "exec", "print", "output-format", "input-format",
    "danger", "bypass", "skip-permission", "no-approval", "approve-all", "auto-approve",
)


def _validate_managed_or_generic_key(key: str, *, allow_unknown: bool, source: str) -> None:
    normalized = key.strip().casefold()
    if not normalized:
        raise ContinuityError(ErrorCode.INVALID_INPUT, f"{source} key cannot be empty.")
    if any(part in normalized for part in _SECRET_KEY_PARTS):
        raise ContinuityError(ErrorCode.INVALID_INPUT, "Secret, prompt, and credential configuration values are not accepted.")
    if normalized in {"mode", "execution_mode", "execution-mode"} or any(
        part in normalized for part in _PROTECTED_UNKNOWN_PARTS
    ):
        raise ContinuityError(ErrorCode.INVALID_INPUT,
                              f"{source} key {key!r} conflicts with LLMD-owned identity, execution, bootstrap, permission-bypass, or directory controls.")
    if not allow_unknown:
        raise ContinuityError(ErrorCode.INVALID_INPUT,
                              f"Unsupported {source} key {key!r}; use --allow-native-unknown to authorize generic configuration.")


def _config_pair(provider: str, value: str, *, allow_unknown: bool) -> tuple[str, str, str | None]:
    key, separator, setting = value.partition("=")
    normalized = key.strip().casefold()
    if not separator or not normalized or not setting:
        raise ContinuityError(ErrorCode.INVALID_INPUT, "Configuration overrides require KEY=VALUE.")
    if any(part in normalized for part in _SECRET_KEY_PARTS):
        raise ContinuityError(ErrorCode.INVALID_INPUT, "Secret, prompt, and credential configuration values are not accepted.")
    if provider == "codex":
        mapped = {"sandbox_mode": "sandbox", "approval_policy": "approval", "model": "model",
                  "model_reasoning_effort": "reasoning_effort"}
        known = mapped.get(normalized)
        if known is None:
            _validate_managed_or_generic_key(key, allow_unknown=allow_unknown, source="Codex configuration")
        clean = setting.strip().strip('"\'')
        choices = {"sandbox": {"read-only", "workspace-write", "danger-full-access"},
                   "approval": {"on-request", "never"},
                   "reasoning_effort": {"low", "medium", "high", "xhigh", "max"}}
        if known in choices and clean not in choices[known]:
            raise ContinuityError(ErrorCode.INVALID_INPUT, f"Unsupported Codex {key} value {clean!r}.")
        if known == "model" and not clean:
            raise ContinuityError(ErrorCode.INVALID_INPUT, "Codex model configuration cannot be empty.")
        if known == "approval" and clean == "auto-review":
            raise ContinuityError(ErrorCode.INVALID_INPUT, "Use --approve-for-me for Codex automatic review.")
        return key, setting, known
    if provider == "agy":
        raise ContinuityError(ErrorCode.INVALID_INPUT, "AGY configuration uses a managed inline JSON --settings object.")
    raise ContinuityError(ErrorCode.INVALID_INPUT, f"Unsupported provider {provider!r}.")


def _validate_agy_settings(value: str, *, allow_unknown: bool) -> dict[str, Any]:
    try:
        settings = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ContinuityError(ErrorCode.INVALID_INPUT, "AGY --settings requires an inline JSON object, not a file path.") from exc
    if not isinstance(settings, dict):
        raise ContinuityError(ErrorCode.INVALID_INPUT, "AGY --settings requires an inline JSON object.")
    allowed = {"model", "effort", "sandbox", "additional_directories", "agent"}
    for key, setting in settings.items():
        normalized = str(key).casefold()
        if normalized not in allowed:
            _validate_managed_or_generic_key(str(key), allow_unknown=allow_unknown, source="AGY setting")
        if normalized == "effort" and setting not in {"low", "medium", "high", "xhigh", "max"}:
            raise ContinuityError(ErrorCode.INVALID_INPUT, f"Unsupported AGY effort {setting!r}.")
        if normalized == "sandbox" and not isinstance(setting, bool):
            raise ContinuityError(ErrorCode.INVALID_INPUT, "AGY settings sandbox value must be boolean.")
        if normalized == "additional_directories" and (
            not isinstance(setting, list) or not all(isinstance(path, str) and path for path in setting)
        ):
            raise ContinuityError(ErrorCode.INVALID_INPUT, "AGY additional_directories must be a list of nonempty paths.")
    return settings


def _validated_native_args(
    provider: str, native_args: Sequence[str], *, allow_unknown: bool = False
) -> list[str]:
    """Validate managed provider options and explicitly authorized generic argv passthrough."""
    values, flags, enums = _managed_native_spec(provider)
    result: list[str] = []
    seen: set[str] = set()
    index = 0
    while index < len(native_args):
        token = native_args[index]
        if not isinstance(token, str) or not token or "\0" in token:
            raise ContinuityError(ErrorCode.INVALID_INPUT, "Provider options must be nonempty argv strings.")
        option, equals, inline_value = token.partition("=")
        attached_short_value = False
        if provider == "codex" and len(token) > 2 and token[:2] in {"-s", "-a", "-m", "-p", "-c"} and token[2] != "=":
            option, inline_value, attached_short_value = token[:2], token[2:], True
        if token == "--":
            raise ContinuityError(ErrorCode.INVALID_INPUT, "Do not include a second `--` inside provider arguments.")
        if not equals and len(token) > 2 and token[:2] in {"-C", "-i", "-h", "-V"}:
            raise ContinuityError(ErrorCode.INVALID_INPUT,
                                  f"Attached provider option {token!r} conflicts with LLMD-owned cwd/bootstrap identity or help/version mode.")
        normalized_option = option.casefold()
        agy_resume_alias = provider == "agy" and (
            option in {"-c", "-r", "-p", "-i"}
            or (not equals and len(token) > 2 and token[:2] in {"-c", "-r", "-p", "-i"})
        )
        if (option in _ALWAYS_FORBIDDEN_NATIVE_OPTIONS or agy_resume_alias
                or not option.startswith("-")):
            raise ContinuityError(ErrorCode.INVALID_INPUT,
                                  f"LLMD-conflicting provider option {option!r} is reserved for session identity, executable, execution mode, bootstrap, prompt, or cwd ownership.")
        if any(part in normalized_option for part in ("dangerously", "skip-permission", "bypass-approval")):
            raise ContinuityError(ErrorCode.INVALID_INPUT, f"Unsafe permission bypass option {option!r} is forbidden.")
        if normalized_option in {"--mode", "--execution-mode"}:
            raise ContinuityError(ErrorCode.INVALID_INPUT, f"Provider option {option!r} changes execution mode and is reserved by LLMD.")
        if any(part in normalized_option for part in _SECRET_KEY_PARTS):
            raise ContinuityError(ErrorCode.INVALID_INPUT,
                                  f"Provider option {option!r} may carry sensitive data and is not accepted by LLMD.")
        kind = values.get(option)
        flag_kind = flags.get(option)
        if kind is None and flag_kind is None:
            if any(part in normalized_option for part in _PROTECTED_UNKNOWN_PARTS):
                raise ContinuityError(ErrorCode.INVALID_INPUT,
                                      f"Provider option {option!r} conflicts with LLMD-owned identity, execution, bootstrap, permission-bypass, or directory controls.")
            if not allow_unknown:
                raise ContinuityError(ErrorCode.INVALID_INPUT,
                                      f"Unknown {provider} option {option!r}; add --allow-native-unknown before `--` to authorize generic forwarding.")
            if equals and not inline_value:
                raise ContinuityError(ErrorCode.INVALID_INPUT, f"Unknown provider option {option!r} cannot have an empty value.")
            result.append(token)
            if equals:
                index += 1
            elif index + 1 < len(native_args) and isinstance(native_args[index + 1], str) and not native_args[index + 1].startswith("-"):
                result.append(native_args[index + 1])
                index += 1
            index += 1
            continue
        if flag_kind:
            if equals:
                raise ContinuityError(ErrorCode.INVALID_INPUT, f"Provider flag {option} does not accept a value.")
            canonical = "approval" if flag_kind == "auto_approval" else "sandbox" if flag_kind == "sandbox" else option
            if canonical in seen:
                raise ContinuityError(ErrorCode.INVALID_INPUT, f"Provider option {canonical} conflicts with a repeated setting.")
            seen.add(canonical)
            result.append(token)
            index += 1
            continue
        if kind == "repeat":
            canonical = option
        elif kind == "config":
            canonical = "config"
        elif kind == "settings":
            canonical = "settings"
        else:
            canonical = kind
        if canonical != "config" and canonical != "repeat" and canonical in seen:
            raise ContinuityError(ErrorCode.INVALID_INPUT, f"Provider option {canonical} may only be specified once.")
        if kind not in {"repeat", "config"}:
            seen.add(canonical)
        if equals or attached_short_value:
            value = inline_value
            if not value:
                raise ContinuityError(ErrorCode.INVALID_INPUT, f"Provider option {option} requires a value.")
            if attached_short_value:
                result.append(token)
            else:
                result.extend((option, value))
        else:
            index += 1
            if (index >= len(native_args) or not isinstance(native_args[index], str)
                    or not native_args[index] or native_args[index].startswith("-")):
                raise ContinuityError(ErrorCode.INVALID_INPUT, f"Provider option {option} requires a value.")
            value = native_args[index]
            result.extend((token, value))
        if kind in {"sandbox", "approval", "effort"} and value not in enums.get(kind, set()):
            raise ContinuityError(ErrorCode.INVALID_INPUT, f"Unsupported {provider} {kind} setting {value!r}.")
        if kind == "config":
            config_key, _, managed_kind = _config_pair(provider, value, allow_unknown=allow_unknown)
            config_identity = managed_kind or f"config:{config_key.casefold()}"
            if config_identity in seen:
                raise ContinuityError(ErrorCode.INVALID_INPUT, f"Configuration option {config_key!r} is repeated or conflicts with an explicit setting.")
            if managed_kind and managed_kind in seen and managed_kind != "config":
                raise ContinuityError(ErrorCode.INVALID_INPUT, f"Configuration value conflicts with the explicit {managed_kind} option.")
            seen.add(config_identity)
        if kind == "settings":
            settings = _validate_agy_settings(value, allow_unknown=allow_unknown)
            setting_kinds = {"model": "model", "effort": "effort", "sandbox": "sandbox", "agent": "profile"}
            for key in settings:
                setting_kind = setting_kinds.get(key)
                if setting_kind and setting_kind in seen:
                    raise ContinuityError(ErrorCode.INVALID_INPUT,
                                          f"AGY --settings {key!r} conflicts with a separate provider option.")
                if setting_kind:
                    seen.add(setting_kind)
        index += 1
    return result


def _requested_permission_settings(
    provider: str, native_args: Sequence[str], *, allow_unknown: bool = False
) -> dict[str, Any]:
    """Report requested permission-related settings without claiming enforcement."""
    validated = _validated_native_args(provider, native_args, allow_unknown=allow_unknown)
    requested: dict[str, Any] = {}
    index = 0
    while index < len(validated):
        token = validated[index]
        option, equals, inline_value = token.partition("=")
        if provider == "codex" and len(token) > 2 and token[:2] in {"-s", "-a", "-m", "-p", "-c"} and token[2] != "=":
            option, equals, inline_value = token[:2], "=", token[2:]
        value = inline_value if equals else (validated[index + 1] if index + 1 < len(validated) else None)
        canonical = {"-s": "--sandbox", "-a": "--ask-for-approval"}.get(option, option)
        if canonical == "--sandbox":
            requested[canonical] = [value] if provider == "codex" else True
        elif canonical == "--ask-for-approval":
            requested[canonical] = [value]
        elif option == "--approve-for-me":
            requested[option] = True
        elif option in {"-c", "--config"} and value:
            key, config_value, managed = _config_pair(provider, value, allow_unknown=allow_unknown)
            if managed in {"sandbox", "approval"}:
                requested[key] = config_value.strip().strip('"\'')
            elif any(word in key.casefold() for word in ("permission", "approval", "sandbox", "trust", "danger", "bypass")):
                requested.setdefault("unclassified_permission_configuration", []).append(
                    {"key": key, "value": "omitted", "verification": "unclassified and not verified effective"}
                )
        elif option == "--settings" and provider == "agy" and value:
            settings = _validate_agy_settings(value, allow_unknown=allow_unknown)
            if "sandbox" in settings and "--sandbox" not in requested:
                requested["--sandbox"] = settings["sandbox"]
            permission_keys = [
                str(key) for key in settings
                if key not in {"model", "effort", "sandbox", "additional_directories", "agent"}
                and any(word in str(key).casefold() for word in ("permission", "approval", "sandbox", "trust", "danger", "bypass"))
            ]
            if permission_keys:
                requested["unclassified_permission_configuration"] = [
                    {"key": key, "value": "omitted", "verification": "unclassified and not verified effective"}
                    for key in permission_keys
                ]
        if option in {"--add-dir", "--enable", "--disable", "--model", "-m", "--profile", "-p", "--effort", "--agent", "--settings", "-c", "--config"} and not equals:
            index += 2
        else:
            index += 1
    unclassified_permission = [
        option for option in _unknown_native_option_names(provider, validated)
        if any(word in option.casefold() for word in ("permission", "approval", "sandbox", "trust", "danger", "bypass"))
    ]
    if unclassified_permission:
        requested["unclassified_permission_options"] = [
            {"option": option, "value": "omitted", "verification": "unclassified and not verified effective"}
            for option in unclassified_permission
        ]
    return requested


def _unknown_native_option_names(provider: str, native_args: Sequence[str]) -> list[str]:
    values, flags, _ = _managed_native_spec(provider)
    unknown: list[str] = []
    index = 0
    while index < len(native_args):
        token = native_args[index]
        option = token.partition("=")[0]
        if provider == "codex" and len(token) > 2 and token[:2] in {"-s", "-a", "-m", "-p", "-c"} and token[2] != "=":
            index += 1
            continue
        if option not in values and option not in flags and option.startswith("-"):
            unknown.append(option)
            if "=" not in token:
                index += 1
                if index < len(native_args) and not native_args[index].startswith("-"):
                    index += 1
            else:
                index += 1
            continue
        if option in values and "=" not in token:
            index += 2
        else:
            index += 1
    return unknown


def _resolve_environment(dispatcher: DispatcherService, selector: str, *, persist_local: bool = False):
    local = getattr(dispatcher, "_llmd_local_environment", None)
    if local is None or persist_local:
        local = load_or_create_environment(dispatcher.home_dir, persist=persist_local)
        dispatcher._llmd_local_environment = local
    return resolve_environment_selector(selector, dispatcher.materializer.list_environments(), local)


def _git_launch_context(dispatcher: DispatcherService, environment_id: str, cwd: str | None) -> dict[str, str | None]:
    """Observe Git identity in the target runtime without changing repository state."""
    target = _resolve_environment(dispatcher, environment_id)
    runtime = detect_runtime_kind()
    target_cwd = cwd or (None if target.runtime_kind == "wsl" and runtime == "windows" else os.getcwd())
    if not target_cwd:
        return {"git_repository": None, "git_worktree": None, "git_branch": None, "git_commit": None}
    argv = ["git", "-C", target_cwd, "rev-parse", "--path-format=absolute", "--show-toplevel",
            "--git-dir", "--git-common-dir", "--abbrev-ref", "HEAD", "HEAD"]
    if target.runtime_kind == "wsl" and runtime == "windows":
        if not target.distro:
            return {"git_repository": None, "git_worktree": None, "git_branch": None, "git_commit": None}
        wsl = shutil.which("wsl.exe") or shutil.which("wsl")
        if not wsl:
            return {"git_repository": None, "git_worktree": None, "git_branch": None, "git_commit": None}
        argv = [wsl, "--distribution", target.distro, "--exec", *argv]
    elif target.runtime_kind != runtime:
        return {"git_repository": None, "git_worktree": None, "git_branch": None, "git_commit": None}
    try:
        result = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                timeout=3, check=False)
    except (OSError, subprocess.SubprocessError):
        result = None
    values = (result.stdout.splitlines() if result is not None and result.returncode == 0 else [])
    if len(values) < 5:
        return {"git_repository": None, "git_worktree": None, "git_branch": None, "git_commit": None}
    worktree, git_dir, common_dir, branch, commit = values[:5]
    normalized_common = common_dir.replace("\\", "/").rstrip("/")
    repository = normalized_common[:-5] if normalized_common.casefold().endswith("/.git") else worktree
    return {"git_repository": repository, "git_worktree": worktree,
            "git_branch": branch if branch != "HEAD" else None, "git_commit": commit}


def _safe_launch_settings(
    provider: str, native_args: Sequence[str], *, allow_unknown: bool = False
) -> dict[str, Any]:
    """Summarize supported, non-sensitive settings without retaining raw argv."""
    values, flags, _ = _managed_native_spec(provider)
    safe: dict[str, Any] = {}
    index = 0
    while index < len(native_args):
        token = native_args[index]
        option, equals, inline_value = token.partition("=")
        if provider == "codex" and len(token) > 2 and token[:2] in {"-s", "-a", "-m", "-p", "-c"} and token[2] != "=":
            option, equals, inline_value = token[:2], "=", token[2:]
        value = inline_value if equals else (native_args[index + 1] if index + 1 < len(native_args) else None)
        kind = values.get(option)
        flag_kind = flags.get(option)
        if flag_kind == "sandbox":
            safe["sandbox"] = True
        elif flag_kind == "auto_approval":
            safe["approval_policy"] = "auto-review"
        elif flag_kind == "search":
            safe["search"] = True
        elif kind == "sandbox":
            safe["sandbox"] = value
        elif kind == "approval":
            safe["approval_policy"] = value
        elif kind == "model":
            safe["model"] = value
        elif kind == "effort":
            safe["reasoning_effort"] = value
        elif kind == "profile":
            safe["provider_profile"] = value
        elif kind == "repeat" and value:
            key = {"--add-dir": "additional_directories", "--enable": "enabled_features",
                   "--disable": "disabled_features"}.get(option)
            if key:
                safe.setdefault(key, []).append(value)
        elif kind == "config" and value:
            key, setting, managed = _config_pair(provider, value, allow_unknown=allow_unknown)
            mapping = {"sandbox": "sandbox", "approval": "approval_policy", "model": "model",
                       "reasoning_effort": "reasoning_effort"}
            if managed:
                safe[mapping[managed]] = setting.strip().strip('"\'')
            else:
                safe.setdefault("configuration_keys", []).append(key)
        elif kind == "settings" and value:
            settings = _validate_agy_settings(value, allow_unknown=allow_unknown)
            mapping = {"model": "model", "effort": "reasoning_effort", "sandbox": "sandbox",
                       "agent": "provider_profile", "additional_directories": "additional_directories"}
            for key, setting in settings.items():
                field = mapping.get(key)
                if field:
                    safe[field] = setting
                else:
                    safe.setdefault("configuration_keys", []).append(key)
        elif option == "--search":
            safe["search"] = True
        elif allow_unknown and option.startswith("-") and option not in flags and option not in values:
            safe.setdefault("unclassified_native_options", []).append(option)
        if option in values and not equals or option.startswith("-") and allow_unknown and not equals and index + 1 < len(native_args) and not native_args[index + 1].startswith("-"):
            index += 2
        else:
            index += 1
    return safe


def _terminal_launch_record(
    dispatcher: DispatcherService,
    slot: dict[str, Any],
    *,
    provider: str,
    environment_id: str,
    session_id: str | None,
    requested_cwd: str | None,
    effective_cwd: str | None,
    native_cwd: str | None,
    native_args: Sequence[str],
    allow_native_unknown: bool = False,
    launcher_terminal_context: str | None = None,
) -> dict[str, Any] | None:
    raw_terminal_id = launcher_terminal_context or os.environ.get("TERMINAL_SESSION_ID")
    if not raw_terminal_id:
        return None
    try:
        terminal_id = DispatcherService._terminal_uuid(raw_terminal_id)
    except ContinuityError:
        return None
    raw_owner = os.environ.get("TERMINAL_SESSION_OWNER_PID", "")
    owner_pid = raw_owner if raw_owner.isdigit() and int(raw_owner) > 0 else None
    gui = dispatcher._row("SELECT alias FROM dispatcher_gui_conversations WHERE gui_id = ?", (slot["gui_id"],))
    git = _git_launch_context(dispatcher, environment_id, effective_cwd)
    return {
        "launch_id": generate_id("tlaunch"), "terminal_session_id": terminal_id,
        "terminal_session_owner_pid": owner_pid, "gui_id": slot["gui_id"],
        "gui_alias": gui["alias"] if gui else slot.get("gui_alias"), "slot_id": slot["slot_id"],
        "slot_name": slot["name"], "provider": provider, "native_session_id": session_id,
        "environment_id": environment_id, "launch_started_at": now_utc_iso(), "launch_exited_at": None,
        "status": "launching", "exit_code": None, "requested_cwd": requested_cwd,
        "effective_cwd": effective_cwd, "native_cwd": native_cwd, **git,
        "settings": _safe_launch_settings(provider, native_args, allow_unknown=allow_native_unknown),
    }


def _finish_terminal_launch(
    dispatcher: DispatcherService,
    record: dict[str, Any] | None,
    *,
    exit_code: int,
    status: str | None = None,
) -> None:
    if record is None:
        return
    record["launch_exited_at"] = now_utc_iso()
    record["exit_code"] = exit_code
    record["status"] = status or ("exited" if exit_code == 0 else "failed")
    dispatcher.record_terminal_launch(record)


def _repository_root(cwd: str | None) -> str | None:
    if not cwd:
        return None
    path = Path(cwd).expanduser()
    if not path.is_dir():
        return None
    for candidate in (path, *path.parents):
        if (candidate / ".git").exists():
            return str(candidate.resolve())
    return None


def _validate_cwd_override(dispatcher: DispatcherService, environment_id: str, cwd: str | None) -> None:
    if cwd is None:
        return
    environment = _resolve_environment(dispatcher, environment_id)
    runtime = detect_runtime_kind()
    if environment.runtime_kind != runtime:
        if environment.runtime_kind != "wsl" or runtime != "windows":
            raise ContinuityError(ErrorCode.CROSS_ENVIRONMENT_UNAVAILABLE,
                                  f"A cwd override cannot target {environment.runtime_kind} from runtime {runtime!r}.")
        if not cwd.startswith("/"):
            raise ContinuityError(ErrorCode.INVALID_INPUT,
                                  "A Windows-to-WSL cwd override must be an absolute path in the recorded WSL runtime.")
        if not environment.distro:
            raise ContinuityError(ErrorCode.CROSS_ENVIRONMENT_UNAVAILABLE,
                                  "The WSL session has no recorded distribution identity.")
        wsl = shutil.which("wsl.exe") or shutil.which("wsl")
        if not wsl:
            raise ContinuityError(ErrorCode.CROSS_ENVIRONMENT_UNAVAILABLE, "wsl.exe is unavailable for cwd validation.")
        try:
            result = subprocess.run([wsl, "--distribution", environment.distro, "--exec", "test", "-d", cwd],
                                    capture_output=True, check=False)
        except OSError as exc:
            raise ContinuityError(ErrorCode.CROSS_ENVIRONMENT_UNAVAILABLE,
                                  f"Could not validate the WSL working directory: {exc}") from exc
        if result.returncode != 0:
            raise ContinuityError(ErrorCode.INVALID_INPUT, f"Working directory does not exist in WSL: {cwd}")
        return
    if not Path(cwd).expanduser().is_dir():
        raise ContinuityError(ErrorCode.INVALID_INPUT, f"Working directory does not exist: {cwd}")


def _launch_preview(dispatcher: DispatcherService, provider: str, session_id: str, environment_id: str,
                    cwd: str | None, native_args: Sequence[str], *, allow_native_unknown: bool = False) -> dict[str, Any]:
    environment = _resolve_environment(dispatcher, environment_id)
    environment_id = environment.environment_id
    argv = _native_argv(dispatcher, provider, session_id, environment_id=environment_id, cwd=cwd,
                        native_args=native_args, allow_native_unknown=allow_native_unknown)
    requested = _requested_permission_settings(provider, native_args, allow_unknown=allow_native_unknown)
    native = dispatcher.materializer.get_session(provider, environment_id, session_id)
    recorded_root = _repository_root(native.cwd_native if native else None)
    requested_root = _repository_root(cwd) if cwd else recorded_root
    return {
        "executable": argv[0], "argv": argv, "cwd": cwd or (native.cwd_native if native else None),
        "environment": {"id": environment_id, "runtime_kind": environment.runtime_kind,
                        "distro": environment.distro,
                        "ownership": environment_is_locally_owned(dispatcher.home_dir, environment)},
        "selected_session": {"provider": provider, "native_session_id": session_id},
        "repository_context_changed": bool(recorded_root and requested_root and recorded_root != requested_root),
        "permission_settings": {"requested": requested, "verified_effective": None,
                                "verification": "Provider enforcement is not observed by a launch preview."},
        "requested_settings": _safe_launch_settings(provider, native_args, allow_unknown=allow_native_unknown),
        "unknown_native_authorization": {"enabled": allow_native_unknown,
                                         "options": _unknown_native_option_names(provider, native_args)},
        "process_environment": "inherited for this invocation; no environment overrides are persisted",
    }


def _current_native_cwd(dispatcher: DispatcherService, current: dict[str, Any] | None) -> str | None:
    if not current:
        return None
    native = dispatcher.materializer.get_session(
        current["provider"], current["environment_id"], current["native_session_id"]
    )
    return native.cwd_native if native else None


def _render_launch_preview(preview: dict[str, Any], stream: TextIO, color: str | None = None) -> None:
    enabled = color_enabled(color or _current_color_mode(), is_tty=stream.isatty(), stream=stream)
    print(semantic_color("Launch preview", "gui", enabled=enabled) +
          semantic_color(" (requested permissions are not verified as effective):", "warning", enabled=enabled),
          file=stream)
    for line in json.dumps(preview, indent=2, ensure_ascii=False, sort_keys=True).splitlines():
        match = re.match(r'^(\s*)("([^"]+)"\s*:\s*)(.*)$', line)
        if match:
            indent, key_text, key, value = match.groups()
            semantic = "warning" if any(term in key.casefold() for term in ("permission", "sandbox", "approval")) else "label"
            value_semantic = {
                "provider": {"codex": "provider_codex", "agy": "provider_agy"}.get(
                    value.split('"', 2)[1].casefold() if value.startswith('"') and '"' in value[1:] else "", ""),
                "native_session_id": "session",
                "session_id": "session",
            }.get(key, "")
            rendered_value = semantic_color(value, value_semantic, enabled=enabled) if value_semantic else value
            line = indent + semantic_color(key_text, semantic, enabled=enabled) + rendered_value
        print(line, file=stream)


def _new_launch_preview(dispatcher: DispatcherService, provider: str, environment_id: str, cwd: str | None,
                        native_args: Sequence[str], *, allow_native_unknown: bool = False) -> dict[str, Any]:
    requested = _requested_permission_settings(provider, native_args, allow_unknown=allow_native_unknown)
    bootstrap = _bootstrap_native_argv(dispatcher, provider, environment_id=environment_id, cwd=cwd)
    resume = _native_argv(dispatcher, provider, "<captured-session-id>", environment_id=environment_id,
                          cwd=cwd, native_args=native_args, allow_native_unknown=allow_native_unknown)
    environment = _resolve_environment(dispatcher, environment_id)
    environment_id = environment.environment_id
    return {
        "bootstrap_argv": bootstrap,
        "interactive_resume_argv_template": resume,
        "cwd": cwd,
        "environment": {"id": environment_id, "runtime_kind": environment.runtime_kind,
                        "distro": environment.distro,
                        "ownership": environment_is_locally_owned(dispatcher.home_dir, environment)},
        "selected_session": {"provider": provider, "native_session_id": None,
                             "identity": "captured exactly from bootstrap output before resume"},
        "permission_settings": {"requested": requested, "verified_effective": None,
                                "verification": "Provider enforcement is not observed by a launch preview."},
        "requested_settings": _safe_launch_settings(provider, native_args, allow_unknown=allow_native_unknown),
        "unknown_native_authorization": {"enabled": allow_native_unknown,
                                         "options": _unknown_native_option_names(provider, native_args)},
        "process_environment": "inherited for this invocation; no environment overrides are persisted",
    }


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
    native_args: Sequence[str] = (),
    cwd_override: str | None = None,
    expected_session_identity: tuple[str, str, str] | None = None,
    allow_native_unknown: bool = False,
    launcher_terminal_context: str | None = None,
) -> int:
    _startup_progress("provider handoff preparation and exact-session validation")
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
        launch_identity = (provider, environment_id, session_id)
        if expected_session_identity is not None and launch_identity != expected_session_identity:
            raise ContinuityError(ErrorCode.INVALID_INPUT,
                                  "Agent selection changed before provider launch; no session was resumed.")
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
    _validated_native_args(provider, native_args, allow_unknown=allow_native_unknown)
    bootstrap_cwd = cwd
    if cwd_override is not None:
        _validate_cwd_override(dispatcher, environment_id, cwd_override)
    if cwd_override is not None and not launch_id:
        cwd = cwd_override
        process_cwd = None if target_environment and target_environment.runtime_kind == "wsl" and detect_runtime_kind() == "windows" else cwd
    if launch_id:
        process_cwd = None if cross_wsl else cwd
    effective_cwd = cwd if target_environment and target_environment.runtime_kind == "wsl" else (process_cwd or os.getcwd())
    native_record = dispatcher.materializer.get_session(provider, environment_id, session_id) if session_id else None
    terminal_record = _terminal_launch_record(
        dispatcher, slot, provider=provider, environment_id=environment_id, session_id=session_id,
        requested_cwd=cwd_override or (pending.get("cwd") if launch_id else None), effective_cwd=effective_cwd,
        native_cwd=native_record.cwd_native if native_record else None, native_args=native_args,
        allow_native_unknown=allow_native_unknown,
        launcher_terminal_context=launcher_terminal_context,
    )
    terminal_record_written = False
    bootstrap_completed = False
    _startup_progress("environment, executable and Git worktree context resolved")
    try:
        if launch_id:
            bootstrap_argv = _bootstrap_native_argv(
                dispatcher, provider, environment_id=environment_id, cwd=bootstrap_cwd
            )
            if terminal_record:
                dispatcher.record_terminal_launch(terminal_record)
                terminal_record_written = True
            dispatcher.record_process_observation(
                slot_id=slot_id,
                launch_id=launch_id,
                return_code=0,
                outcome="bootstrap_attempt_started",
                detail="Provider bootstrap started; automatic retry is disabled until this launch is resolved.",
            )
            try:
                _startup_progress("fixed read-only bootstrap started; waiting for exact session capture")
                bootstrap = _run_provider_with_progress(
                    bootstrap_argv,
                    label="provider bootstrap",
                    progress_interval=4.0,
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
                _finish_terminal_launch(dispatcher, terminal_record, exit_code=124, status="interrupted")
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
                _finish_terminal_launch(dispatcher, terminal_record, exit_code=1)
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
                _finish_terminal_launch(dispatcher, terminal_record, exit_code=bootstrap.returncode or 1)
                return bootstrap.returncode or 1

            bootstrap_completed = True
            _startup_progress("exact native session captured; persisting identity and activation")
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
                if terminal_record:
                    terminal_record["native_session_id"] = captured_session_id
                _finish_terminal_launch(dispatcher, terminal_record, exit_code=1)
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
                    cwd=bootstrap_cwd, launch_id=launch_id, provenance=transition_source.get("provenance", "agent_transition"),
                    allow_inactive_source=transition_source.get("allow_inactive_source", False),
                    review_cycle=transition_source.get("review_cycle"), apply=True,
                )
            else:
                dispatcher.attach_session(
                    gui=slot["gui_alias"],
                    name=slot["name"],
                    provider=provider,
                    session_id=captured_session_id,
                    environment_selector=environment_id,
                    cwd=bootstrap_cwd,
                    launch_id=launch_id,
                    apply=True,
                    provenance="provider_bootstrap_output",
                )
            if terminal_record:
                terminal_record["native_session_id"] = captured_session_id
                terminal_record["native_cwd"] = bootstrap_cwd
                dispatcher.record_terminal_launch(terminal_record)
            session_id = captured_session_id
            launch_id = None
            launch_identity = (provider, environment_id, session_id)
            if cwd_override is not None:
                cwd = cwd_override
                process_cwd = None if target_environment and target_environment.runtime_kind == "wsl" and detect_runtime_kind() == "windows" else cwd
            argv = _native_argv(dispatcher, provider, session_id, environment_id=environment_id, cwd=cwd,
                                native_args=native_args, allow_native_unknown=allow_native_unknown)
        else:
            argv = _native_argv(dispatcher, provider, session_id, environment_id=environment_id, cwd=cwd,
                                native_args=native_args, allow_native_unknown=allow_native_unknown)
    except ContinuityError as exc:
        if launch_id and bootstrap_completed:
            pending_now = dispatcher._row(
                "SELECT failure_detail FROM dispatcher_pending_launches WHERE launch_id = ? AND status = 'pending'",
                (launch_id,),
            )
            if pending_now is not None and not pending_now["failure_detail"]:
                dispatcher.mark_launch_failed(launch_id=launch_id, detail=str(exc), apply=True)
        if terminal_record_written:
            _finish_terminal_launch(dispatcher, terminal_record, exit_code=1)
        raise
    print(f"Launching {slot['name']}: {provider} {session_id or '(new session)'}", file=output_stream)
    try:
        session_lock = contextlib.nullcontext()
        if session_id:
            lock_key = hashlib.sha256(f"{provider}\0{environment_id}\0{session_id}".encode()).hexdigest()[:24]
            session_lock = _session_runtime_lock(dispatcher, f"session-{lock_key}.lock", blocking=False)
        with session_lock:
            if session_id:
                latest = dispatcher.get_slot_by_id(slot_id)
                if _session_identity(latest) != launch_identity:
                    raise ContinuityError(ErrorCode.INVALID_INPUT,
                                          "Agent selection changed before provider launch; retry with the selected session.")
            if terminal_record and not terminal_record_written:
                dispatcher.record_terminal_launch(terminal_record)
                terminal_record_written = True
            _startup_progress("interactive provider handoff")
            _STARTUP_PROGRESS.set(False)
            result = subprocess.run(argv, cwd=process_cwd, check=False)
    except KeyboardInterrupt:
        if launch_id:
            dispatcher.mark_launch_failed(launch_id=launch_id, detail="Provider launch was interrupted; inspect provider state before retrying.", apply=True)
        _finish_terminal_launch(dispatcher, terminal_record, exit_code=130, status="interrupted")
        raise
    except ContinuityError:
        if terminal_record_written:
            _finish_terminal_launch(dispatcher, terminal_record, exit_code=1, status="failed")
        raise
    except OSError as exc:
        if launch_id:
            dispatcher.mark_launch_failed(launch_id=launch_id, detail=str(exc), apply=True)
        elif session_id:
            dispatcher.record_process_observation(
                slot_id=slot_id, launch_id=None, return_code=-1, outcome="spawn_failed",
                session_identity=(provider, environment_id, session_id),
            )
        _finish_terminal_launch(dispatcher, terminal_record, exit_code=1, status="spawn_failed")
        raise ContinuityError(ErrorCode.PROVIDER_UNAVAILABLE, f"Failed to launch {provider}: {exc}") from exc
    _finish_terminal_launch(dispatcher, terminal_record, exit_code=result.returncode,
                            status="exited" if result.returncode == 0 else "abnormal_exit")
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
        print(semantic_color(f"{slot['name']} exited with code {result.returncode}; slot and current session remain unchanged.",
                             "error", enabled=color_enabled(_current_color_mode(), is_tty=output_stream.isatty(),
                                                            stream=output_stream)), file=output_stream)
        return result.returncode
    opposite_provider = "agy" if provider == "codex" else "codex"
    use_color = color_enabled(_current_color_mode(), is_tty=output_stream.isatty(), stream=output_stream)
    while True:
        print(f"\n{semantic_color(slot['name'], 'agent', enabled=use_color)} "
              f"{outcome_semantic('has exited successfully', enabled=use_color)}\n"
              f"[1] Keep {state_color('active', enabled=use_color)} (default)\n"
              f"[2] Mark {state_color('completed', enabled=use_color)}\n"
              f"[3] Mark {state_color('inactive', enabled=use_color)}\n"
              f"[4] Switch to {provider_semantic(opposite_provider, enabled=use_color)}\n"
              f"[5] Switch to an existing agent\n[6] Create a new agent", file=output_stream)
        try:
            choice = input_stream.readline().strip()
        except (EOFError, OSError):
            choice = ""
        if choice == "4":
            result = _switch_after_exit(dispatcher, slot, opposite_provider,
                                        input_stream=input_stream, output_stream=output_stream,
                                        native_args=native_args, cwd_override=cwd_override,
                                        launcher_terminal_context=launcher_terminal_context)
            if result is None:
                continue
            if show_summary:
                _render_scoped_summary(dispatcher, slot, output_stream)
            return result
        if choice == "5":
            result = _switch_to_existing_agent(dispatcher, slot, input_stream=input_stream,
                                               output_stream=output_stream, native_args=native_args,
                                               cwd_override=cwd_override,
                                               launcher_terminal_context=launcher_terminal_context)
            if show_summary:
                _render_scoped_summary(dispatcher, slot, output_stream)
            return result
        if choice == "6":
            result = _create_agent_after_exit(dispatcher, slot, input_stream=input_stream,
                                              output_stream=output_stream, native_args=native_args,
                                              cwd_override=cwd_override,
                                              launcher_terminal_context=launcher_terminal_context)
            if show_summary:
                _render_scoped_summary(dispatcher, slot, output_stream)
            return result
        break
    state = {"2": "completed", "3": "inactive"}.get(choice, "active")
    if state != "active":
        dispatcher.set_slot_state(gui=slot["gui_alias"], name=slot["name"], state=state, apply=True)
    if show_summary:
        _render_scoped_summary(dispatcher, slot, output_stream)
    return 0


def _render_scoped_summary(dispatcher: DispatcherService, slot: dict[str, Any], stream: TextIO) -> None:
    args = argparse.Namespace(gui_pos=None, gui=slot["gui_alias"], limit=None, all=True,
                              history_count=0)
    _render_listing(_listing(dispatcher, args), stream, _current_color_mode(), dispatcher=dispatcher)


def _switch_after_exit(
    dispatcher: DispatcherService,
    slot: dict[str, Any],
    provider: str,
    *,
    input_stream: TextIO,
    output_stream: TextIO,
    native_args: Sequence[str] = (),
    cwd_override: str | None = None,
    launcher_terminal_context: str | None = None,
) -> int | None:
    """Switch the exited slot to an exact prior provider session or explicitly new one."""
    expected_current = _session_identity(slot)
    if expected_current is None:
        raise ContinuityError(ErrorCode.INVALID_INPUT,
                              "Provider switch requires an exact current session; no launch was reserved.")
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
                return None
        else:
            print("Provider switch canceled; current selection and history were unchanged.", file=output_stream)
            return None
    elif not _ask_confirmation(input_stream, output_stream,
                               f"No previous {provider.upper()} session is registered. Start a new conversation?",
                               default=False):
        print("Provider switch canceled; current selection and history were unchanged.", file=output_stream)
        return None

    if target:
        _provider_environment(dispatcher, target["environment_id"])
        destination = {"provider": target["provider"], "environment_id": target["environment_id"],
                       "native_session_id": target["native_session_id"]}
        overrides = _select_post_exit_overrides(
            dispatcher, provider=target["provider"], environment_id=target["environment_id"],
            recorded_cwd=_current_native_cwd(dispatcher, destination), native_args=native_args,
            cwd_override=cwd_override, input_stream=input_stream, output_stream=output_stream,
        )
        if overrides is None:
            return None
        destination_args, destination_cwd = overrides
        if destination_cwd:
            _validate_cwd_override(dispatcher, target["environment_id"], destination_cwd)
        preview = _launch_preview(dispatcher, target["provider"], target["native_session_id"], target["environment_id"],
                                  destination_cwd or _current_native_cwd(dispatcher, destination), destination_args)
        if destination_args:
            _render_launch_preview(preview, output_stream)
        dispatcher.attach_session(
            gui=slot["gui_alias"], name=slot["name"], provider=target["provider"],
            session_id=target["native_session_id"], environment_selector=target["environment_id"],
            expected_current=expected_current, check_current=True,
            apply=True, provenance="post_exit_provider_switch",
        )
        current = dispatcher.get_slot(gui=slot["gui_alias"], name=slot["name"])
        return _run_pane(dispatcher, slot_id=current["slot_id"], launch_id=None,
                         input_stream=input_stream, output_stream=output_stream, show_summary=False,
                         native_args=destination_args, cwd_override=destination_cwd,
                         expected_session_identity=(target["provider"], target["environment_id"],
                                                    target["native_session_id"]),
                         launcher_terminal_context=launcher_terminal_context)

    environment_id = expected_current[1]
    _provider_environment(dispatcher, environment_id)
    native = dispatcher.materializer.get_session(*expected_current)
    cwd = native.cwd_native if native else None
    overrides = _select_post_exit_overrides(
        dispatcher, provider=provider, environment_id=environment_id, recorded_cwd=cwd,
        native_args=native_args, cwd_override=cwd_override,
        input_stream=input_stream, output_stream=output_stream,
    )
    if overrides is None:
        return None
    destination_args, destination_cwd = overrides
    effective_cwd = destination_cwd or cwd
    if destination_cwd:
        _validate_cwd_override(dispatcher, environment_id, destination_cwd)
    preview = _new_launch_preview(dispatcher, provider, environment_id, effective_cwd, destination_args)
    if destination_args:
        _render_launch_preview(preview, output_stream)
    launch = dispatcher.begin_launch(
        gui=slot["gui_alias"], name=slot["name"], provider=provider,
        cwd=effective_cwd, environment_selector=environment_id, expected_current=expected_current,
        check_current=True, apply=True,
    )
    return _run_pane(dispatcher, slot_id=slot["slot_id"], launch_id=launch["details"]["launch_id"],
                     input_stream=input_stream, output_stream=output_stream, show_summary=False,
                     native_args=destination_args, launcher_terminal_context=launcher_terminal_context)


def _select_post_exit_overrides(
    dispatcher: DispatcherService,
    *,
    provider: str,
    environment_id: str,
    recorded_cwd: str | None,
    native_args: Sequence[str],
    cwd_override: str | None,
    input_stream: TextIO,
    output_stream: TextIO,
) -> tuple[list[str], str | None] | None:
    """Require an explicit destination-scoped choice before reusing source invocation overrides."""
    if not native_args and cwd_override is None:
        return [], None
    details = []
    if cwd_override is not None:
        details.append(f"-C {cwd_override}")
    if native_args:
        details.append("provider argv " + repr(list(native_args)))
    try:
        destination_args = _validated_native_args(provider, native_args)
    except ContinuityError:
        print("The departing session's " + " and ".join(details)
              + f" cannot be applied to {provider.upper()}. The destination keeps its recorded working directory "
                "and provider defaults. Continue with those defaults? [y/N] ",
              end="", file=output_stream, flush=True)
        answer = input_stream.readline().strip().casefold()
        return ([], None) if answer in {"y", "yes"} else None

    print("The departing session's " + " and ".join(details)
          + f" are invocation-scoped. {provider.upper()} destination uses recorded environment {environment_id!r} "
            f"and working directory {recorded_cwd!r} by default.", file=output_stream)
    print("[o] Apply these overrides to the destination  [d] Use destination defaults  [c] Cancel: ",
          end="", file=output_stream, flush=True)
    choice = input_stream.readline().strip().casefold()
    if choice in {"d", "defaults"}:
        return [], None
    if choice not in {"o", "override", "overrides"}:
        return None
    if cwd_override:
        _validate_cwd_override(dispatcher, environment_id, cwd_override)
    return destination_args, cwd_override


def _session_identity(slot: dict[str, Any]) -> tuple[str, str, str] | None:
    current = slot.get("current")
    if not current:
        return None
    return current["provider"], current["environment_id"], current["native_session_id"]


def _provider_environment(dispatcher: DispatcherService, environment_id: str):
    environment = next((item for item in dispatcher.materializer.list_environments()
                         if item.environment_id == environment_id), None)
    if environment is None:
        raise ContinuityError(ErrorCode.ENVIRONMENT_NOT_FOUND,
                              "The selected session environment is not registered; provider switch was not started.")
    runtime = detect_runtime_kind()
    if environment.runtime_kind == "wsl":
        if not environment.distro:
            raise ContinuityError(ErrorCode.CROSS_ENVIRONMENT_UNAVAILABLE,
                                  "The selected WSL environment has no recorded distribution identity.")
        if runtime == "windows":
            if not (shutil.which("wsl.exe") or shutil.which("wsl")):
                raise ContinuityError(ErrorCode.CROSS_ENVIRONMENT_UNAVAILABLE,
                                      "Cannot switch to the recorded WSL environment because wsl.exe is unavailable.")
        elif runtime == "wsl":
            local_distro = os.environ.get("WSL_DISTRO_NAME")
            if not local_distro or local_distro.casefold() != environment.distro.casefold():
                raise ContinuityError(ErrorCode.CROSS_ENVIRONMENT_UNAVAILABLE,
                                      "The selected WSL session belongs to a different or unknown distribution.")
        else:
            raise ContinuityError(ErrorCode.CROSS_ENVIRONMENT_UNAVAILABLE,
                                  f"Cannot launch the selected WSL environment from runtime {runtime!r}.")
    elif environment.runtime_kind != runtime:
        raise ContinuityError(ErrorCode.CROSS_ENVIRONMENT_UNAVAILABLE,
                              f"Cannot launch the selected {environment.runtime_kind} environment from runtime {runtime!r}.")
    return environment


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
    native_args: Sequence[str] = (),
    cwd_override: str | None = None,
    launcher_terminal_context: str | None = None,
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
        row["runtime_status"] = _runtime_label(dispatcher, str(row.get("current_provider") or "UNKNOWN"),
                                               row.get("current_environment_id"), row.get("current_session_id"))
    selector_color = color_enabled(_current_color_mode(), is_tty=output_stream.isatty(), stream=output_stream)
    action, selected = select_item(
        rows, title=f"LLMD — Switch agent in {source['gui_alias']}",
        render_line=lambda row: _agent_selector_line(row, shutil.get_terminal_size((100, 24)).columns,
                                                     enabled=selector_color),
        header=lambda: _agent_selector_line({}, shutil.get_terminal_size((100, 24)).columns, header=True,
                                             enabled=selector_color),
        input_stream=input_stream, output_stream=output_stream, filter_key="search_text",
        color_mode=_current_color_mode(),
    )
    if action != "selected" or selected is None:
        return 0
    destination = dispatcher.get_slot(gui=source["gui_alias"], name=selected["slot_id"])
    if destination["state"] != "inactive" or not destination["current"]:
        print("Destination is no longer inactive with a selected session; no slot state changed.", file=output_stream)
        return 2
    current = destination["current"]
    destination_identity = (current["provider"], current["environment_id"], current["native_session_id"])
    destination_cwd = _current_native_cwd(dispatcher, current)
    overrides = _select_post_exit_overrides(
        dispatcher, provider=current["provider"], environment_id=current["environment_id"],
        recorded_cwd=destination_cwd, native_args=native_args, cwd_override=cwd_override,
        input_stream=input_stream, output_stream=output_stream,
    )
    if overrides is None:
        return 0
    destination_args, destination_cwd_override = overrides
    if destination_cwd_override:
        _validate_cwd_override(dispatcher, current["environment_id"], destination_cwd_override)
    preview = _launch_preview(dispatcher, current["provider"], current["native_session_id"], current["environment_id"],
                              destination_cwd_override or destination_cwd, destination_args)
    if destination_args:
        _render_launch_preview(preview, output_stream)
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
        destination_state = "active"
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
                     input_stream=input_stream, output_stream=output_stream, show_summary=False,
                     native_args=destination_args, cwd_override=destination_cwd_override,
                     expected_session_identity=destination_identity,
                     launcher_terminal_context=launcher_terminal_context)


def _create_agent_after_exit(
    dispatcher: DispatcherService,
    source: dict[str, Any],
    *,
    input_stream: TextIO,
    output_stream: TextIO,
    native_args: Sequence[str] = (),
    cwd_override: str | None = None,
    launcher_terminal_context: str | None = None,
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
    overrides = _select_post_exit_overrides(
        dispatcher, provider=provider, environment_id="local", recorded_cwd=str(cwd),
        native_args=native_args, cwd_override=None,
        input_stream=input_stream, output_stream=output_stream,
    )
    if overrides is None:
        print("New agent canceled; no slot or provider launch was created.", file=output_stream)
        return 0
    destination_args, _ = overrides
    if cwd_override:
        print(f"The departing session's -C {cwd_override!r} is not inherited; the new agent will use {str(cwd)!r}.",
              file=output_stream)
    if not _ask_confirmation(input_stream, output_stream,
                             f"Create {name!r} under {source['gui_alias']!r}, initialize {provider.upper()} in {cwd}, and switch to it?",
                             default=False):
        print("New agent canceled; no slot or provider launch was created.", file=output_stream)
        return 0
    _validate_cwd_override(dispatcher, "local", str(cwd))
    preview = _new_launch_preview(dispatcher, provider, "local", str(cwd), destination_args)
    if destination_args:
        _render_launch_preview(preview, output_stream)
    launch = dispatcher.prepare_start(gui=source["gui_alias"], name=name, provider=provider,
                                       cwd=str(cwd), apply=True)
    return _run_pane(
        dispatcher, slot_id=launch["details"]["slot_id"], launch_id=launch["details"]["launch_id"],
        input_stream=input_stream, output_stream=output_stream, show_summary=False,
        native_args=destination_args,
        transition_source={"slot_id": source["slot_id"], "expected_source": _session_identity(source),
                          "source_state": "inactive", "destination_state": "active",
                          "provenance": "post_exit_new_agent"},
        launcher_terminal_context=launcher_terminal_context,
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
            input_stream: TextIO, output_stream: TextIO, *, native_args: Sequence[str] = (),
            allow_native_unknown: bool = False) -> int:
    original = dispatcher.get_slot(gui=args.gui, name=args.agent_name)
    if original["state"] not in {"active", "inactive"} or original["current"] is None:
        raise ContinuityError(ErrorCode.INVALID_INPUT,
                              "Review requires an active or inactive original with an exact selected session.")
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
    if args.cwd:
        _validate_cwd_override(dispatcher,
                               reviewer_identity[1] if reviewer_identity and not args.new else (args.environment or "local"),
                               args.cwd)
    create_reviewer = bool(args.new or reviewer_identity is None)
    if create_reviewer:
        preview = _new_launch_preview(dispatcher, args.provider, args.environment or "local", args.cwd, native_args,
                                      allow_native_unknown=allow_native_unknown)
        if not args.apply:
            if getattr(args, "json_output", False):
                print(json.dumps({"action": "review", "applied": False, "launch_preview": preview}, indent=2), file=output_stream)
            else:
                _render_launch_preview(preview, output_stream)
                print("Dry-run only; an empty reviewer slot initializes automatically. Use -N to replace a selected reviewer session.",
                      file=output_stream)
            return 0
    else:
        if reviewer_identity[0] != args.provider:
            raise ContinuityError(ErrorCode.INVALID_INPUT,
                                  "Reviewer provider differs from its selected session; use -N to start a new reviewer conversation.")
        if _session_in_use(dispatcher, *reviewer_identity):
            raise ContinuityError(ErrorCode.INVALID_INPUT, "Reviewer session is already in use.")
        preview = _launch_preview(dispatcher, reviewer_identity[0], reviewer_identity[2], reviewer_identity[1],
                                  args.cwd or _current_native_cwd(dispatcher, reviewer["current"]), native_args,
                                  allow_native_unknown=allow_native_unknown)
        if not args.apply:
            if getattr(args, "json_output", False):
                print(json.dumps({"action": "review", "applied": False, "launch_preview": preview}, indent=2), file=output_stream)
            else:
                _render_launch_preview(preview, output_stream)
            return 0
    if create_reviewer:
        if native_args:
            _render_launch_preview(preview, output_stream)
        _startup_progress("reserving reviewer bootstrap and review-cycle intent")
        prepared = dispatcher.prepare_start(
            gui=args.gui, name=args.reviewer_agent, provider=args.provider, cwd=args.cwd,
            environment_selector=args.environment, expected_current=reviewer_identity,
            reactivate=bool(reviewer and reviewer["state"] == "inactive"), defer_reactivate=True, apply=True,
        )
        target_slot_id = prepared["details"]["slot_id"]
        _startup_progress("reviewer launch reservation committed")
        cycle = _review_cycle_payload(original, target_slot_id, status="pending")
        dispatcher.record_pending_review_cycle(gui=args.gui, cycle=cycle,
                                              expected_original=original_identity,
                                              allow_inactive_original=original["state"] == "inactive", apply=True)
        return _run_pane(
            dispatcher, slot_id=target_slot_id, launch_id=prepared["details"]["launch_id"],
            input_stream=input_stream, output_stream=output_stream,
            native_args=native_args,
            allow_native_unknown=allow_native_unknown,
            transition_source={"slot_id": original["slot_id"], "expected_source": original_identity,
                              "review_cycle": {**cycle, "status": "active"},
                              "allow_inactive_source": original["state"] == "inactive",
                              "provenance": "reviewer_bootstrap"},
        )
    cycle = _review_cycle_payload(original, reviewer["slot_id"], reviewer["current"])
    dispatcher.complete_agent_transition(
        gui=args.gui, source_slot_id=original["slot_id"], destination_slot_id=reviewer["slot_id"],
        provider=reviewer_identity[0], environment_id=reviewer_identity[1], session_id=reviewer_identity[2],
        source_state="inactive", destination_state="active", expected_source=original_identity,
        expected_destination=reviewer_identity, cwd=dispatcher.current_working_directory(reviewer),
        allow_inactive_source=original["state"] == "inactive",
        provenance="reviewer_resume", review_cycle=cycle, apply=True,
    )
    latest = dispatcher.get_slot(gui=args.gui, name=reviewer["slot_id"])
    return _run_pane(dispatcher, slot_id=latest["slot_id"], launch_id=None,
                     input_stream=input_stream, output_stream=output_stream,
                     native_args=native_args, cwd_override=args.cwd,
                     allow_native_unknown=allow_native_unknown)


def _return(dispatcher: DispatcherService, args: argparse.Namespace,
            input_stream: TextIO, output_stream: TextIO, *, native_args: Sequence[str] = (),
            allow_native_unknown: bool = False) -> int:
    original = dispatcher.get_slot(gui=args.gui, name=args.agent_name)
    cycle = dispatcher.active_review_cycle(slot_id=original["slot_id"])
    if not cycle or cycle["original_slot_id"] != original["slot_id"]:
        raise ContinuityError(ErrorCode.INVALID_INPUT, "No active reviewer cycle is linked to this original agent.")
    reviewer = dispatcher.get_slot(gui=args.gui, name=cycle["reviewer_slot_id"])
    reviewer_identity = _session_identity(reviewer)
    original_identity = (cycle["original_provider"], cycle["original_environment_id"], cycle["original_session_id"])
    if reviewer_identity is None or _session_identity(original) != original_identity:
        raise ContinuityError(ErrorCode.INVALID_INPUT, "Original or reviewer session changed; return was not applied.")
    cwd_override = getattr(args, "cwd", None)
    if cwd_override:
        _validate_cwd_override(dispatcher, original_identity[1], cwd_override)
    preview = _launch_preview(dispatcher, original_identity[0], original_identity[2], original_identity[1],
                              cwd_override or _current_native_cwd(dispatcher, original["current"]), native_args,
                              allow_native_unknown=allow_native_unknown)
    if not args.apply:
        if getattr(args, "json_output", False):
            print(json.dumps({"action": "return", "applied": False, "launch_preview": preview}, indent=2), file=output_stream)
        else:
            _render_launch_preview(preview, output_stream)
        return 0
    if _session_in_use(dispatcher, *reviewer_identity) or _session_in_use(dispatcher, *original_identity):
        raise ContinuityError(ErrorCode.INVALID_INPUT, "A review session is in use; return was not applied.")
    if native_args:
        _render_launch_preview(preview, output_stream)
    dispatcher.complete_agent_transition(
        gui=args.gui, source_slot_id=reviewer["slot_id"], destination_slot_id=original["slot_id"],
        provider=original_identity[0], environment_id=original_identity[1], session_id=original_identity[2],
        source_state="inactive", destination_state="active", expected_source=reviewer_identity,
        expected_destination=original_identity, cwd=dispatcher.current_working_directory(original),
        provenance="review_return", review_cycle={**cycle, "status": "returned"}, apply=True,
    )
    selected = dispatcher.get_slot(gui=args.gui, name=original["slot_id"])
    return _run_pane(dispatcher, slot_id=selected["slot_id"], launch_id=None,
                     input_stream=input_stream, output_stream=output_stream,
                     native_args=native_args, cwd_override=cwd_override,
                     allow_native_unknown=allow_native_unknown)


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


def _continue_picker_line(row: dict[str, Any], width: int, *, enabled: bool) -> str:
    gui = semantic_color(clip_display(str(row.get("gui_alias") or "(unknown GUI)"), max(4, width // 4)),
                         "gui", enabled=enabled)
    name = semantic_color(clip_display(str(row.get("name") or "(unnamed)"), max(8, width // 3)),
                          "agent", enabled=enabled)
    provider = provider_semantic(str(row.get("provider") or "UNKNOWN"), enabled=enabled)
    lifecycle = state_color(str(row.get("state") or "unknown"), enabled=enabled)
    runtime = runtime_semantic(str(row.get("runtime_status") or "UNKNOWN"), enabled=enabled)
    session = str(row.get("current_session_id") or ("<pending>" if row.get("pending_launch_id") else "<unresolved>"))
    prefix = f"{gui} / {name}  {provider}  {lifecycle}"
    if width >= 92:
        used = display_width(prefix) + 2 + display_width(runtime) + 2
        return f"{prefix}  {runtime}  {semantic_color(clip_display(session, max(1, width - used)), 'session', enabled=enabled)}"
    return (f"{clip_display(str(row.get('gui_alias') or '(unknown GUI)'), max(4, width // 4))} / "
            f"{clip_display(str(row.get('name') or '(unnamed)'), max(8, width // 3))}\n"
            f"    {provider}  {lifecycle}  {runtime}\n"
            f"    {semantic_color(clip_display(session, max(1, width - 6)), 'session', enabled=enabled)}")


def _run_picker(dispatcher: DispatcherService, args: argparse.Namespace, input_stream: TextIO, output_stream: TextIO,
                *, native_args: Sequence[str] = (), allow_native_unknown: bool = False) -> int:
    if not (input_stream.isatty() and output_stream.isatty()):
        raise ContinuityError(ErrorCode.INVALID_INPUT, "`llmd continue` without an agent requires an interactive terminal.")
    from .interactive import select_item
    items = _continue_items(dispatcher, args.gui, include_completed=args.all)
    if not items:
        print("No eligible agents have a resumable session.", file=output_stream)
        return 0
    picker_color = color_enabled(getattr(args, "color", "auto"), is_tty=output_stream.isatty(),
                                 stream=output_stream)
    action, item = select_item(items, title="LLMD — Resume Agent",
        render_line=lambda row: _continue_picker_line(row, shutil.get_terminal_size((100, 24)).columns,
                                                     enabled=picker_color),
        input_stream=input_stream, output_stream=output_stream, filter_key="search_text",
        color_mode=getattr(args, "color", "auto"))
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
    current = item.get("current") or {}
    provider = item.get("provider") or current.get("provider")
    environment_id = item.get("current_environment_id") or current.get("environment_id")
    session_id = item.get("current_session_id") or current.get("native_session_id")
    expected_identity = (provider, environment_id, session_id)
    latest_slot = dispatcher.get_slot_by_id(item["slot_id"])
    if _session_identity(latest_slot) != expected_identity:
        raise ContinuityError(ErrorCode.INVALID_INPUT,
                              "Agent selection changed while the picker was open; no session was resumed.")
    cwd_override = getattr(args, "cwd", None)
    if cwd_override:
        _validate_cwd_override(dispatcher, environment_id, cwd_override)
    preview = _launch_preview(dispatcher, provider, session_id,
                              environment_id, cwd_override or _current_native_cwd(dispatcher, current), native_args,
                              allow_native_unknown=allow_native_unknown)
    if not args.apply:
        _render_launch_preview(preview, output_stream)
        return 0
    if item["state"] == "inactive":
        print("Inactive agent selected. Confirm reactivation? [y/N] ", end="", file=output_stream, flush=True)
        if input_stream.readline().strip().casefold() not in {"y", "yes"}:
            return 0
    if args.apply and native_args:
        _render_launch_preview(preview, output_stream)
    if not args.apply:
        print("Dry-run: pass -a/--apply to resume this session.", file=output_stream)
        return 0
    if _session_in_use(dispatcher, provider, environment_id, session_id):
        print("This session is already in use by an LLMD-managed process.", file=output_stream)
        return 2
    dispatcher.attach_session(
        gui=item["gui_alias"], name=item["name"], provider=provider, session_id=session_id,
        environment_selector=environment_id, expected_current=expected_identity, check_current=True,
        reactivate=item["state"] == "inactive", apply=True, provenance="continue_picker",
    )
    return _run_pane(dispatcher, slot_id=item["slot_id"], launch_id=None, input_stream=input_stream,
                     output_stream=output_stream, native_args=native_args, cwd_override=cwd_override,
                     expected_session_identity=expected_identity, allow_native_unknown=allow_native_unknown)


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
    panes = []
    for item in request["panes"]:
        launcher_context = str(uuid4())
        item["argv"] = [*item["argv"], "-T", launcher_context]
        panes.append(PaneSpec(title=item["title"], argv=tuple(item["argv"]), cwd=item.get("cwd")))
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


def _render_doctor_report(report: dict[str, Any], stream: TextIO, color: str = "auto") -> None:
    enabled = color_enabled(color, is_tty=stream.isatty(), stream=stream)
    registry = report["registry"]
    database = registry["database"]
    print(semantic_color("LLMD Doctor", "gui", enabled=enabled), file=stream)
    registry_state = "accessible" if registry["accessible"] else "unavailable"
    print(f"{semantic_color('Registry:', 'label', enabled=enabled)} "
          f"{semantic_color(registry_state, 'success' if registry['accessible'] else 'error', enabled=enabled)} ({registry['home']})", file=stream)
    print(f"{semantic_color('Registry integrity:', 'label', enabled=enabled)} "
          f"{outcome_semantic(database.get('integrity') or 'unknown', enabled=enabled)}", file=stream)
    if database.get("diagnostic_error"):
        print(f"  {semantic_color('Diagnostic error:', 'error', enabled=enabled)} {database['diagnostic_error']}", file=stream)
    print(f"{semantic_color('Registry lock:', 'label', enabled=enabled)} {registry['mutation_lock']}", file=stream)
    print(semantic_color("Agents:", "label", enabled=enabled), file=stream)
    if not report["agents"]:
        print("  No matching agents.", file=stream)
    for agent in report["agents"]:
        provider = (agent.get("provider") or "unassigned").upper()
        session = agent.get("session_id") or "no selected session"
        print(f"  {semantic_color(agent['gui'], 'gui', enabled=enabled)} / {semantic_color(agent['name'], 'agent', enabled=enabled)}  "
              f"{provider_semantic(provider, enabled=enabled)}  {state_color(str(agent['lifecycle']), enabled=enabled)}  "
              f"{runtime_semantic(str(agent['runtime']), enabled=enabled)}", file=stream)
        print(f"    {semantic_color('Session:', 'label', enabled=enabled)} {semantic_color(session, 'session', enabled=enabled)}; "
              f"duplicate resume: {outcome_semantic(str(agent['duplicate_resume']), enabled=enabled)}", file=stream)
    print(semantic_color("Pending launches:", "label", enabled=enabled), file=stream)
    if not report["pending_launches"]:
        print("  None.", file=stream)
    for pending in report["pending_launches"]:
        captured = pending.get("captured_session_id") or "no captured session ID"
        print(f"  {pending['launch_id']}  {provider_semantic(str(pending.get('provider', 'unknown')), enabled=enabled)}  "
              f"{semantic_color(captured, 'session', enabled=enabled)}", file=stream)
    print(semantic_color("Inconsistencies:", "label", enabled=enabled), file=stream)
    if not report["inconsistencies"]:
        print("  None positively established.", file=stream)
    for issue in report["inconsistencies"]:
        print(f"  {semantic_color(issue['kind'], 'error', enabled=enabled)}: {issue['detail']}", file=stream)
    print(semantic_color("Limitations:", "label", enabled=enabled), file=stream)
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
        gui_record = next((item for item in dispatcher.list_guis()
                           if item['alias'].casefold() == gui.casefold()), None)
        return {'action': 'list', 'gui': gui,
                'last_activity_at': gui_record.get('last_activity_at') if gui_record else None,
                'slots': selected, 'total': total,
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
    use_color = color_enabled(color, is_tty=stream.isatty(), stream=stream)
    width = shutil.get_terminal_size((100, 24)).columns
    all_rows = (result.get("slots", []) if "conversations" not in result else
                [row for conversation in result["conversations"] for row in conversation.get("slots", [])])
    longest_session = max((display_width(str(row.get("current_session_id") or
                                             ("<pending>" if row.get("pending_launch_id") else "<unresolved>")))
                           for row in all_rows), default=12)
    # Reserve enough cells for the widest real session identity in this result,
    # then allocate remaining room to names. This keeps 36-cell UUIDs intact at
    # 120 columns without imposing a fixed name/session split on every listing.
    max_table_session = max(8, width - 69)
    session_width = min(longest_session, max_table_session)
    name_width = max(12, min(32, width - 57 - session_width))
    wide_table = width >= 104 and longest_session <= max_table_session

    def print_header() -> None:
        if not wide_table:
            return
        print("  " + pad_semantic("Agent", name_width, "label", enabled=use_color) + "  " +
              pad_semantic("Provider", 8, "label", enabled=use_color) + "  " +
              pad_semantic("Last activity", 16, "label", enabled=use_color) + "  " +
              pad_semantic("Lifecycle", 9, "label", enabled=use_color) + "  " +
              pad_semantic("Runtime", 12, "label", enabled=use_color) + "  " +
              pad_semantic("Session", session_width, "label", enabled=use_color), file=stream)

    def rows(items: list[dict[str, Any]]) -> None:
        for row in items:
            provider = row.get('current_provider') or row.get('pending_provider') or '—'
            provider_text = pad_semantic(str(provider).upper(), 7,
                                         {"CODEX": "provider_codex", "AGY": "provider_agy"}.get(str(provider).upper(), ""),
                                         enabled=use_color)
            lifecycle = str(row.get('state') or 'unknown')
            state_text = pad_semantic(lifecycle, 9,
                                      lifecycle.casefold() if lifecycle.casefold() in {"active", "inactive", "completed"} else "",
                                      enabled=use_color)
            stored_session = row.get('current_session_id')
            session = stored_session or (
                "<pending>" if row.get("pending_launch_id") else "<unresolved>"
            )
            activity = format_timestamp(row.get('last_activity_at'))
            runtime = (_runtime_label(dispatcher, provider, row.get('current_environment_id'),
                                      row.get('current_session_id'), pending=bool(row.get('pending_launch_id')))
                       if dispatcher else 'UNKNOWN')
            agent_text = pad_semantic(str(row['name']), name_width, "agent", enabled=use_color)
            runtime_text = runtime_semantic(runtime, enabled=use_color)
            session_semantic = ("unresolved" if not _valid_existing_session(row) else "session") if stored_session else (
                "pending" if session == "<pending>" else "unresolved"
            )
            session_display = f"UNRESOLVED: {session}" if stored_session and session_semantic == "unresolved" else str(session)
            if wide_table:
                activity_field = pad_semantic(activity, 16, "timestamp", enabled=use_color)
                runtime_field = pad_semantic(runtime, 12,
                                             {"IN USE": "runtime_in_use", "NOT OBSERVED": "runtime_not_observed",
                                              "PENDING": "pending", "UNKNOWN": "unknown"}.get(runtime.upper(), ""),
                                             enabled=use_color)
                line = (f"  {agent_text}  {pad_semantic(str(provider).upper(), 8, {'CODEX': 'provider_codex', 'AGY': 'provider_agy'}.get(str(provider).upper(), ''), enabled=use_color)}  {activity_field}  {state_text}  "
                        f"{runtime_field}  {semantic_color(clip_display(session_display, session_width), session_semantic, enabled=use_color)}")
                print(line, file=stream)
            elif width >= 58:
                first_width = max(10, width - 23)
                print(f"  {pad_semantic(str(row['name']), first_width, 'agent', enabled=use_color)}  "
                      f"{provider_text}  {state_text}", file=stream)
                if longest_session > width - 30:
                    print(f"    {pad_semantic(activity, 16, 'timestamp', enabled=use_color)}  {runtime_text}", file=stream)
                    print(f"    {semantic_color(clip_display(session_display, max(1, width - 6)), session_semantic, enabled=use_color)}",
                          file=stream)
                else:
                    suffix_width = display_width(runtime) + 2 + min(display_width(session_display), max(8, width - 6))
                    date_width = min(16, max(8, width - suffix_width - 8))
                    print(f"    {pad_semantic(activity, date_width, 'timestamp', enabled=use_color)}  "
                          f"{runtime_text}  {semantic_color(clip_display(session_display, max(8, width - date_width - display_width(runtime) - 8)), session_semantic, enabled=use_color)}",
                          file=stream)
            else:
                print("  " + semantic_color(clip_display(str(row['name']), width - 2), "agent", enabled=use_color), file=stream)
                print(f"    {provider_text.strip()}  {state_text.strip()}  "
                      f"{semantic_color(activity, 'timestamp', enabled=use_color)}", file=stream)
                session_cells = max(1, width - 8 - display_width(runtime))
                print(f"    {runtime_text}  {semantic_color(clip_display(session_display, session_cells), session_semantic, enabled=use_color)}", file=stream)
            for entry in row.get("activation_history", []):
                entry_date = format_timestamp(entry.get("activated_at"))
                entry_provider_value = str(entry.get("provider") or "—").upper()
                entry_provider = provider_semantic(entry_provider_value, enabled=use_color)
                entry_id = "<unresolved>" if entry.get("unresolved") else entry["native_session_id"]
                marker_value = " * selected" if entry.get("selected") else ""
                marker = semantic_color(marker_value, "success", enabled=use_color)
                if width < 48:
                    print(f"    {pad_semantic(entry_date, 16, 'timestamp', enabled=use_color)}  {entry_provider}", file=stream)
                    id_cells = max(1, width - 6 - display_width(marker_value))
                    print(f"      {semantic_color(clip_display(entry_id, id_cells), 'unresolved' if entry.get('unresolved') else 'session', enabled=use_color)}{marker}", file=stream)
                else:
                    id_cells = max(1, width - 31 - display_width(marker_value))
                    history_line = (f"    {pad_semantic(entry_date, 16, 'timestamp', enabled=use_color)}  {entry_provider}  "
                                    f"{semantic_color(clip_display(entry_id, id_cells), 'unresolved' if entry.get('unresolved') else 'session', enabled=use_color)}{marker}")
                    print(history_line, file=stream)

    if 'conversations' in result:
        for index, conversation in enumerate(result['conversations']):
            if index:
                print(file=stream)
                if use_color:
                    print(semantic_color("─" * max(8, width - 1), "label", enabled=use_color), file=stream)
                print(file=stream)
            activity = format_timestamp(conversation.get('last_activity_at'))
            gui_alias = clip_display(str(conversation['alias']), max(0, width - 33))
            print(f"{semantic_color(gui_alias, 'gui', enabled=use_color)}  "
                  f"{semantic_color('Last activity:', 'label', enabled=use_color)} "
                  f"{semantic_color(activity, 'timestamp', enabled=use_color)}", file=stream)
            print_header()
            if not conversation['slots']:
                print("  (no agents)", file=stream)
            rows(conversation['slots'])
            if conversation['omitted']:
                print(clip_display(f"  {conversation['omitted']} agents omitted.", width), file=stream)
        print(clip_display(f"Showing {result['shown']} of {result['total']} conversations ({result['omitted']} omitted).", width), file=stream)
    else:
        gui_alias = clip_display(str(result['gui']), max(0, width - 33))
        print(f"{semantic_color(gui_alias, 'gui', enabled=use_color)}  "
              f"{semantic_color('Last activity:', 'label', enabled=use_color)} "
              f"{semantic_color(format_timestamp(result.get('last_activity_at')), 'timestamp', enabled=use_color)}", file=stream)
        print_header()
        if not result['slots']:
            print("  (no agents)", file=stream)
        rows(result['slots'])
        print(clip_display(f"Showing {result['shown']} of {result['total']} agents ({result['omitted']} omitted).", width), file=stream)


def _last_terminal_history(dispatcher: DispatcherService, args: argparse.Namespace) -> dict[str, Any]:
    raw_terminal_id = os.environ.get("TERMINAL_SESSION_ID")
    if not raw_terminal_id:
        raise ContinuityError(
            ErrorCode.INVALID_INPUT,
            "This process has no TERMINAL_SESSION_ID. Run `llmd last` from a PowerShell session with terminal identity initialized; no global fallback is used.",
        )
    if args.count is not None and (args.count < 1 or args.count > 1000):
        raise ContinuityError(ErrorCode.INVALID_INPUT, "Terminal history count must be between 1 and 1000.")
    if args.apply and args.count is not None:
        raise ContinuityError(ErrorCode.INVALID_INPUT, "Choose either `last -N COUNT` or `last -a`.")
    if args.reactivate and not args.apply:
        raise ContinuityError(ErrorCode.INVALID_INPUT, "`last -R` requires `-a` to resume the recorded session.")
    if args.json_output and args.apply:
        raise ContinuityError(ErrorCode.INVALID_INPUT, "JSON output is available for read-only `last` queries, not interactive resume.")
    if (args.cwd or getattr(args, "native_args", []) or args.allow_native_unknown) and not args.apply:
        raise ContinuityError(ErrorCode.INVALID_INPUT, "Launch overrides on `last` require `-a` to resume a session.")
    launches = dispatcher.list_terminal_launches(raw_terminal_id, limit=args.count or 1)
    if args.apply:
        if not launches:
            raise ContinuityError(ErrorCode.INVALID_INPUT, "This terminal has no recorded launch to resume.")
        return {"action": "last", "launch": launches[0]}
    return {"action": "last", "launches": launches}


def _render_terminal_launches(launches: list[dict[str, Any]], stream: TextIO, *, show_terminal_id: bool,
                              color: str = "auto") -> None:
    enabled = color_enabled(color, is_tty=stream.isatty(), stream=stream)
    if not launches:
        print(semantic_color("No matching terminal launch history.", "unknown", enabled=enabled), file=stream)
        return
    for index, launch in enumerate(launches):
        if index:
            print(file=stream)
        def display_value(key: str, current_launch: dict[str, Any] = launch) -> str:
            item = current_launch.get(key)
            return str(item) if item not in (None, "") else "(unavailable)"

        terminal_id = str(launch.get("terminal_session_id") or "")
        scope = f"  terminal {terminal_id[:8]}" if show_terminal_id and terminal_id else ""
        status = launch.get("status") or "unknown status"
        if status in {"launching", "running"}:
            status = f"{status} (outcome unverified; process may have been terminated)"
        print(f"{semantic_color(format_timestamp(launch.get('launch_started_at')), 'timestamp', enabled=enabled)}  "
              f"{outcome_semantic(status, enabled=enabled)}{scope}", file=stream)
        print(f"  {semantic_color('Requested GUI:', 'label', enabled=enabled)} "
              f"{semantic_color(display_value('gui_alias'), 'gui', enabled=enabled)}", file=stream)
        print(f"  {semantic_color('Agent:', 'label', enabled=enabled)} "
              f"{semantic_color(display_value('slot_name'), 'agent', enabled=enabled)}", file=stream)
        print(f"  {semantic_color('Provider:', 'label', enabled=enabled)} "
              f"{provider_semantic(display_value('provider'), enabled=enabled)}", file=stream)
        session = launch.get("native_session_id")
        print(f"  {semantic_color('Native session ID:', 'label', enabled=enabled)} "
              f"{semantic_color(session if session else '(unavailable; not captured)', 'session' if session else 'unresolved', enabled=enabled)}", file=stream)
        for label, key in (("Environment:", "environment_id"), ("Requested cwd:", "requested_cwd"),
                           ("Effective launch cwd:", "effective_cwd"), ("Recorded native cwd:", "native_cwd"),
                           ("Git repository:", "git_repository"), ("Git worktree:", "git_worktree"),
                           ("Git branch:", "git_branch"), ("Git commit:", "git_commit")):
            print(f"  {semantic_color(label, 'label', enabled=enabled)} {display_value(key)}", file=stream)
        if launch.get("launch_exited_at"):
            exit_code = launch.get("exit_code")
            status_text = str(launch.get("status") or "")
            exit_semantic = "failed" if exit_code not in (None, 0) or "abnormal" in status_text else (
                "success" if status_text == "exited" and exit_code == 0 else "warning")
            print(f"  {semantic_color('Exit:', 'label', enabled=enabled)} "
                  f"{semantic_color(format_timestamp(launch['launch_exited_at']), 'timestamp', enabled=enabled)} "
                  f"{semantic_color(f'(code {exit_code})', exit_semantic, enabled=enabled)}", file=stream)


def _resume_terminal_launch(
    dispatcher: DispatcherService,
    launch: dict[str, Any],
    *,
    reactivate: bool,
    cwd_override: str | None = None,
    native_args: Sequence[str] = (),
    allow_native_unknown: bool = False,
    input_stream: TextIO,
    output_stream: TextIO,
) -> int:
    _startup_progress("resolving the exact terminal-scoped session for resume")
    provider = launch.get("provider")
    environment_id = launch.get("environment_id")
    session_id = launch.get("native_session_id")
    slot_id = launch.get("slot_id")
    if not all((provider, environment_id, session_id, slot_id)):
        raise ContinuityError(ErrorCode.INVALID_INPUT, "The latest terminal launch has no safely captured native session ID; use pending/recover/attach safeguards.")
    slot = dispatcher.get_slot_by_id(slot_id)
    if launch.get("gui_id") != slot["gui_id"]:
        raise ContinuityError(ErrorCode.INVALID_INPUT, "The recorded GUI identity no longer matches the selected agent slot.")
    identity = (provider, environment_id, session_id)
    if not any(
        (item["provider"], item["environment_id"], item["native_session_id"]) == identity
        for item in slot["history"]
    ):
        raise ContinuityError(ErrorCode.INVALID_INPUT, "The recorded session is no longer in this agent's activation history.")
    if slot["state"] == "completed":
        raise ContinuityError(ErrorCode.INVALID_INPUT, "Completed agents cannot be resumed with `llmd last`.")
    if slot["state"] == "inactive" and not reactivate:
        raise ContinuityError(ErrorCode.INVALID_INPUT, "This agent is inactive; pass `-R -a` to explicitly reactivate and resume it.")
    if reactivate and slot["state"] != "inactive":
        raise ContinuityError(ErrorCode.INVALID_INPUT, "`-R` applies only to an inactive recorded agent.")
    if _session_in_use(dispatcher, provider, environment_id, session_id):
        raise ContinuityError(ErrorCode.INVALID_INPUT, "The recorded session is already in use by an LLMD-managed process.")
    _validated_native_args(provider, native_args, allow_unknown=allow_native_unknown)
    if cwd_override:
        _validate_cwd_override(dispatcher, environment_id, cwd_override)
    _validate_additional_directories(dispatcher, provider, environment_id, native_args,
                                     allow_native_unknown=allow_native_unknown)
    native_session = dispatcher.materializer.get_session(provider, environment_id, session_id)
    effective_cwd = cwd_override or (native_session.cwd_native if native_session else None)
    preview = _launch_preview(dispatcher, provider, session_id, environment_id, effective_cwd,
                              native_args, allow_native_unknown=allow_native_unknown)
    if cwd_override or native_args:
        _render_launch_preview(preview, output_stream)
    expected_current = _session_identity(slot)
    dispatcher.attach_session(
        gui=slot["gui_alias"], name=slot["name"], provider=provider,
        session_id=session_id, environment_selector=environment_id,
        expected_current=expected_current, check_current=True, reactivate=reactivate,
        apply=True, provenance="terminal_last",
    )
    return _run_pane(
        dispatcher, slot_id=slot_id, launch_id=None, input_stream=input_stream,
        output_stream=output_stream, native_args=native_args, cwd_override=cwd_override,
        expected_session_identity=identity, allow_native_unknown=allow_native_unknown,
    )


def dispatch(args: argparse.Namespace, parser: argparse.ArgumentParser, *, input_stream: TextIO, output_stream: TextIO) -> int:
    _resolve_execution_mode(args)
    token = _COLOR_MODE.set(getattr(args, "color", "auto"))
    started = time.monotonic()
    startup_enabled = bool(args.command in {"start", "continue", "switch", "review", "return", "last"}
                           and getattr(args, "apply", False) and not getattr(args, "json_output", False))
    progress_token = _STARTUP_PROGRESS.set(startup_enabled)
    started_token = _STARTUP_STARTED.set(started)
    try:
        with temporary_vt_processing(output_stream, _current_color_mode()):
            return _dispatch_impl(args, parser, input_stream=input_stream, output_stream=output_stream)
    finally:
        _STARTUP_STARTED.reset(started_token)
        _STARTUP_PROGRESS.reset(progress_token)
        _COLOR_MODE.reset(token)


def _resolve_execution_mode(args: argparse.Namespace) -> None:
    """Resolve the compatibility apply alias and default action behavior before any I/O."""
    command = getattr(args, "command", None)
    gui_action = command == "gui" and getattr(args, "gui_command", None) in {"add", "rename"}
    slot_action = command == "slot" and getattr(args, "slot_command", None) is not None
    operational = command in {"start", "continue", "switch", "open", "review", "return", "attach"} or gui_action or slot_action
    if command == "last":
        args.apply = bool(getattr(args, "apply", False) or getattr(args, "resume", False))
        if getattr(args, "dry_run", False):
            raise ContinuityError(ErrorCode.INVALID_INPUT, "`last` is read-only by default; use `-r/--resume` to resume.")
        return
    if command == "register" and getattr(args, "dry_run", False) and getattr(args, "apply", False):
        raise ContinuityError(ErrorCode.INVALID_INPUT, "Choose either --dry-run or --apply.")
    if not operational:
        return
    explicit_apply = bool(getattr(args, "apply", False))
    dry_run = bool(getattr(args, "dry_run", False))
    if explicit_apply and dry_run:
        raise ContinuityError(ErrorCode.INVALID_INPUT, "Choose either --dry-run or --apply.")
    args.apply_explicit = explicit_apply
    args.apply = explicit_apply or not dry_run
def _dispatch_impl(args: argparse.Namespace, parser: argparse.ArgumentParser, *, input_stream: TextIO, output_stream: TextIO) -> int:
    if args.command is None:
        if not (input_stream.isatty() and output_stream.isatty()):
            parser.print_help(file=output_stream)
            return 2
        from .interactive import run_interactive

        return run_interactive(DispatcherService(home_dir=args.home), input_stream=input_stream,
                               output_stream=output_stream, color_mode=getattr(args, "color", "auto"))

    if args.command in {"start", "continue"}:
        args.gui = _resolve_name(args.gui_pos, args.gui, "GUI")
        args.agent_name = _resolve_name(args.agent_pos, args.agent_name, "agent")
        if args.command == "start" and (not args.gui or not args.agent_name):
            raise ContinuityError(ErrorCode.INVALID_INPUT, "Both GUI and agent are required.")
        if args.command == "continue" and args.agent_name and not args.gui:
            raise ContinuityError(ErrorCode.INVALID_INPUT, "A GUI is required when an agent is specified.")
    native_args = getattr(args, "native_args", [])
    allow_native_unknown = bool(getattr(args, "allow_native_unknown", False))
    if native_args and args.command not in _NATIVE_ARG_COMMANDS:
        raise ContinuityError(ErrorCode.INVALID_INPUT, f"Provider options are not supported with `llmd {args.command}`.")
    if args.command == "open" and native_args:
        raise ContinuityError(ErrorCode.INVALID_INPUT,
                              "Provider options are not supported by `llmd open`; use `continue` for one selected session.")
    if getattr(args, "apply", False) and args.command in {"start", "continue", "switch", "review", "return", "last"}:
        _startup_progress("registry synchronization, environment and executable discovery starting")
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
    elif args.command == "last":
        result = _last_terminal_history(dispatcher, args)
        if args.json_output:
            print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True), file=output_stream)
            return 0
        if args.apply:
            return _resume_terminal_launch(dispatcher, result["launch"], reactivate=args.reactivate,
                                          cwd_override=args.cwd, native_args=native_args,
                                          allow_native_unknown=allow_native_unknown,
                                          input_stream=input_stream, output_stream=output_stream)
        _render_terminal_launches(result["launches"], output_stream, show_terminal_id=False,
                                  color=getattr(args, "color", "auto"))
        return 0
    elif args.command == "recent":
        if args.count < 1 or args.count > 1000:
            raise ContinuityError(ErrorCode.INVALID_INPUT, "Recent history count must be between 1 and 1000.")
        result = {"action": "recent", "launches": dispatcher.list_recent_terminal_launches(limit=args.count)}
        if args.json_output:
            print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True), file=output_stream)
        else:
            _render_terminal_launches(result["launches"], output_stream, show_terminal_id=True,
                                      color=getattr(args, "color", "auto"))
        return 0
    elif args.command == "register":
        gui = _resolve_name(args.gui_pos, args.gui, "GUI")
        name = _resolve_name(args.agent_pos, args.agent_name, "agent")
        if not gui:
            raise ContinuityError(ErrorCode.INVALID_INPUT, "A GUI name is required.")
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
        return _review(dispatcher, args, input_stream, output_stream, native_args=native_args,
                       allow_native_unknown=allow_native_unknown)
    elif args.command == "return":
        return _return(dispatcher, args, input_stream, output_stream, native_args=native_args,
                       allow_native_unknown=allow_native_unknown)
    elif args.command == "switch":
        reuse = args.command == "switch" and args.reuse_previous
        if reuse:
            current_slot = dispatcher.get_slot(gui=args.gui, name=args.agent_name)
            expected_current = _session_identity(current_slot)
            if current_slot["state"] == "completed":
                raise ContinuityError(ErrorCode.INVALID_INPUT,
                                      "Completed agents require an explicit lifecycle change before switching.")
            if current_slot["state"] == "inactive" and not args.reactivate:
                raise ContinuityError(ErrorCode.INVALID_INPUT,
                                      "This agent is inactive; pass --reactivate to confirm its lifecycle change.")
            old = _resolve_historical_session(dispatcher, gui=args.gui, name=args.agent_name,
                                              provider=args.provider, session_id=None, allow_latest=True)
            target_identity = (old["provider"], old["environment_id"], old["native_session_id"])
            target_cwd = args.cwd or _current_native_cwd(dispatcher, old)
            if args.cwd:
                _validate_cwd_override(dispatcher, old["environment_id"], args.cwd)
            preview = _launch_preview(dispatcher, old["provider"], old["native_session_id"],
                                      old["environment_id"], target_cwd, native_args,
                                      allow_native_unknown=allow_native_unknown)
            if not args.apply:
                result = {"action": "switch", "applied": False,
                          "summary": f"Dry-run: would resume historical {old['provider']} session {old['native_session_id']}.",
                          "launch_preview": preview}
                if not args.json_output:
                    _render_launch_preview(preview, output_stream)
                    return 0
            if args.apply:
                if _session_in_use(dispatcher, *target_identity):
                    raise ContinuityError(ErrorCode.INVALID_INPUT, "Requested session is already in use.")
                if native_args:
                    _render_launch_preview(preview, output_stream)
                _startup_progress("validating and reserving exact historical session activation")
                result = dispatcher.attach_session(
                    gui=args.gui, name=args.agent_name, provider=target_identity[0],
                    session_id=target_identity[2], environment_selector=target_identity[1],
                    expected_current=expected_current, check_current=True, reactivate=args.reactivate,
                    apply=True, provenance="dispatcher_reuse",
                )
            if args.apply:
                slot = dispatcher.get_slot(gui=args.gui, name=args.agent_name)
                return _run_pane(dispatcher, slot_id=slot["slot_id"], launch_id=None,
                                 input_stream=input_stream, output_stream=output_stream,
                                 native_args=native_args, cwd_override=args.cwd,
                                 expected_session_identity=target_identity,
                                 allow_native_unknown=allow_native_unknown)
        else:
            current_slot = dispatcher.get_slot(gui=args.gui, name=args.agent_name)
            current = current_slot["current"]
            expected_current = ((current["provider"], current["environment_id"], current["native_session_id"])
                                if current else None)
            _validated_native_args(args.provider, native_args, allow_unknown=allow_native_unknown)
            environment_selector = args.environment or (current["environment_id"] if current else "local")
            environment = _resolve_environment(dispatcher, environment_selector)
            if args.cwd:
                _validate_cwd_override(dispatcher, environment.environment_id, args.cwd)
            if args.apply:
                environment = _resolve_environment(dispatcher, environment_selector, persist_local=True)
            environment_id = environment.environment_id
            launch_environment_selector = environment_id if args.apply else environment_selector
            if args.apply:
                new_preview = _new_launch_preview(
                    dispatcher, args.provider, environment_id,
                    args.cwd or _current_native_cwd(dispatcher, current), native_args,
                    allow_native_unknown=allow_native_unknown,
                )
                if native_args:
                    _render_launch_preview(new_preview, output_stream)
                _startup_progress("reserving new-provider launch under the registry lock")
            result = dispatcher.begin_launch(gui=args.gui, name=args.agent_name, provider=args.provider,
                                             cwd=args.cwd, environment_selector=launch_environment_selector,
                                             expected_current=expected_current, check_current=True,
                                             reactivate=args.reactivate, apply=args.apply)
            if args.apply:
                _startup_progress("new-provider launch reservation committed")
                return _run_pane(dispatcher, slot_id=result["details"]["slot_id"],
                                 launch_id=result["details"]["launch_id"],
                                 input_stream=input_stream, output_stream=output_stream,
                                 native_args=native_args, allow_native_unknown=allow_native_unknown)
            else:
                result["launch_preview"] = _new_launch_preview(
                    dispatcher, args.provider, environment_selector,
                    args.cwd or _current_native_cwd(dispatcher, current), native_args,
                    allow_native_unknown=allow_native_unknown)
                preview_environment_id = result["launch_preview"]["environment"]["id"]
                result["details"]["environment_id"] = preview_environment_id
                for event in result["events"]:
                    event["environment_id"] = preview_environment_id
    elif args.command == "continue":
        if not args.agent_name:
            return _run_picker(dispatcher, args, input_stream, output_stream, native_args=native_args,
                               allow_native_unknown=allow_native_unknown)
        slot = dispatcher.get_slot(gui=args.gui, name=args.agent_name)
        expected_current = _session_identity(slot)
        target = _resolve_historical_session(dispatcher, gui=args.gui, name=args.agent_name,
            provider=args.provider, session_id=args.session_id) if (args.provider or args.session_id) else slot["current"]
        if target is None:
            raise ContinuityError(ErrorCode.INVALID_INPUT, "This slot has no selected session; use `llmd start`.")
        target_identity = (target["provider"], target["environment_id"], target["native_session_id"])
        if slot["state"] == "completed":
            raise ContinuityError(ErrorCode.INVALID_INPUT, "Completed agents require an explicit lifecycle change before resumption.")
        effective_cwd = args.cwd or target.get("cwd_native") or _current_native_cwd(dispatcher, target)
        if args.cwd:
            _validate_cwd_override(dispatcher, target["environment_id"], args.cwd)
        preview = _launch_preview(dispatcher, target["provider"], target["native_session_id"],
                                  target["environment_id"], effective_cwd, native_args,
                                  allow_native_unknown=allow_native_unknown)
        if not args.apply:
            result = {"action": "continue", "applied": False, "summary": "Dry-run: pass -a/--apply to resume this exact session.",
                      "launch_preview": preview}
            if not args.json_output:
                print(result["summary"], file=output_stream)
                _render_launch_preview(preview, output_stream)
                return 0
        if args.apply and _session_in_use(dispatcher, *target_identity):
            raise ContinuityError(ErrorCode.INVALID_INPUT, "Requested session is already in use.")
        if slot["state"] == "inactive" and not args.reactivate:
            raise ContinuityError(ErrorCode.INVALID_INPUT,
                                  "This agent is inactive; pass --reactivate to confirm its lifecycle change.")
        if target_identity != expected_current:
            if not args.apply:
                result = {"action": "continue", "applied": False, "slot": slot,
                          "summary": f"Dry-run: would select historical {target['provider']} session {target['native_session_id']}.",
                          "launch_preview": preview}
        else:
            result = {"action": "continue", "applied": False, "slot": slot,
                      "summary": "Dry-run: pass -a/--apply to resume the selected session.",
                      "launch_preview": preview}
        if args.apply:
            if native_args:
                _render_launch_preview(preview, output_stream)
            dispatcher.attach_session(
                gui=args.gui, name=args.agent_name, provider=target_identity[0],
                session_id=target_identity[2], environment_selector=target_identity[1],
                expected_current=expected_current, check_current=True, reactivate=args.reactivate,
                apply=True, provenance="dispatcher_reuse",
            )
            current_slot = dispatcher.get_slot(gui=args.gui, name=args.agent_name)
            return _run_pane(dispatcher, slot_id=current_slot["slot_id"], launch_id=None,
                             input_stream=input_stream, output_stream=output_stream,
                             native_args=native_args, cwd_override=args.cwd,
                             expected_session_identity=target_identity,
                             allow_native_unknown=allow_native_unknown)
    elif args.command == "open":
        result = _open(dispatcher, args)
        if args.apply and result.get("terminal_launcher_available") is False:
            print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True, default=_json_default) if args.json_output else result["summary"], file=output_stream)
            return 2
    elif args.command == "pane-run":
        return _run_pane(dispatcher, slot_id=args.slot_id, launch_id=args.launch_id,
                         input_stream=input_stream, output_stream=output_stream,
                         launcher_terminal_context=args.launcher_terminal_context)
    else:
        parser.error("command required")
        return 2

    json_mode = bool(args.json_output)
    if json_mode:
        print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True, default=_json_default), file=output_stream)
    else:
        output_color = color_enabled(getattr(args, "color", "auto"), is_tty=output_stream.isatty(),
                                     stream=output_stream)
        if result.get("action") == "list":
            _render_listing(result, output_stream, args.color, dispatcher=dispatcher)
            return 0
        if result.get("schema_version") == 1 and "registry" in result and "agents" in result:
            _render_doctor_report(result, output_stream, getattr(args, "color", "auto"))
            return 0
        if result.get("action") == "gui-list":
            for conversation in result["conversations"]:
                print(conversation["alias"], file=output_stream)
        if "summary" in result:
            print(result["summary"], file=output_stream)
        if result.get("launch_preview"):
            _render_launch_preview(result["launch_preview"], output_stream, getattr(args, "color", "auto"))
        for slot_row in result.get("slots", []):
            provider = slot_row.get("current_provider") or slot_row.get("pending_provider") or "unresolved"
            session = slot_row.get("current_session_id") or ("pending" if slot_row.get("pending_launch_id") else "unresolved")
            session_semantic = "pending" if session == "pending" else "unresolved" if session == "unresolved" else "session"
            print(f"{semantic_color(slot_row['name'], 'agent', enabled=output_color)}\t"
                  f"{provider_semantic(provider, enabled=output_color)}\t"
                  f"{semantic_color(session, session_semantic, enabled=output_color)}", file=output_stream)
        if result.get("unresolved"):
            for item in result["unresolved"]:
                print(f"{semantic_color('Unresolved:', 'unresolved', enabled=output_color)} "
                      f"{semantic_color(item['agent_name'], 'agent', enabled=output_color)}: {item['reason']}", file=output_stream)
        if result.get("action") == "history":
            for index, item in enumerate(result["slot"]["history"], 1):
                marker = semantic_color(" * selected", "success", enabled=output_color) if item.get("selected") else ""
                session_semantic = "unresolved" if item.get("unresolved") else "session"
                print(f"{index}. {provider_semantic(item['provider'], enabled=output_color)} "
                      f"{semantic_color(item['native_session_id'], session_semantic, enabled=output_color)} "
                      f"[{item['environment_id']}] ({item['provenance']}){marker}", file=output_stream)
        if result.get("action") == "pending":
            for launch in result["launches"]:
                captured_id = launch.get("captured_session_id") or "unresolved"
                print(
                    f"{launch['launch_id']}\t{launch.get('gui_alias', '')}\t{launch.get('agent_name', '')}\t"
                    f"{provider_semantic(launch['provider'], enabled=output_color)}\t{launch['environment_id']}\t"
                    f"{semantic_color(captured_id, 'unresolved' if captured_id == 'unresolved' else 'session', enabled=output_color)}",
                    file=output_stream,
                )
                if launch.get("failure_detail"):
                    print(f"  {semantic_color('Recovery:', 'label', enabled=output_color)} "
                          f"{semantic_color(launch['failure_detail'], 'error', enabled=output_color)}", file=output_stream)
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
        "SELECT gui_id, alias FROM dispatcher_gui_conversations WHERE alias_key = ?", (args.gui.strip().casefold(),)
    )
    slot_row = (dispatcher._row("SELECT * FROM agent_slots WHERE gui_id = ? AND name_key = ?",
                                (gui_row["gui_id"], args.agent_name.strip().casefold())) if gui_row else None)
    if slot_row:
        history = dispatcher._history(slot_row["slot_id"])
        slot = {**slot_row, "gui_alias": gui_row["alias"], "history": history,
                "current": history[-1] if history else None}
    else:
        slot = None
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
        if args.cwd:
            _validate_cwd_override(dispatcher, current["environment_id"], args.cwd)
        preview = _launch_preview(dispatcher, current["provider"], current["native_session_id"],
                                  current["environment_id"], args.cwd or _current_native_cwd(dispatcher, current),
                                  getattr(args, "native_args", []),
                                  allow_native_unknown=getattr(args, "allow_native_unknown", False))
        if not args.apply:
            if getattr(args, "json_output", False):
                result = {"action": "start", "applied": False,
                          "summary": f"Dry-run: would resume selected {current['provider']} session {current['native_session_id']}.",
                          "launch_preview": preview}
                print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True), file=output_stream)
                return 0
            _render_launch_preview(preview, output_stream)
            return 0
        if getattr(args, "native_args", []):
            _render_launch_preview(preview, output_stream)
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
                         input_stream=input_stream, output_stream=output_stream,
                         native_args=getattr(args, "native_args", []), cwd_override=args.cwd,
                         allow_native_unknown=getattr(args, "allow_native_unknown", False))

    if slot and slot["state"] == "completed":
        raise ContinuityError(ErrorCode.INVALID_INPUT,
                              "Completed agents require an explicit lifecycle change before starting a session.")
    if slot and slot["state"] == "inactive" and not args.reactivate:
        raise ContinuityError(ErrorCode.INVALID_INPUT,
                              "This agent is inactive; pass --reactivate to confirm its lifecycle change.")
    if (current and args.new and args.apply and input_stream.isatty() and output_stream.isatty()
            and not _ask_confirmation(
                input_stream, output_stream,
                f"Start a NEW {args.provider} conversation and retain the selected session in history?",
                default=False)):
        print("New conversation canceled; no provider was launched.", file=output_stream)
        return 0

    _validated_native_args(args.provider, getattr(args, "native_args", []),
                           allow_unknown=getattr(args, "allow_native_unknown", False))
    environment_selector = args.environment or (current["environment_id"] if current and args.new else "local")
    environment = _resolve_environment(dispatcher, environment_selector)
    if args.cwd:
        _validate_cwd_override(dispatcher, environment.environment_id, args.cwd)
    if args.apply:
        environment = _resolve_environment(dispatcher, environment_selector, persist_local=True)
    environment_id = environment.environment_id
    launch_environment_selector = environment_id if args.apply else environment_selector
    new_preview = _new_launch_preview(dispatcher, args.provider,
                                      environment_id if args.apply else environment_selector, args.cwd,
                                      getattr(args, "native_args", []),
                                      allow_native_unknown=getattr(args, "allow_native_unknown", False))
    _startup_progress("environment and provider executable discovery completed")
    if args.apply and getattr(args, "native_args", []):
        _render_launch_preview(new_preview, output_stream)

    _startup_progress("reserving the pending launch under the registry lock")
    result = dispatcher.prepare_start(
        gui=args.gui,
        name=args.agent_name,
        provider=args.provider,
        cwd=args.cwd,
        environment_selector=launch_environment_selector,
        reactivate=args.reactivate,
        expected_current=expected_current,
        apply=args.apply,
    )
    if args.apply:
        _startup_progress("launch reservation committed")
        return _run_pane(dispatcher, slot_id=result["details"]["slot_id"],
                         launch_id=result["details"]["launch_id"],
                         input_stream=input_stream, output_stream=output_stream,
                         native_args=getattr(args, "native_args", []),
                         allow_native_unknown=getattr(args, "allow_native_unknown", False))
    result["launch_preview"] = new_preview
    if not args.apply:
        preview_environment_id = new_preview["environment"]["id"]
        result["details"]["environment_id"] = preview_environment_id
        for event in result["events"]:
            event["environment_id"] = preview_environment_id
    if args.json_output:
        print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True, default=_json_default), file=output_stream)
    else:
        print(f"{result['summary']} Use -N to replace an existing selected session.", file=output_stream)
        _render_launch_preview(result["launch_preview"], output_stream)
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
