"""Subcommand entry point for setup and the existing local-model workflow."""

from __future__ import annotations

import argparse
import base64
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from . import __version__
from .setup.files import write_json
from .setup.installer import apply_plan, recover_installation, remove_installation
from .setup.planner import build_plan


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="local-agent",
        description="Set up coding agents and run the local model bridge.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""How to setup Global AGENTS.md and other LLM files:
  local-agent setup plan -c codex agy -m local -s auto
  local-agent setup apply
  local-agent setup status -j

How to run the local model setup & codex/agy integration:
  local-agent run -M qwen38_23GB -c 32768 -o 8192
  local-agent model verify qwen38_23GB -j
  local-agent run -M qwen38_23GB
  local-agent model list

How to inspect or attach to an existing OpenCode server:
  local-agent opencode status
  local-agent opencode status -j
  local-agent opencode attach -s ses_example""",
    )
    parser.add_argument("-V", "--version", action="version", version=__version__)
    groups = parser.add_subparsers(dest="group")
    setup = groups.add_parser(
        "setup", help="Plan, install, inspect or remove agent setup"
    )
    actions = setup.add_subparsers(dest="action")
    for name in ["plan", "apply", "status", "remove", "recover"]:
        action = actions.add_parser(name, help=name.capitalize() + " agent setup")
        action.add_argument("-H", "--home", type=Path, help="Target user home root")
        action.add_argument(
            "-S", "--state-dir", type=Path, help="Receipt and backup directory"
        )
        action.add_argument(
            "-j", "--json", action="store_true", help="Print structured results"
        )
        if name != "recover":
            action.add_argument(
                "-c",
                "--clients",
                nargs="+",
                choices=["codex", "agy"],
                default=None,
                help="Clients to configure (default: codex agy)",
            )
        if name in {"plan", "apply", "status"}:
            action.add_argument(
                "-s",
                "--strategy",
                choices=["auto", "link", "copy"],
                default=None,
                help="Resource link/copy strategy (default: auto)",
            )
            action.add_argument(
                "-m",
                "--mode",
                choices=["generic", "local"],
                default=None,
                help="Generic agent setup or generic plus local delegation (default: local)",
            )
            action.add_argument(
                "-A",
                "--adopt",
                nargs="+",
                default=None,
                help="Exact existing resource IDs to adopt",
            )
            action.add_argument(
                "--code-retrieval",
                action=argparse.BooleanOptionalAction,
                default=None,
                help="Opt in to receipt-managed OpenCode code_locate/code_context tools",
            )
        if name == "plan":
            action.add_argument(
                "-o",
                "--output",
                type=Path,
                help="Save a versioned plan without config contents",
            )
        if name == "apply":
            action.add_argument(
                "-i", "--input-plan", type=Path, help="Apply an unchanged saved plan"
            )
        if name == "remove":
            action.add_argument(
                "-a",
                "--apply",
                action="store_true",
                help="Execute removal (default: preview)",
            )
    model = groups.add_parser(
        "model", help="Inventory or manage configured model aliases"
    )
    actions = model.add_subparsers(dest="action")
    actions.add_parser(
        "list", help="List model variants, loaded models and configured aliases"
    )
    verify = actions.add_parser("verify", help="Read-only verification of OpenCode and LM Studio model limits")
    verify.add_argument("nickname", help="Configured OpenCode model alias")
    verify.add_argument("-j", "--json", action="store_true", help="Print structured verification results")
    verify.add_argument("-p", "--opencode-port", type=int, default=4096, help="OpenCode HTTP server port")
    verify.add_argument("-l", "--lms-port", type=int, default=1234, help="LM Studio HTTP port")
    verify.add_argument("-d", "--directory", type=Path, help="Project directory whose effective OpenCode config is checked")
    verify.add_argument("-c", "--context-length", type=int, help="Expected context limit")
    verify.add_argument("-o", "--output-tokens", type=int, help="Expected output limit")
    for name in ["rename", "remove"]:
        action = actions.add_parser(name)
        action.add_argument("nickname", help="Existing model alias")
        if name == "rename":
            action.add_argument("new_nickname", help="New model alias")
        action.add_argument(
            "-a",
            "--apply",
            action="store_true",
            help="Execute the operation (default: preview)",
        )
        action.add_argument(
            "-p",
            "--opencode-port",
            type=int,
            default=4096,
            help="OpenCode HTTP server port",
        )
        action.add_argument(
            "-l", "--lms-port", type=int, default=1234, help="LM Studio HTTP port"
        )
    opencode = groups.add_parser(
        "opencode",
        help="Check or attach to an existing OpenCode server",
        epilog="Examples:\n  local-agent opencode status -j\n  local-agent opencode ping\n  local-agent opencode attach -s ses_example",
    )
    opencode_actions = opencode.add_subparsers(dest="action")
    for name in ("status", "ping", "attach"):
        action = opencode_actions.add_parser(
            name,
            help={
                "status": "Check OpenCode server health",
                "ping": "Alias for status",
                "attach": "Open the interactive OpenCode TUI on an existing server",
            }[name],
        )
        action.add_argument(
            "-p",
            "--port",
            type=int,
            default=None,
            help="OpenCode server port (default: 4096)",
        )
        action.add_argument(
            "-u",
            "--url",
            help="Explicit OpenCode server URL (overrides environment default)",
        )
        action.add_argument(
            "-t",
            "--timeout",
            type=float,
            default=3.0,
            help="Health-check timeout in seconds (default: 3)",
        )
        if name in {"status", "ping"}:
            action.add_argument(
                "-j",
                "--json",
                action="store_true",
                help="Print structured health status",
            )
        else:
            action.add_argument("-s", "--session", help="Existing OpenCode session ID")
            action.add_argument(
                "-d", "--dir", type=Path, help="Project directory passed to OpenCode"
            )
    code = groups.add_parser("code", help="Locate, search, and read bounded source context")
    code_actions = code.add_subparsers(dest="action")
    locate = code_actions.add_parser("locate", help="List Git-aware workspace paths")
    locate.add_argument("query", nargs="?", help="Optional case-insensitive path substring")
    locate.add_argument("-C", "--workspace", type=Path, help="Workspace root (default: current directory)")
    locate.add_argument("-p", "--path", action="append", help="Explicit relative path; repeat as needed")
    locate.add_argument("-l", "--limit", type=int, default=200, help="Maximum paths to return")
    locate.add_argument("-b", "--max-bytes", type=int, default=8 * 1024, help="Maximum compact JSON bytes")
    locate.add_argument("-j", "--json", action="store_true", help="Print machine-readable JSON")
    search = code_actions.add_parser("search", help="Search source using a literal query or explicit regex")
    search.add_argument("query", help="Search text or regular expression")
    search.add_argument("-C", "--workspace", type=Path, help="Workspace root (default: current directory)")
    search.add_argument("-p", "--path", action="append", help="Restrict to an explicit relative path; repeat as needed")
    search.add_argument("-r", "--regex", action="store_true", help="Interpret query as a Python regular expression")
    search.add_argument("-l", "--limit", type=int, default=80, help="Maximum matches to return")
    search.add_argument("-f", "--max-files", type=int, default=200, help="Maximum candidate files to inspect")
    search.add_argument("-m", "--max-line-bytes", type=int, default=4096, help="Maximum returned match-line bytes")
    search.add_argument("-b", "--max-bytes", type=int, default=12 * 1024, help="Maximum compact JSON bytes")
    search.add_argument("-j", "--json", action="store_true", help="Print machine-readable JSON")
    context = code_actions.add_parser("context", help="Read an exact bounded source line range")
    context.add_argument("path", help="Workspace-relative source path")
    context.add_argument("start_line", type=int, help="Inclusive one-based start line")
    context.add_argument("end_line", type=int, help="Inclusive one-based end line")
    context.add_argument("-C", "--workspace", type=Path, help="Workspace root (default: current directory)")
    context.add_argument("-m", "--max-line-bytes", type=int, default=4096, help="Maximum bytes per returned line")
    context.add_argument("-b", "--max-bytes", type=int, default=16 * 1024, help="Maximum compact JSON bytes")
    context.add_argument("-j", "--json", action="store_true", help="Print machine-readable JSON")
    checkpoint = groups.add_parser("checkpoint", help="Save, inspect, or recover durable task context")
    checkpoint_actions = checkpoint.add_subparsers(dest="action")
    checkpoint_save = checkpoint_actions.add_parser("save", help="Validate and atomically save a task checkpoint")
    checkpoint_save.add_argument("-C", "--workspace", type=Path, required=True, help="Task workspace root")
    checkpoint_save.add_argument("-S", "--state-dir", type=Path, help="Checkpoint directory outside the workspace")
    checkpoint_save.add_argument("-i", "--input", type=Path, required=True, help="JSON checkpoint fields")
    checkpoint_save.add_argument("-j", "--json", action="store_true", help="Print machine-readable JSON")
    for name in ("show", "recover"):
        action = checkpoint_actions.add_parser(name, help={"show": "Show the saved task state",
                                                            "recover": "Build a stale-aware recovery packet"}[name])
        action.add_argument("task_id", help="Stable task identifier")
        action.add_argument("-C", "--workspace", type=Path, required=True, help="Task workspace root")
        action.add_argument("-S", "--state-dir", type=Path, help="Checkpoint directory outside the workspace")
        action.add_argument("-j", "--json", action="store_true", help="Print machine-readable JSON")
    groups.add_parser(
        "run",
        help="Configure/load the model and start the foreground bridge",
        add_help=False,
    )
    return parser


def _validate_opencode_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Invalid OpenCode URL or port.") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or any(char.isspace() for char in parsed.hostname)
        or parsed.netloc.endswith(":")
    ):
        raise ValueError(
            "OpenCode URL must be an http(s) URL without embedded credentials."
        )
    if parsed.query or parsed.fragment:
        raise ValueError("OpenCode URL must not contain a query string or fragment.")
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("OpenCode URL port must be between 1 and 65535.")
    return value.rstrip("/")


def resolve_opencode_url(args: argparse.Namespace) -> str:
    """Resolve an explicit URL, explicit localhost port, environment URL, then the safe default."""
    explicit_url = getattr(args, "url", None)
    explicit_port = getattr(args, "port", None)
    if explicit_url is not None and explicit_port is not None:
        raise ValueError("--url and --port cannot be combined; choose one endpoint.")
    if explicit_url is not None:
        return _validate_opencode_url(explicit_url)
    if explicit_port is not None:
        if not 1 <= explicit_port <= 65535:
            raise ValueError("--port must be between 1 and 65535.")
        return f"http://127.0.0.1:{explicit_port}"
    configured = os.environ.get("OPENCODE_BASE_URL")
    if configured:
        return _validate_opencode_url(configured)
    return "http://127.0.0.1:4096"


def _is_loopback_url(url: str) -> bool:
    hostname = urlsplit(url).hostname or ""
    if hostname.lower() == "localhost" or hostname.lower().endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _health_error(
    error_type: str, message: str, *, status_code: int | None = None
) -> dict:
    error = {"type": error_type, "message": message}
    if status_code is not None:
        error["status_code"] = status_code
    return error


def probe_opencode(url: str, timeout: float = 3.0) -> dict:
    """Query OpenCode's health endpoint without starting or configuring any runtime."""
    endpoint = _validate_opencode_url(url)
    if not 0 < timeout <= 60:
        raise ValueError(
            "--timeout must be greater than 0 and no more than 60 seconds."
        )
    request = urllib.request.Request(
        f"{endpoint}/global/health", headers={"Accept": "application/json"}
    )
    if _is_loopback_url(endpoint):
        password = os.environ.get("OPENCODE_SERVER_PASSWORD")
        if password:
            username = os.environ.get("OPENCODE_SERVER_USERNAME", "opencode")
            token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode(
                "ascii"
            )
            # Keep Basic auth out of redirects so a loopback credential cannot follow a server redirect.
            request.add_unredirected_header("Authorization", f"Basic {token}")
    result = {
        "url": endpoint,
        "reachable": False,
        "healthy": False,
        "version": None,
        "error": None,
    }
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status_code = response.status
            final_url = response.geturl()
            raw = response.read(65537)
    except urllib.error.HTTPError as exc:
        status_code = exc.code
        result["reachable"] = True
        if status_code in {401, 403}:
            result["error"] = _health_error(
                "authentication_required",
                "Authentication required.",
                status_code=status_code,
            )
        else:
            result["error"] = _health_error(
                "http_error", f"HTTP {status_code}.", status_code=status_code
            )
        return result
    except urllib.error.URLError as exc:
        reason = exc.reason
        if isinstance(reason, (TimeoutError, socket.timeout)):
            result["error"] = _health_error(
                "timeout", f"Request timed out after {timeout:g} seconds."
            )
        elif isinstance(reason, PermissionError):
            result["error"] = _health_error(
                "local_execution_error",
                "Local socket access was denied by the execution environment.",
            )
        elif (
            isinstance(reason, ConnectionRefusedError)
            or getattr(reason, "errno", None) in {61, 111, 10061}
            or getattr(reason, "winerror", None) == 10061
        ):
            result["error"] = _health_error("connection_refused", "Connection refused.")
        else:
            result["error"] = _health_error(
                "unavailable", "Could not connect to the OpenCode server."
            )
        return result
    except (TimeoutError, socket.timeout):
        result["error"] = _health_error(
            "timeout", f"Request timed out after {timeout:g} seconds."
        )
        return result
    except PermissionError:
        result["error"] = _health_error(
            "local_execution_error",
            "Local socket access was denied by the execution environment.",
        )
        return result
    except OSError:
        result["error"] = _health_error(
            "unavailable", "Could not connect to the OpenCode server."
        )
        return result

    result["reachable"] = True
    if final_url != request.full_url:
        result["error"] = _health_error(
            "unexpected_redirect", "Health endpoint redirected to a different URL."
        )
        return result
    if status_code < 200 or status_code >= 300:
        result["error"] = _health_error(
            "http_error", f"HTTP {status_code}.", status_code=status_code
        )
        return result
    if len(raw) > 65536:
        result["error"] = _health_error(
            "invalid_response", "Health response is too large or malformed."
        )
        return result
    try:
        health = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        result["error"] = _health_error(
            "invalid_response", "Health response is not valid JSON."
        )
        return result
    if not isinstance(health, dict) or not isinstance(health.get("healthy"), bool):
        result["error"] = _health_error(
            "invalid_response", "Health response has an invalid format."
        )
        return result
    result["version"] = (
        health.get("version") if isinstance(health.get("version"), str) else None
    )
    if health["healthy"] is not True:
        result["error"] = _health_error(
            "unhealthy_response", "OpenCode reported an unhealthy status."
        )
        return result
    return {**result, "healthy": True}


