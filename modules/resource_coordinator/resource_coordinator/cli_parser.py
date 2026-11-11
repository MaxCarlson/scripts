"""Argument parsing for canonical and legacy Resource Coordinator commands."""

from __future__ import annotations

import argparse
from typing import List, Optional

from resource_coordinator import __version__


def _add_canonical_commands(subparsers: argparse._SubParsersAction) -> None:
    control = subparsers.add_parser(
        "control", help="Manage coordinated mining and gaming modes.",
        description="Control managed workloads. Mutating operations retain their established immediate behavior.",
        epilog="Examples: resource-coordinator control miner pause -d 2h; "
               "resource-coordinator control gaming on",
    )
    control_sub = control.add_subparsers(dest="control_domain", required=True)
    miner = control_sub.add_parser("miner", help="Control the coordinator-managed miner.")
    miner_sub = miner.add_subparsers(dest="miner_command", required=True)
    for action in ("status", "start", "stop", "pause", "resume"):
        command = miner_sub.add_parser(action, help=f"Miner {action}.")
        command.set_defaults(operation_id=f"control.miner.{action}")
        command.add_argument("-u", "--url", default="http://127.0.0.1:1235", help="Coordinator URL.")
        if action != "status":
            command.add_argument("-r", "--reason", default=f"Operator requested miner {action}.")
        if action == "pause":
            pause_mode = command.add_mutually_exclusive_group(required=True)
            pause_mode.add_argument("-d", "--duration", help="Hold duration, e.g. 2h, 30m, or 90s.")
            pause_mode.add_argument("--until-gpu-below", type=float, metavar="PCT")
            command.add_argument("--window", default="60s", help="GPU sampling window (default: 60s).")
    gaming = control_sub.add_parser("gaming", help="Safely coordinate gaming and local-model memory.")
    gaming_sub = gaming.add_subparsers(dest="gaming_action", required=True)
    gaming_status = gaming_sub.add_parser("status", help="Show gaming mode state.")
    gaming_status.set_defaults(operation_id="control.gaming.status", gaming_command="status")
    gaming_status.add_argument("-u", "--url", default="http://127.0.0.1:1235")
    for spelling, action in (("on", "start"), ("off", "stop")):
        command = gaming_sub.add_parser(spelling, help=f"Gaming mode {spelling}.")
        command.set_defaults(operation_id=f"control.gaming.{spelling}", gaming_command=action)
        command.add_argument("-u", "--url", default="http://127.0.0.1:1235")
        command.add_argument("-r", "--reason", default=f"Operator requested gaming {action}.")

    service = subparsers.add_parser(
        "service", help="Manage coordinator lifecycle and safety state.",
        description="Coordinator lifecycle controls. restart drains and restarts the running service; "
                    "recover clears safety inhibition only under its authorization rules.",
        epilog="Examples: resource-coordinator service restart; "
               "resource-coordinator service recover --reason 'upstream verified idle'",
    )
    service_sub = service.add_subparsers(dest="service_command", required=True)
    for action in ("restart", "shutdown"):
        command = service_sub.add_parser(action, help=f"Gracefully {action} the running coordinator.")
        command.set_defaults(operation_id=f"service.{action}")
        command.add_argument("-u", "--url", default="http://127.0.0.1:1235", help="Coordinator URL.")
        command.add_argument("-r", "--reason", default=f"Operator requested {action}")
    abort = service_sub.add_parser("abort", help="Trigger the authenticated emergency abort operation.")
    abort.set_defaults(operation_id="service.abort", command="abort")
    abort.add_argument("-u", "--url", default="http://127.0.0.1:1235")
    abort.add_argument("-r", "--reason", default="Manual operator emergency abort")
    recover = service_sub.add_parser("recover", help="Clear a restart inhibition with operator evidence.")
    recover.set_defaults(operation_id="service.recover", command="recover")
    recover.add_argument("-u", "--url", default="http://127.0.0.1:1235")
    recover.add_argument("--resource", default="gpu.inference")
    recover.add_argument("-r", "--reason", required=True)
    recover.add_argument("-f", "--force", action="store_true")
    run = service_sub.add_parser("run", help="Run the coordination gateway in the foreground.")
    run.set_defaults(operation_id="service.run", command="serve")
    _add_serve_arguments(run)

    system = subparsers.add_parser(
        "system", help="Install and maintain Resource Coordinator on this host.",
        description="Host installation and startup integration. upgrade activates new code; "
                    "repair reconciles owned resources; teardown removes RC ownership.",
        epilog="Examples: resource-coordinator system setup --apply; "
               "resource-coordinator system upgrade --apply",
    )
    system_sub = system.add_subparsers(dest="system_command", required=True)
    setup = system_sub.add_parser("setup", help="Set up or repair the managed installation.")
    setup.set_defaults(operation_id="system.setup", command="setup")
    _add_installation_arguments(setup, setup=True)
    upgrade = system_sub.add_parser("upgrade", help="Activate updated coordinator code safely.")
    upgrade.set_defaults(operation_id="system.upgrade", command="upgrade")
    _add_apply_arguments(upgrade, non_interactive=True)
    repair = system_sub.add_parser("repair", help="Repair Resource Coordinator-owned installation resources.")
    repair.set_defaults(operation_id="system.repair", command="repair")
    _add_apply_arguments(repair, non_interactive=True)
    teardown = system_sub.add_parser("teardown", help="Safely remove Resource Coordinator ownership.")
    teardown.set_defaults(operation_id="system.teardown", command="teardown")
    _add_apply_arguments(teardown, non_interactive=True)

    recovery = system_sub.add_parser("recovery", help="Inspect or recover an interrupted host upgrade.")
    recovery_sub = recovery.add_subparsers(dest="recovery_command", required=True)
    for action in ("status", "diagnose", "restore", "resume", "reconcile"):
        command = recovery_sub.add_parser(action, help=f"Upgrade recovery {action}.")
        command.set_defaults(operation_id=f"system.recovery.{action}", command="recovery")
        if action in {"restore", "resume", "reconcile"}:
            _add_apply_arguments(command, non_interactive=True)

    startup = system_sub.add_parser("startup", help="Inspect or manage owned startup tasks.")
    startup_sub = startup.add_subparsers(dest="startup_command", required=True)
    for action in ("status", "enable", "disable", "repair", "uninstall"):
        command = startup_sub.add_parser(action, help=f"Startup task {action}.")
        command.set_defaults(operation_id=f"system.startup.{action}", command="startup")
        if action != "status":
            _add_apply_arguments(command, non_interactive=True)
    install = startup_sub.add_parser("install", help="Install the authoritative startup task.")
    install.set_defaults(operation_id="system.startup.install", command="startup")
    install.add_argument("-m", "--mode", choices=("boot", "logon"), required=True)
    _add_apply_arguments(install, non_interactive=True)

    auth = system_sub.add_parser("auth", help="Check or repair the local operator credential.")
    auth_sub = auth.add_subparsers(dest="auth_command", required=True)
    for action in ("doctor", "repair", "reinitialize"):
        command = auth_sub.add_parser(action, help=f"Credential {action}.")
        command.set_defaults(operation_id=f"system.auth.{action}", command="auth")

    subparsers.choices["status"].set_defaults(operation_id="status")
    subparsers.choices["logs"].set_defaults(operation_id="logs")

    check = subparsers.add_parser(
        "check", help="Check health, telemetry, readiness, or acceptance.",
        description="health diagnoses installation/runtime; telemetry reads service/hardware metrics; "
                    "preflight checks readiness; accept runs supervised trials that may be live only "
                    "when explicitly authorized.",
        epilog="Examples: resource-coordinator check health; "
               "resource-coordinator check preflight --config .\\config.local.yaml",
    )
    check_sub = check.add_subparsers(dest="check_command", required=True)
    health = check_sub.add_parser("health", help="Diagnose installation and runtime health.")
    health.set_defaults(operation_id="check.health", command="doctor")
    telemetry = check_sub.add_parser("telemetry", help="Read hardware and coordinator telemetry.")
    telemetry.set_defaults(operation_id="check.telemetry", command="diagnose")
    telemetry.add_argument("-c", "--config", default=None)
    telemetry.add_argument("-u", "--url", default="http://127.0.0.1:1235")
    preflight = check_sub.add_parser("preflight", help="Check readiness for coordinator operation.")
    preflight.set_defaults(operation_id="check.preflight", command="preflight")
    preflight.add_argument("-c", "--config", default=None)
    preflight.add_argument("-f", "--fake-miner", "--fake-process", action="store_true")
    preflight.add_argument("--check-live", action="store_true")
    preflight.add_argument("--min-free-vram-mb", type=float, default=1024.0)
    accept = check_sub.add_parser("accept", help="Run supervised coordination acceptance trials.")
    accept.set_defaults(operation_id="check.accept", command="accept")
    _add_accept_arguments(accept)


