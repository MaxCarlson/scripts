"""Command line interface for managed Scheduled Task lifecycle operations."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from . import windows
from .models import (
    BootTrigger,
    CalendarTrigger,
    LogonTrigger,
    RepeatingIntervalTrigger,
    TaskPrincipal,
    TaskSpec,
    UnsupportedPlatformError,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="runtime-lifecycle", description="Manage owned Windows Scheduled Tasks")
    commands = parser.add_subparsers(dest="command", required=True)

    def common(command: str, help_text: str) -> argparse.ArgumentParser:
        sub = commands.add_parser(command, help=help_text)
        sub.add_argument("-j", "--json", action="store_true", help="Print JSON")
        return sub

    def add_spec(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("-i", "--input-file", required=True, type=Path, help="TaskSpec JSON file")

    preview = common("preview", "Preview a task definition")
    add_spec(preview)

    apply = common("apply", "Create or update an owned task")
    add_spec(apply)
    apply.add_argument("-a", "--apply", action="store_true", help="Apply the previewed definition")
    apply.add_argument("-n", "--dry-run", action="store_true", help="Preview without applying (default)")
    apply.add_argument("-f", "--force", action="store_true", help="Replace a conflicting task during apply")

    status = common("status", "Show task registration and Scheduler state")
    _add_identity(status)

    listing = common("list", "List managed tasks")
    listing.add_argument("-o", "--owner", help="Filter to one owner")
    listing.add_argument("-p", "--folder", default="\\Scripts", help="Task Scheduler folder")

    for name in ("enable", "disable", "start", "stop", "remove"):
        sub = common(name, f"{name.title()} an owned task")
        _add_identity(sub)
        sub.add_argument("-a", "--apply", action="store_true", help=f"Perform {name} (default is preview)")
        sub.add_argument("-n", "--dry-run", action="store_true", help="Preview without changing the task")

    return parser


def _add_identity(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-o", "--owner", required=True, help="Owning module identifier")
    parser.add_argument("-N", "--name", required=True, help="Task identifier")
    parser.add_argument("-p", "--folder", default="\\Scripts", help="Task Scheduler folder")
    parser.add_argument("-t", "--task-name", help="Override the default scheduled task name")
    parser.add_argument("-s", "--principal-sid", help="Expected task principal SID")


def _load_spec(path: Path) -> TaskSpec:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read task specification {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("Task specification JSON must be an object")
    principal_data = data.pop("principal", None)
    if principal_data is None:
        principal = TaskPrincipal.current_user_limited()
    else:
        principal = TaskPrincipal(**principal_data)
    trigger_types = {
        "logon": LogonTrigger,
        "boot": BootTrigger,
        "interval": RepeatingIntervalTrigger,
        "calendar": CalendarTrigger,
    }
    triggers = []
    for item in data.pop("triggers", []):
        values = dict(item)
        kind = values.pop("type", None)
        try:
            trigger_type = trigger_types[kind]
        except KeyError as exc:
            raise ValueError(f"Unsupported trigger type in spec: {kind!r}") from exc
        if trigger_type is CalendarTrigger:
            values["days_of_week"] = tuple(values.get("days_of_week", ()))
            values["days_of_month"] = tuple(values.get("days_of_month", ()))
            values["months"] = tuple(values.get("months", ()))
        triggers.append(trigger_type(**values))
    for key in ("executable", "working_dir"):
        if key in data and data[key] is not None:
            data[key] = Path(data[key])
    data["args"] = tuple(data.get("args", ()))
    data["triggers"] = tuple(triggers)
    data["principal"] = principal
    try:
        return TaskSpec(**data)
    except TypeError as exc:
        raise ValueError(f"Invalid task specification fields: {exc}") from exc


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes):
        return value.decode("utf-16")
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def _emit(value: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(_jsonable(value), ensure_ascii=False, indent=2))
    else:
        if isinstance(value, str):
            print(value)
        else:
            print(json.dumps(_jsonable(value), ensure_ascii=False, indent=2))


def _dispatch(args: argparse.Namespace) -> Any:
    if args.command == "preview":
        return windows.preview(_load_spec(args.input_file))
    if args.command == "apply":
        spec = _load_spec(args.input_file)
        if not args.apply or args.dry_run:
            return windows.preview(spec, check_paths=True)
        return windows.apply(spec, force=args.force)
    if args.command == "status":
        return windows.status(
            args.owner,
            args.name,
            folder=args.folder,
            task_name_override=args.task_name,
            principal_sid=args.principal_sid,
        )
    if args.command == "list":
        return windows.list_tasks(owner=args.owner, folder=args.folder)
    if args.command in {"enable", "disable", "start", "stop", "remove"}:
        action = getattr(windows, args.command)
        identity = {
            "folder": args.folder,
            "task_name_override": args.task_name,
            "principal_sid": args.principal_sid,
        }
        if not args.apply or args.dry_run:
            return {
                "applied": False,
                "action": args.command,
                "status": windows.status(args.owner, args.name, **identity),
                "message": f"Preview only; pass --apply to {args.command} the task",
            }
        return {"applied": True, "action": args.command, "result": action(args.owner, args.name, **identity)}
    raise ValueError(f"Unsupported command {args.command}")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        _emit(_dispatch(args), args.json)
        return 0
    except (OSError, RuntimeError, ValueError, UnsupportedPlatformError) as exc:
        if args.json:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        else:
            print(f"runtime-lifecycle: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