def _print_opencode_status(result: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2))
        return
    if result["healthy"]:
        print("OpenCode: RUNNING")
        print(f"URL:     {result['url']}")
        print(f"Version: {result['version'] or 'unknown'}")
        print("Health:  healthy")
        return
    error = result["error"] or {}
    if error.get("type") == "authentication_required":
        state = "AUTH REQUIRED"
    elif error.get("type") == "local_execution_error":
        state = "CHECK FAILED"
    elif result["reachable"]:
        state = "UNHEALTHY"
    else:
        state = "NOT RUNNING"
    print(f"OpenCode: {state}")
    print(f"URL:     {result['url']}")
    if error.get("type") == "unhealthy_response":
        print("Health:  unhealthy")
    print(f"Reason:  {error.get('message', 'OpenCode health check failed.')}")


def _run_opencode_attach(args: argparse.Namespace, url: str) -> int:
    if args.session is not None and not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_-]*", args.session
    ):
        raise ValueError(
            "Invalid session ID; use letters, digits, underscores, and hyphens."
        )
    if args.timeout <= 0 or args.timeout > 60:
        raise ValueError(
            "--timeout must be greater than 0 and no more than 60 seconds."
        )
    health = probe_opencode(url, args.timeout)
    if not health["healthy"]:
        print(health["error"]["message"], file=sys.stderr)
        return 2 if health["error"].get("type") == "local_execution_error" else 1
    executable = shutil.which("opencode")
    if not executable:
        print(
            "OpenCode executable 'opencode' was not found in PATH; install OpenCode and retry.",
            file=sys.stderr,
        )
        return 2
    command = [executable, "attach", url]
    if args.session is not None:
        command.extend(["--session", args.session])
    if args.dir is not None:
        command.extend(["--dir", str(args.dir)])
    environment = os.environ.copy()
    if not _is_loopback_url(url):
        # OpenCode attach reads these variables automatically; never send local server credentials to a custom host.
        environment.pop("OPENCODE_SERVER_PASSWORD", None)
        environment.pop("OPENCODE_SERVER_USERNAME", None)
    try:
        process = subprocess.Popen(command, env=environment, shell=False)
    except OSError as exc:
        print(
            f"Could not launch OpenCode: {exc.strerror or exc.__class__.__name__}.",
            file=sys.stderr,
        )
        return 2
    try:
        return_code = process.wait()
    except KeyboardInterrupt:
        try:
            process.terminate()
        except OSError:
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        return 130
    if os.name == "nt" and return_code == 3221225786:
        return 130
    return return_code if return_code >= 0 else 128 + abs(return_code)