def _child_parsers(parser: argparse.ArgumentParser) -> dict:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action.choices
    return {}


def _add_apply_arguments(parser: argparse.ArgumentParser, *, non_interactive: bool = False) -> None:
    parser.add_argument("-a", "--apply", action="store_true", help="Apply the requested administrative change.")
    if non_interactive:
        parser.add_argument("-n", "--non-interactive", action="store_true", help="Do not prompt for UAC.")


def _add_installation_arguments(parser: argparse.ArgumentParser, *, setup: bool = False) -> None:
    _add_apply_arguments(parser, non_interactive=True)
    if setup:
        parser.add_argument("-m", "--startup-mode", choices=("boot", "logon"), default="logon")
        parser.add_argument("--viewer", action="store_true", help="Install the optional read-only log viewer.")


def _add_serve_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-l", "--listen", default=None, help="Host:port to bind the gateway.")
    parser.add_argument("-u", "--upstream", default=None, help="LM Studio upstream URL.")
    parser.add_argument("-c", "--config", default=None, help="Policy configuration YAML.")
    parser.add_argument("-f", "--fake-miner", "--fake-process", action="store_true")
    parser.add_argument("-m", "--start-miner", action="store_true", dest="start_miner")
    parser.add_argument("--start-process", metavar="NAME")
    parser.add_argument("-s", "--stop-miner-on-shutdown", action="store_true")
    parser.add_argument("--stop-process-on-shutdown", metavar="NAME")
    parser.add_argument("-t", "--drain-timeout", type=float, default=30.0)
    parser.add_argument("--first-boot", action="store_true")


def _add_accept_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-c", "--config", default=None)
    parser.add_argument("-m", "--mode", choices=["simulated", "disposable_helper", "live"], default="simulated")
    parser.add_argument("--allow-live-lmstudio", action="store_true")
    parser.add_argument("--allow-real-miner", action="store_true")
    # Historical `accept -u` means upstream, not coordinator URL.
    parser.add_argument("-u", "--upstream", default=None)
    parser.add_argument("-w", "--work-dir", default=None)
    parser.add_argument("-o", "--output", default=None)
    parser.add_argument("--trials", nargs="+", default=None)
    parser.add_argument("--cooldown", type=float, default=None)


def _legacy_operation_id(command: str, child: Optional[str] = None, leaf: Optional[str] = None) -> str:
    if command == "miner":
        return f"control.miner.{child}"
    if command == "gaming":
        return f"control.gaming.{'on' if child == 'start' else 'off' if child == 'stop' else child}"
    if command in {"restart", "shutdown", "abort", "recover", "serve"}:
        return f"service.{'run' if command == 'serve' else command}"
    if command in {"setup", "upgrade", "repair", "teardown"}:
        return f"system.{command}"
    if command == "startup":
        return f"system.startup.{child}"
    if command == "auth":
        return f"system.auth.{child}"
    if command == "doctor":
        return "check.health"
    if command == "diagnose":
        return "check.telemetry"
    if command == "preflight":
        return "check.preflight"
    if command == "accept":
        return "check.accept"
    if command == "config":
        return f"config.{child}"
    return command if command in {"status", "logs"} else ""