def _handle_opencode(args: argparse.Namespace) -> int:
    try:
        url = resolve_opencode_url(args)
        if args.timeout <= 0 or args.timeout > 60:
            raise ValueError(
                "--timeout must be greater than 0 and no more than 60 seconds."
            )
        if args.action == "attach":
            return _run_opencode_attach(args, url)
        result = probe_opencode(url, args.timeout)
        _print_opencode_status(result, args.json)
        if result["healthy"]:
            return 0
        return 2 if result["error"].get("type") == "local_execution_error" else 1
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2


def _output(value: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(value, indent=2))
    elif "operations" in value:
        for op in value["operations"]:
            print(f"{op['action']:10} {op['resource_id']:28} {op['path']}")
            if op["conflict"]:
                print("  " + op["conflict"])
        for warning in value.get("warnings", []):
            print("Notice: " + warning)
    else:
        print(
            value.get("message", "Completed")
            + (": " + ", ".join(value["changed"]) if value.get("changed") else "")
        )
        for problem in value.get("conflicts", []) + value.get("errors", []):
            print(problem)


def _handle_code(args: argparse.Namespace) -> int:
    from .retrieval import RetrievalError, context, locate, search

    try:
        if args.action == "locate":
            result = locate(
                args.workspace, args.query, paths=args.path, limit=args.limit,
                max_output_bytes=args.max_bytes,
            )
        elif args.action == "search":
            result = search(
                args.workspace, args.query, regex=args.regex, paths=args.path,
                limit=args.limit, max_files=args.max_files, max_output_bytes=args.max_bytes,
                max_line_bytes=args.max_line_bytes,
            )
        else:
            result = context(
                args.workspace, args.path, args.start_line, args.end_line,
                max_output_bytes=args.max_bytes, max_line_bytes=args.max_line_bytes,
            )
    except (RetrievalError, OSError, ValueError) as exc:
        result = {
            "schema": "local-agent-retrieval-v1",
            "operation": args.action,
            "workspace": str(args.workspace) if args.workspace else str(Path.cwd()),
            "status": "error",
            "results": [],
            "truncated": False,
            "errors": [{"code": "invalid_request", "message": str(exc)}],
        }
        if args.json:
            print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        else:
            print(str(exc), file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    else:
        for item in result["results"]:
            if args.action == "locate":
                print(item["path"])
            elif args.action == "search":
                print(f'{item["path"]}:{item["line"]}: {item["text"]}')
            else:
                print(f'{item["line"]:>5}: {item["text"]}')
        if args.action == "context" and result["results"]:
            print(f'Next line: {result["next_line"]}')
        if not result["results"]:
            print("No results.")
        for issue in result["errors"]:
            location = f' ({issue["path"]})' if issue.get("path") else ""
            print(f'Notice{location}: {issue["message"]}', file=sys.stderr)
        if result["truncated"]:
            print("Output was truncated to the configured retrieval budget.", file=sys.stderr)
    return 1 if result["status"] == "partial" else 0


def _handle_checkpoint(args: argparse.Namespace) -> int:
    from .context.checkpoint import CheckpointError, load_checkpoint, recovery_packet, save_checkpoint

    try:
        if args.action == "save":
            payload = json.loads(args.input.read_text(encoding="utf-8"))
            allowed = {
                "task_id", "objective", "authorized_scope", "next_action", "base_revision", "identities",
                "confirmed_sources", "decisions", "assumptions", "modified_paths", "completed_verification",
                "pending_checks", "blockers",
            }
            if not isinstance(payload, dict) or set(payload) - allowed:
                raise CheckpointError("Checkpoint input must be an object with only supported task fields")
            result = save_checkpoint(
                args.workspace, payload.get("task_id"), payload.get("objective"),
                state_dir=args.state_dir,
                authorized_scope=payload.get("authorized_scope"),
                next_action=payload.get("next_action"),
                base_revision=payload.get("base_revision"),
                identities=payload.get("identities"),
                confirmed_sources=payload.get("confirmed_sources"),
                decisions=payload.get("decisions"),
                assumptions=payload.get("assumptions"),
                modified_paths=payload.get("modified_paths"),
                completed_verification=payload.get("completed_verification"),
                pending_checks=payload.get("pending_checks"),
                blockers=payload.get("blockers"),
            )
        else:
            result = load_checkpoint(args.workspace, args.task_id, state_dir=args.state_dir)
            if args.action == "recover":
                result = recovery_packet(args.workspace, result)
    except (CheckpointError, OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        result = {"status": "error", "errors": [{"code": "checkpoint_error", "message": str(exc)}]}
        if args.json:
            print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        else:
            print(str(exc), file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    else:
        print(f"Checkpoint {result.get('task_id')}: {result.get('status', 'saved')}")
        if result.get("next_action"):
            print("Next action: " + result["next_action"])
        for reason in result.get("stale_reasons", []):
            print("Stale evidence: " + reason)
    return 1 if result.get("status") == "stale" else 0


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    if arguments and arguments[0] == "run":
        from . import cli

        if "-h" not in arguments and "--help" not in arguments:
            if not (Path.home() / ".local/share/local-agent/receipt.json").is_file():
                print(
                    "Notice: delegation resources are not installed; run local-agent setup plan/apply."
                )
        return cli.main(arguments[1:], runtime_only=True)
    args = parser.parse_args(arguments)
    if not args.group:
        parser.print_help()
        return 0
    if not args.action:
        parser.parse_args([args.group, "--help"])
    if args.group == "opencode":
        return _handle_opencode(args)
    if args.group == "code":
        return _handle_code(args)
    if args.group == "checkpoint":
        return _handle_checkpoint(args)
    try:
        if args.group == "model":
            from . import cli

            if args.action == "list":
                cli.handle_ls_command()
            elif args.action == "verify":
                if (args.context_length is None) != (args.output_tokens is None):
                    raise ValueError("--context-length and --output-tokens must be supplied together.")
                result = cli.verify_model_configuration(
                    args.nickname,
                    opencode_port=args.opencode_port,
                    lms_port=args.lms_port,
                    directory=str(args.directory) if args.directory else None,
                    expected_context=args.context_length,
                    expected_output=args.output_tokens,
                )
                if args.json:
                    print(json.dumps(result, indent=2))
                else:
                    print(f"Model verification: {result['status']} ({args.nickname})")
                    for issue in result["diagnostics"]:
                        print(f"Mismatch: {issue}")
                    for warning in result["warnings"]:
                        print(f"Notice: {warning}")
                return 1 if result["diagnostics"] else 0
            elif not args.apply:
                print(
                    f"Preview: {args.action} alias {args.nickname}; add -a/--apply to execute."
                )
            elif args.action == "rename":
                cli.handle_rename_model(
                    args.nickname, args.new_nickname, args.lms_port, args.opencode_port
                )
            else:
                cli.handle_delete_model(args.nickname, args.opencode_port)
            return 0
        if args.action == "recover":
            result = recover_installation(
                args.home or Path.home(), state_dir=args.state_dir
            )
        elif args.action == "remove":
            result = remove_installation(
                args.home or Path.home(),
                tuple(args.clients or ["codex", "agy"]),
                execute=args.apply,
                state_dir=args.state_dir,
            )
        else:
            saved = None
            if args.action == "apply" and args.input_plan:
                if any(
                    value is not None
                    for value in [
                        args.clients,
                        args.strategy,
                        args.adopt,
                        args.mode,
                        args.code_retrieval,
                        args.state_dir,
                        args.home,
                    ]
                ):
                    parser.error(
                        "--input-plan cannot be combined with selection/target changes"
                    )
                saved = json.loads(args.input_plan.read_text(encoding="utf-8"))
                if saved.get("schema_version") != 1:
                    raise ValueError("Unsupported saved plan schema")
                saved.setdefault("code_retrieval", False)
                home, clients, strategy, mode, adopt, state = (
                    Path(saved["home"]),
                    tuple(saved["clients"]),
                    saved["strategy"],
                    saved["mode"],
                    tuple(saved["adopt"]),
                    Path(saved["state_dir"]),
                )
            else:
                home, clients, strategy, mode, adopt, state = (
                    args.home or Path.home(),
                    tuple(args.clients or ["codex", "agy"]),
                    args.strategy or "auto",
                    args.mode or "local",
                    tuple(args.adopt or []),
                    args.state_dir,
                )
                code_retrieval = args.code_retrieval
                if args.action == "status" and args.mode is None:
                    from .setup.manifest import Layout
                    from .setup.planner import load_receipt

                    modes = load_receipt(Layout.discover(home, state, None)).get(
                        "modes", {}
                    )
                    if modes and all(
                        modes.get(client) == "generic" for client in clients
                    ):
                        mode = "generic"
            plan = build_plan(
                home,
                clients,
                strategy=strategy,
                adopt=adopt,
                mode=mode,
                state_dir=state,
                code_retrieval=(saved["code_retrieval"] if saved is not None else code_retrieval),
            )
            if args.action == "apply":
                result = apply_plan(plan, expected=saved)
            else:
                result = plan.summary()
                result["code"] = (
                    3
                    if plan.conflicts
                    or (
                        args.action == "status"
                        and any(op.action != "unchanged" for op in plan.operations)
                    )
                    else 0
                )
                if args.action == "plan" and args.output:
                    write_json(args.output, plan.summary())
        _output(result, args.json)
        return result.get("code", 0)
    except (ValueError, OSError, RuntimeError, KeyError) as exc:
        message = str(exc)
        if args.group == "model" and args.action == "verify":
            if getattr(args, "json", False):
                print(json.dumps({"status": "error", "diagnostics": [message], "warnings": []}, indent=2))
            else:
                print(message, file=sys.stderr)
            return 2
        result = {
            "schema_version": 1,
            "code": 4
            if "stale" in message
            else 5
            if "rollback" in message
            else 3
            if "conflict" in message.lower()
            else 1,
            "message": message,
        }
        _output(result, getattr(args, "json", False))
        return result["code"]


if __name__ == "__main__":
    raise SystemExit(main())