def _add_global_leaf_options(root: argparse.ArgumentParser) -> None:
    """Allow global options before or after the command without child defaults masking them."""
    subparser_actions = [action for action in root._actions if isinstance(action, argparse._SubParsersAction)]
    visited = set()

    def visit(parser: argparse.ArgumentParser) -> None:
        if id(parser) in visited:
            return
        visited.add(id(parser))
        nested = [action for action in parser._actions if isinstance(action, argparse._SubParsersAction)]
        if nested:
            for action in nested:
                for child in action.choices.values():
                    visit(child)
            return
        if parser is root:
            return
        existing = {option for action in parser._actions for option in action.option_strings}
        for option, kwargs in (
            ("-v", {"long": "--verbose", "action": "store_true", "dest": "verbose"}),
            ("-j", {"long": "--json", "action": "store_true", "dest": "json"}),
            (None, {"long": "--color", "choices": ("auto", "always", "never"), "dest": "color"}),
        ):
            option_strings = [option] if option else []
            option_strings.append(kwargs.pop("long"))
            dest = kwargs.pop("dest")
            if any(item in existing for item in option_strings):
                for action in parser._actions:
                    if dest == action.dest and action.default is False:
                        action.default = argparse.SUPPRESS
                continue
            if dest == "json" and parser.get_default("operation_id") in {"logs", "service.run"}:
                continue
            parser.add_argument(*option_strings, default=argparse.SUPPRESS, **kwargs)

    for action in subparser_actions:
        for child in action.choices.values():
            visit(child)


def parse_args(args: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="resource-coordinator",
        description="Coordinate local inference and managed workloads.",
        epilog=(
            "Examples:\n"
            "  resource-coordinator status\n"
            "  resource-coordinator control miner status\n"
            "  resource-coordinator logs miner --follow\n\n"
            "Compatibility: existing root commands (miner, gaming, restart, serve, setup, "
            "upgrade, repair, teardown, startup, auth, doctor, diagnose, preflight, accept) "
            "remain supported. Use --help on a command for its options."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose debug logging.")
    parser.add_argument("-j", "--json", action="store_true", help="Output structured results as JSON.")
    parser.add_argument("--color", choices=("auto", "always", "never"), default="auto",
                        help="Colorized human output (auto honors NO_COLOR and terminal detection).")

    subparsers = parser.add_subparsers(
        dest="command", required=True, metavar="{status,control,service,system,config,check,logs}"
    )

    auth_parser = subparsers.add_parser("auth", help=argparse.SUPPRESS)
    auth_sub = auth_parser.add_subparsers(dest="auth_command", required=True)
    auth_sub.add_parser("doctor", help="Offline credential and ACL check.")
    auth_sub.add_parser("repair", help="Repair credential ACLs without changing the token.")
    auth_sub.add_parser("reinitialize", help="Rotate credential while the coordinator is stopped.")

    setup_parser = subparsers.add_parser("setup", help=argparse.SUPPRESS)
    setup_parser.add_argument("-a", "--apply", action="store_true", help="Apply the planned setup changes.")
    setup_parser.add_argument("-j", "--json", action="store_true", help="Output a machine-readable result.")
    setup_parser.add_argument(
        "-n", "--non-interactive", action="store_true", help="Do not display UAC or other interactive prompts."
    )
    setup_parser.add_argument(
        "-m", "--startup-mode", choices=("boot", "logon"), default="logon",
        help="Authoritative coordinator startup trigger (default: logon).",
    )
    setup_parser.add_argument("--viewer", action="store_true", help="Install the optional visible log viewer at user logon.")

    upgrade_parser = subparsers.add_parser("upgrade", help=argparse.SUPPRESS)
    upgrade_parser.add_argument("-a", "--apply", action="store_true", help="Apply the prepared upgrade.")
    upgrade_parser.add_argument("-j", "--json", action="store_true", help="Output a machine-readable result.")
    upgrade_parser.add_argument(
        "-n", "--non-interactive", action="store_true", help="Do not display UAC or other interactive prompts."
    )

    doctor_parser = subparsers.add_parser("doctor", help=argparse.SUPPRESS)
    doctor_parser.add_argument("-j", "--json", action="store_true", help="Output a machine-readable report.")

    repair_parser = subparsers.add_parser("repair", help=argparse.SUPPRESS)
    repair_parser.add_argument("-a", "--apply", action="store_true", help="Apply safe repairs.")
    repair_parser.add_argument("-j", "--json", action="store_true", help="Output a machine-readable report.")
    repair_parser.add_argument("-n", "--non-interactive", action="store_true")

    teardown_parser = subparsers.add_parser("teardown", help=argparse.SUPPRESS)
    teardown_parser.add_argument("-a", "--apply", action="store_true", help="Apply the planned teardown.")
    teardown_parser.add_argument("-j", "--json", action="store_true", help="Output a machine-readable result.")
    teardown_parser.add_argument(
        "-n", "--non-interactive", action="store_true", help="Do not display UAC or other interactive prompts."
    )

    startup_parser = subparsers.add_parser("startup", help=argparse.SUPPRESS)
    startup_sub = startup_parser.add_subparsers(dest="startup_command", required=True)
    startup_status = startup_sub.add_parser("status", help="Show RC startup task state.")
    startup_status.add_argument("-j", "--json", action="store_true")
    for startup_action in ("enable", "disable", "repair", "uninstall"):
        action_parser = startup_sub.add_parser(startup_action, help=f"{startup_action.capitalize()} RC startup tasks.")
        action_parser.add_argument("-a", "--apply", action="store_true", help="Apply the requested change.")
        action_parser.add_argument("-j", "--json", action="store_true")
        action_parser.add_argument("-n", "--non-interactive", action="store_true")
    startup_install = startup_sub.add_parser("install", help="Install one authoritative RC startup task.")
    startup_install.add_argument("-m", "--mode", choices=("boot", "logon"), required=True)
    startup_install.add_argument("-a", "--apply", action="store_true", help="Apply the requested change.")
    startup_install.add_argument("-j", "--json", action="store_true")
    startup_install.add_argument("-n", "--non-interactive", action="store_true")

    for action in ("restart", "shutdown"):
        lifecycle_parser = subparsers.add_parser(action, help=argparse.SUPPRESS)
        lifecycle_parser.add_argument("-u", "--url", default="http://127.0.0.1:1235", help="Coordinator URL.")
        lifecycle_parser.add_argument(
            "-r", "--reason", default=f"Operator requested {action}", help="Reason recorded with the request."
        )
        lifecycle_parser.add_argument("-j", "--json", action="store_true", help="Output the JSON response.")

    # serve
    serve_parser = subparsers.add_parser("serve", help=argparse.SUPPRESS)
    serve_parser.add_argument(
        "-l",
        "--listen",
        default=None,
        help="Host:port to bind the gateway (default: 127.0.0.1:1235).",
    )
    serve_parser.add_argument(
        "-u",
        "--upstream",
        default=None,
        help="Upstream LM Studio URL (default: http://127.0.0.1:1234).",
    )
    serve_parser.add_argument("-c", "--config", default=None, help="Path to policy configuration YAML.")
    serve_parser.add_argument(
        "-f",
        "--fake-miner",
        "--fake-process",
        action="store_true",
        help="Use in-memory fake process backends instead of real processes.",
    )
    serve_parser.add_argument(
        "-m",
        "--start-miner",
        action="store_true",
        dest="start_miner",
        help="Start the legacy miner target during service startup if configured.",
    )
    serve_parser.add_argument(
        "--start-process", metavar="NAME", help="Explicitly start a configured process at startup."
    )
    serve_parser.add_argument(
        "-s",
        "--stop-miner-on-shutdown",
        action="store_true",
        help="Stop miner during service shutdown if configured.",
    )
    serve_parser.add_argument(
        "--stop-process-on-shutdown", metavar="NAME", help="Stop a coordinator-owned configured process at shutdown."
    )
    serve_parser.add_argument(
        "-t",
        "--drain-timeout",
        type=float,
        default=30.0,
        help="Timeout in seconds for draining active requests during shutdown (default: 30.0).",
    )
    serve_parser.add_argument(
        "--first-boot",
        action="store_true",
        help="Initialize a fresh durable state journal if it does not already exist.",
    )

    # preflight
    preflight_parser = subparsers.add_parser(
        "preflight",
        help=argparse.SUPPRESS,
    )
    preflight_parser.add_argument("-c", "--config", default=None, help="Path to policy configuration YAML.")
    preflight_parser.add_argument(
        "-f",
        "--fake-miner",
        "--fake-process",
        action="store_true",
        help="Use in-memory fake process backends.",
    )
    preflight_parser.add_argument("-j", "--json", action="store_true", help="Output preflight result in JSON format.")
    preflight_parser.add_argument(
        "--check-live",
        action="store_true",
        help="Run read-only live acceptance preflight (checks external miners, locks, LM Studio model, and GPU VRAM).",
    )
    preflight_parser.add_argument(
        "--min-free-vram-mb",
        type=float,
        default=1024.0,
        help="Minimum free GPU VRAM (MiB) required for live preflight (default: 1024.0).",
    )

    # abort
    abort_parser = subparsers.add_parser(
        "abort",
        help=argparse.SUPPRESS,
    )
    abort_parser.add_argument(
        "-u",
        "--url",
        default="http://127.0.0.1:1235",
        help="Coordinator gateway URL (default: http://127.0.0.1:1235).",
    )
    abort_parser.add_argument(
        "-r",
        "--reason",
        default="Manual operator emergency abort",
        help="Reason for emergency abort.",
    )
    abort_parser.add_argument("-j", "--json", action="store_true", help="Output abort response in JSON format.")

    # status
    status_parser = subparsers.add_parser("status", help="Query coordinator service status.")
    status_parser.add_argument(
        "-u",
        "--url",
        default="http://127.0.0.1:1235",
        help="Coordinator gateway URL (default: http://127.0.0.1:1235).",
    )
    status_parser.add_argument("-j", "--json", action="store_true", help="Output status in JSON format.")

    # recover
    recover_parser = subparsers.add_parser("recover", help=argparse.SUPPRESS)
    recover_parser.add_argument(
        "-u",
        "--url",
        default="http://127.0.0.1:1235",
        help="Coordinator gateway URL (default: http://127.0.0.1:1235).",
    )
    recover_parser.add_argument(
        "-r",
        "--resource",
        default="gpu.inference",
        help="Resource name to clear inhibition for (default: gpu.inference).",
    )

    recover_parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Explicitly override unverifiable upstream state.",
    )
    recover_parser.add_argument("-n", "--reason", required=True, help="Operator evidence/reason for recovery.")

    # config
    config_parser = subparsers.add_parser("config", help="Inspect or validate configuration.")
    config_sub = config_parser.add_subparsers(dest="config_command", required=True)
    show_parser = config_sub.add_parser("show", help="Show active configuration.")
    show_parser.add_argument("-c", "--config", default=None, help="Path to configuration YAML.")
    show_parser.add_argument("-j", "--json", action="store_true", help="Output in JSON format.")

    validate_parser = config_sub.add_parser("validate", help="Validate a configuration file.")
    validate_parser.add_argument("-c", "--config", required=True, help="Path to configuration YAML.")

    # miner
    miner_parser = subparsers.add_parser("miner", help=argparse.SUPPRESS)
    miner_sub = miner_parser.add_subparsers(dest="miner_command", required=True)
    m_status = miner_sub.add_parser("status", help="Get current miner process status.")
    m_status.add_argument("-u", "--url", default="http://127.0.0.1:1235", help="Coordinator URL.")
    m_status.add_argument("-j", "--json", action="store_true", help="Output in JSON format.")

    for action in ("start", "stop", "resume", "pause"):
        miner_action = miner_sub.add_parser(action, help=f"Coordinator-mediated miner {action}.")
        miner_action.add_argument("-u", "--url", default="http://127.0.0.1:1235", help="Coordinator URL.")
        miner_action.add_argument("-r", "--reason", default=f"Operator requested miner {action}.")
        miner_action.add_argument("-j", "--json", action="store_true", help="Output the JSON response.")
        if action == "pause":
            pause_mode = miner_action.add_mutually_exclusive_group(required=True)
            pause_mode.add_argument("-d", "--duration", help="Hold duration, e.g. 2h, 30m, or 90s.")
            pause_mode.add_argument("--until-gpu-below", type=float, metavar="PCT",
                                    help="Resume after GPU utilization stays below this percent for a full window.")
            miner_action.add_argument("--window", default="60s", help="GPU sampling window, e.g. 60s or 2m.")
    m_status.add_argument("-c", "--config", default=None, help=argparse.SUPPRESS)

    gaming_parser = subparsers.add_parser("gaming", help=argparse.SUPPRESS)
    gaming_sub = gaming_parser.add_subparsers(dest="gaming_command", required=True)
    gaming_status = gaming_sub.add_parser("status", help="Show gaming mode state.")
    gaming_status.add_argument("-u", "--url", default="http://127.0.0.1:1235")
    gaming_status.add_argument("-j", "--json", action="store_true")
    for action in ("start", "stop"):
        gaming_action = gaming_sub.add_parser(action, help=f"Gaming mode {action}.")
        gaming_action.add_argument("-u", "--url", default="http://127.0.0.1:1235")
        gaming_action.add_argument("-r", "--reason", default=f"Operator requested gaming {action}.")
        gaming_action.add_argument("-j", "--json", action="store_true")

    logs_parser = subparsers.add_parser("logs", help="Read or follow captured raw process output.")
    logs_parser.add_argument("process_name", help="Configured process name, e.g. krig.")
    logs_parser.add_argument("-u", "--url", default="http://127.0.0.1:1235")
    logs_parser.add_argument("--tail-bytes", type=int, default=65536, help="Initial history bytes (max 256 KiB).")
    logs_parser.add_argument("-f", "--follow", action="store_true", help="Continue polling for appended output.")

    # diagnose
    diag_parser = subparsers.add_parser(
        "diagnose",
        help=argparse.SUPPRESS,
    )
    diag_parser.add_argument("-c", "--config", default=None, help="Path to configuration YAML.")
    diag_parser.add_argument(
        "-u",
        "--url",
        default="http://127.0.0.1:1235",
        help="Coordinator URL (default: http://127.0.0.1:1235).",
    )
    diag_parser.add_argument("-j", "--json", action="store_true", help="Output diagnostics in JSON format.")

    # accept
    accept_parser = subparsers.add_parser(
        "accept",
        help=argparse.SUPPRESS,
    )
    accept_parser.add_argument("-c", "--config", default=None, help="Path to policy configuration YAML.")
    accept_parser.add_argument(
        "-m",
        "--mode",
        choices=["simulated", "disposable_helper", "live"],
        default="simulated",
        help="Execution mode (default: simulated).",
    )
    accept_parser.add_argument(
        "--allow-live-lmstudio",
        action="store_true",
        help="Explicitly authorize connection to live LM Studio upstream.",
    )
    accept_parser.add_argument(
        "--allow-real-miner",
        action="store_true",
        help="Explicitly authorize launching the configured real miner process.",
    )
    accept_parser.add_argument(
        "-u",
        "--upstream",
        default=None,
        help="Upstream LM Studio URL override.",
    )
    accept_parser.add_argument(
        "-w",
        "--work-dir",
        default=None,
        help="Work directory for isolated run evidence (default: creates temp dir or uses .live_acceptance_work).",
    )
    accept_parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Optional destination path to write acceptance_report.json.",
    )
    accept_parser.add_argument(
        "--trials",
        nargs="+",
        default=None,
        help="Specific trials to run (e.g. --trials T01 or --trials T02 T03 T04).",
    )
    accept_parser.add_argument(
        "--cooldown",
        type=float,
        default=None,
        help="Override cooldown seconds (live mode enforces >= 10.0s).",
    )
    accept_parser.add_argument("-j", "--json", action="store_true", help="Output acceptance report in JSON format.")

    _add_canonical_commands(subparsers)
    legacy_operation_ids = {
        "setup": "system.setup", "upgrade": "system.upgrade", "repair": "system.repair",
        "teardown": "system.teardown", "restart": "service.restart", "shutdown": "service.shutdown",
        "abort": "service.abort", "serve": "service.run", "recover": "service.recover",
        "doctor": "check.health", "diagnose": "check.telemetry", "preflight": "check.preflight",
        "accept": "check.accept", "status": "status", "logs": "logs",
    }
    for command, operation_id in legacy_operation_ids.items():
        subparsers.choices[command].set_defaults(operation_id=operation_id)
    for group in ("auth", "startup", "miner", "gaming", "config"):
        for child, child_parser in _child_parsers(subparsers.choices[group]).items():
            child_parser.set_defaults(operation_id=_legacy_operation_id(group, child))
    visible_commands = ("status", "control", "service", "system", "config", "check", "logs")
    choices_by_name = {action.dest: action for action in subparsers._choices_actions}
    subparsers._choices_actions = [choices_by_name[name] for name in visible_commands]
    _add_global_leaf_options(parser)
    return parser.parse_args(args)
