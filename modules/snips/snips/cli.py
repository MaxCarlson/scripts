"""Command line interface for managing snippets and AutoHotkey runtime."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from ._version import __version__
from snips.backend import (
    DEFAULT_WATCHDOG_INTERVAL,
    ensure_autohotkey,
    find_autohotkey,
    legacy_startup_value,
    remove_legacy_startup,
    runtime_task_spec,
    startup_command,
)
from snips.config import (
    ConfigError,
    atomic_write,
    config_default_path,
    load_config,
    parse_hotkey,
    runtime_default_path,
    serialize_config,
    validate_config,
)
from snips.runtime import deploy, ensure_runtime, generate_script, runtime_status, start_runtime


def _read_exact(path: Path) -> str:
    with path.open("r", encoding="utf-8", newline="") as stream:
        return stream.read()


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-c", "--config", type=Path, default=None, help="Configuration JSON path")
    parser.add_argument("-j", "--json", action="store_true", help="Print machine-readable JSON")


def _add_apply(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "-a", "--apply", action="store_true", help="Apply the change (mutating commands default to dry-run)"
    )
    group.add_argument(
        "-n", "--dry-run", action="store_true", help="Preview without changing persistent state (default)"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="snips", description="Manage Windows snippets, hotkeys, and AutoHotkey v2")
    parser.add_argument("-V", "--version", action="version", version=f"snips {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    def command(name: str, help_text: str, *, mutating: bool = False) -> argparse.ArgumentParser:
        sub = commands.add_parser(name, help=help_text, description=help_text)
        _add_common(sub)
        if mutating:
            _add_apply(sub)
        return sub

    p = command(
        "install", "Detect/install AutoHotkey, create starter actions, and register per-user startup", mutating=True
    )
    p.add_argument("-s", "--skip-start", action="store_true", help="Do not start the runtime now")
    p.add_argument(
        "-i", "--interval", default=DEFAULT_WATCHDOG_INTERVAL, help="Watchdog repetition interval, e.g. PT1M"
    )

    p = command("ensure-runtime", "Ensure the configured AutoHotkey runtime is running", mutating=True)
    p.add_argument("-q", "--quiet", action="store_true", help="Silence healthy no-op checks")

    startup = commands.add_parser("startup", help="Manage the per-user Scheduled Task watchdog")
    startup_commands = startup.add_subparsers(dest="startup_command", required=True)
    for startup_name in ("preview", "apply", "status", "enable", "disable", "start", "stop", "remove"):
        sub = startup_commands.add_parser(startup_name, help=f"{startup_name.title()} snips scheduled startup")
        _add_common(sub)
        if startup_name in {"apply", "enable", "disable", "start", "stop", "remove"}:
            _add_apply(sub)
        if startup_name in {"preview", "apply"}:
            sub.add_argument("-i", "--interval", default=DEFAULT_WATCHDOG_INTERVAL, help="Watchdog repetition interval")

    p = command("add", "Add a template or action", mutating=True)
    p.add_argument("-i", "--id", required=True, help="Stable lowercase binding id")
    p.add_argument("-N", "--name", required=True, help="Display name")
    p.add_argument("-k", "--hotkey", required=True, help="Shortcut, for example Ctrl+Alt+X")
    p.add_argument(
        "-t",
        "--kind",
        choices=["template", "clipboard-fence", "selection-fence"],
        default="template",
        help="Action type",
    )
    p.add_argument("-T", "--content", help="Template text (use --file for multiline content)")
    p.add_argument("-f", "--file", type=Path, help="UTF-8 file containing template content")
    p.add_argument("-d", "--description", help="Optional description")

    p = command("edit", "Edit a binding's name, description, or template", mutating=True)
    p.add_argument("-i", "--id", required=True)
    p.add_argument("-N", "--name")
    p.add_argument("-d", "--description")
    p.add_argument("-T", "--content")
    p.add_argument("-f", "--file", type=Path)

    p = command("bind", "Assign or change a binding's hotkey", mutating=True)
    p.add_argument("-i", "--id", required=True)
    p.add_argument("-k", "--hotkey", required=True)

    p = command("remove", "Remove a binding", mutating=True)
    p.add_argument("-i", "--id", required=True)

    command("list", "List configured bindings")
    p = command("show", "Show one binding")
    p.add_argument("-i", "--id", required=True)

    for name in ("enable", "disable"):
        p = command(name, f"{name.title()} one binding", mutating=True)
        p.add_argument("-i", "--id", required=True)

    command("reload", "Reload the active AutoHotkey configuration", mutating=True)
    command("status", "Report runtime and startup state")
    command("doctor", "Check configuration, AutoHotkey, runtime, and startup")

    p = command("export", "Export the current configuration to a JSON file", mutating=True)
    p.add_argument("-o", "--output", required=True, type=Path)

    p = command("import", "Import bindings from a JSON file", mutating=True)
    p.add_argument("-f", "--input-file", required=True, type=Path)
    p.add_argument("-r", "--replace", action="store_true", help="Replace all managed bindings instead of merging by id")
    return parser


def _print(value: Any, as_json: bool) -> None:
    def jsonable(item: Any) -> Any:
        if is_dataclass(item):
            return jsonable(asdict(item))
        if isinstance(item, Path):
            return str(item)
        if isinstance(item, dict):
            return {key: jsonable(inner) for key, inner in item.items()}
        if isinstance(item, (list, tuple)):
            return [jsonable(inner) for inner in item]
        return item

    value = jsonable(value)
    if as_json:
        print(json.dumps(value, ensure_ascii=False, indent=2))
    elif isinstance(value, str):
        print(value)
    else:
        print(json.dumps(value, ensure_ascii=False, indent=2))


def _config_path(args: argparse.Namespace) -> Path:
    return args.config or config_default_path()


def _current(path: Path) -> dict[str, Any]:
    return load_config(path, missing_ok=True)


def _snapshot(paths: list[Path]) -> dict[Path, bytes | None]:
    result: dict[Path, bytes | None] = {}
    for path in paths:
        result[path] = path.read_bytes() if path.is_file() else None
    return result


def _restore(snapshot: dict[Path, bytes | None]) -> None:
    for path, content in snapshot.items():
        if content is None:
            path.unlink(missing_ok=True)
        else:
            atomic_write(path, content)


def _managed_runtime_files(runtime_dir: Path) -> list[Path]:
    paths = [runtime_dir / "snips.ahk"]
    paths.extend((runtime_dir / "data").glob("*.txt") if (runtime_dir / "data").exists() else [])
    return paths


def _apply_config(path: Path, config: dict[str, Any], *, executable: Path | None = None, start: bool = True) -> str:
    config = validate_config(config)
    runtime_dir = runtime_default_path()
    script = runtime_dir / "snips.ahk"
    runtime_paths = _managed_runtime_files(runtime_dir)
    runtime_paths.extend(
        runtime_dir / "data" / f"{item['id']}.txt" for item in config["bindings"] if item["kind"] == "template"
    )
    snapshot = _snapshot([path, *runtime_paths])
    try:
        atomic_write(path, serialize_config(config))
        script, build_id = deploy(config, runtime_dir)
        if executable and start:
            ok, message = start_runtime(executable, script, runtime_dir, build_id)
            if not ok:
                raise RuntimeError(message)
            return message
        return f"Configuration saved to {path}; runtime files generated at {runtime_dir}"
    except Exception:
        _restore(snapshot)
        if executable:
            old_config = load_config(path, missing_ok=True)
            old_script = runtime_dir / "snips.ahk"
            old_id = __import__("hashlib").sha256(repr(old_config).encode("utf-8")).hexdigest()[:16]
            if old_script.exists():
                start_runtime(executable, old_script, runtime_dir, old_id)
        raise


def _read_content(args: argparse.Namespace, required: bool = True) -> str | None:
    if getattr(args, "file", None):
        return _read_exact(args.file)
    content = getattr(args, "content", None)
    if content is None and required:
        raise ConfigError("Provide template text with --content or --file")
    return content


def _binding(config: dict[str, Any], binding_id: str) -> dict[str, Any]:
    for item in config["bindings"]:
        if item["id"] == binding_id:
            return item
    raise ConfigError(f"No binding named {binding_id!r}")


def _run_mutation(
    args: argparse.Namespace, path: Path, config: dict[str, Any], *, backend: Path | None = None
) -> dict[str, Any]:
    config = validate_config(config)
    if not args.apply:
        return {"applied": False, "preview": config, "message": "Dry run; pass --apply to persist this change"}
    message = _apply_config(path, config, executable=backend)
    return {"applied": True, "message": message, "config": str(path)}


def _task_spec(path: Path, interval: str = DEFAULT_WATCHDOG_INTERVAL):
    custom_path = path if path.resolve() != config_default_path().resolve() else None
    return runtime_task_spec(custom_path, interval)


def _startup_status(path: Path, interval: str = DEFAULT_WATCHDOG_INTERVAL) -> dict[str, Any]:
    from runtime_lifecycle import status as task_status

    spec = _task_spec(path, interval)
    task = task_status(spec.owner, spec.name, spec=spec)
    return {
        "configured": task.registration_state == "registered",
        "task": task,
        "legacy_run_value": legacy_startup_value(),
        "last_recovery_error": _last_recovery_error(runtime_default_path()),
    }


def _last_recovery_error(runtime_dir: Path) -> str | None:
    log_path = runtime_dir / "lifecycle.log"
    try:
        lines = log_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        if "recovery failed:" in line:
            return line.split("recovery failed:", 1)[1].strip()
    return None


def _apply_startup(path: Path, interval: str = DEFAULT_WATCHDOG_INTERVAL) -> dict[str, Any]:
    from runtime_lifecycle import apply as apply_task, status as task_status

    executable, _version = find_autohotkey()
    if not executable:
        raise RuntimeError("AutoHotkey v2 is not installed; run `snips install --apply`")
    expected_run = startup_command(executable, runtime_default_path() / "snips.ahk")
    legacy_value = legacy_startup_value()
    if legacy_value is not None and legacy_value != expected_run:
        raise RuntimeError("HKCU Run value 'Snips' contains a different command; refusing to replace or remove it")

    spec = _task_spec(path, interval)
    applied = apply_task(spec)
    verified = task_status(spec.owner, spec.name, spec=spec)
    if verified.registration_state != "registered":
        raise RuntimeError(
            f"Scheduled Task verification failed ({verified.registration_state}); legacy Run value was preserved"
        )
    removed_legacy = remove_legacy_startup(expected_run) if legacy_value == expected_run else False
    return {
        "task": applied,
        "verified": verified,
        "legacy_run_removed": removed_legacy,
        "message": "Scheduled Task is registered and its definition matches the requested snips watchdog",
    }


def _remove_startup(path: Path) -> dict[str, Any]:
    from runtime_lifecycle import remove as remove_task

    executable, _version = find_autohotkey()
    expected_run = startup_command(executable, runtime_default_path() / "snips.ahk") if executable else None
    legacy_value = legacy_startup_value()
    if legacy_value is not None and legacy_value != expected_run:
        raise RuntimeError("HKCU Run value 'Snips' does not match the expected command; refusing to remove it")
    task_removed = remove_task("snips", "runtime")
    legacy_removed = remove_legacy_startup(expected_run) if expected_run and legacy_value == expected_run else False
    return {
        "task_removed": task_removed,
        "legacy_run_removed": legacy_removed,
        "runtime": runtime_status(runtime_default_path()),
        "message": "Scheduled startup removed; an already-running AutoHotkey process may continue until exited",
    }


def _ensure_runtime_command(path: Path, *, apply: bool, quiet: bool) -> tuple[dict[str, Any], int]:
    if not apply:
        return {
            "applied": False,
            "runtime": runtime_status(runtime_default_path()),
            "message": "Preview only; pass --apply to ensure the runtime",
        }, 0
    executable, _version = find_autohotkey()
    if not executable:
        return {"applied": True, "ok": False, "message": "AutoHotkey v2 is not installed"}, 4
    config = _current(path)
    runtime_dir = runtime_default_path()
    source, expected_build, data = generate_script(config, runtime_dir / "data", runtime_dir / "status.txt")
    script = runtime_dir / "snips.ahk"
    needs_deploy = not script.exists() or script.read_text(encoding="utf-8") != source
    if not needs_deploy:
        needs_deploy = any(
            not (runtime_dir / "data" / filename).is_file()
            or (runtime_dir / "data" / filename).read_text(encoding="utf-8") != content
            for filename, content in data.items()
        )
    if needs_deploy:
        script, expected_build = deploy(config, runtime_dir)
    ok, message = ensure_runtime(executable, script, runtime_dir, expected_build)
    silent_noop = quiet and ok and ("already running" in message or "another ensure check" in message)
    return {"applied": True, "ok": ok, "message": message, "quiet_noop": silent_noop}, 0 if ok else 4


def _dispatch_startup(args: argparse.Namespace, path: Path) -> tuple[Any, int]:
    from runtime_lifecycle import disable, enable, preview as preview_task, start, status as task_status, stop

    action = args.startup_command
    if action == "preview":
        return preview_task(_task_spec(path, args.interval)), 0
    if action == "status":
        return _startup_status(path), 0
    if action == "apply":
        if not args.apply:
            return preview_task(_task_spec(path, args.interval)), 0
        return _apply_startup(path, args.interval), 0
    if action == "remove":
        if not args.apply:
            return {
                "applied": False,
                "task": _startup_status(path),
                "legacy_run_value": legacy_startup_value(),
                "message": "Preview only; pass --apply to remove owned startup",
            }, 0
        return _remove_startup(path), 0

    if not args.apply:
        return {
            "applied": False,
            "action": action,
            "task": _startup_status(path),
            "runtime": runtime_status(runtime_default_path()),
            "message": f"Preview only; pass --apply to {action} the scheduled action",
        }, 0

    operations = {"enable": enable, "disable": disable, "start": start, "stop": stop}
    result = operations[action]("snips", "runtime")
    task = task_status("snips", "runtime", spec=_task_spec(path))
    payload: dict[str, Any] = {"applied": True, "action": action, "result": result, "task": task}
    if action == "stop":
        payload["runtime"] = runtime_status(runtime_default_path())
        payload["message"] = "Stopped the scheduled ensure action; an already-running AutoHotkey process may continue"
    return payload, 0


def _install(args: argparse.Namespace, path: Path) -> dict[str, Any]:
    executable, version, backend_message = ensure_autohotkey(apply=args.apply)
    runtime_dir = runtime_default_path()
    script = runtime_dir / "snips.ahk"
    if not args.apply:
        startup_preview: Any = "AutoHotkey must be available before a task preview can be rendered"
        if executable:
            from runtime_lifecycle import preview as preview_task

            startup_preview = preview_task(_task_spec(path, args.interval))
        return {
            "applied": False,
            "backend": backend_message,
            "config": str(path),
            "startup": startup_preview,
            "message": "Dry run; pass --apply to install and configure",
        }
    config = load_config(path, missing_ok=True)
    expected = startup_command(executable, script)
    existing = legacy_startup_value()
    if existing is not None and existing != expected:
        raise RuntimeError(
            "HKCU Run value 'Snips' already exists with a different command; refusing to change or remove it"
        )
    message = _apply_config(path, config, executable=executable, start=not args.skip_start)
    startup_result = _apply_startup(path, args.interval)
    return {
        "applied": True,
        "backend": backend_message,
        "backend_version": version,
        "runtime": message,
        "startup": startup_result,
        "config": str(path),
    }


def _dispatch(args: argparse.Namespace) -> tuple[Any, int]:
    path = _config_path(args)
    command_name = args.command
    if command_name == "install":
        return _install(args, path), 0
    if command_name == "ensure-runtime":
        return _ensure_runtime_command(path, apply=args.apply, quiet=args.quiet)
    if command_name == "startup":
        return _dispatch_startup(args, path)
    config = _current(path)
    if command_name == "add":
        if any(item["id"] == args.id for item in config["bindings"]):
            raise ConfigError(f"Binding {args.id!r} already exists")
        if args.file and args.content is not None:
            raise ConfigError("Use either --content or --file, not both")
        item: dict[str, Any] = {
            "id": args.id,
            "name": args.name,
            "kind": args.kind,
            "hotkey": parse_hotkey(args.hotkey)[0],
            "enabled": True,
        }
        if args.kind == "template":
            item["content"] = _read_content(args)
        elif args.file or args.content is not None:
            raise ConfigError("--content/--file are only valid for template bindings")
        if args.description:
            item["description"] = args.description
        config["bindings"].append(item)
        return _run_mutation(args, path, config), 0
    if command_name == "edit":
        item = _binding(config, args.id)
        content = _read_content(args, required=False)
        if args.file and args.content is not None:
            raise ConfigError("Use either --content or --file, not both")
        if args.name is not None:
            item["name"] = args.name
        if args.description is not None:
            item["description"] = args.description
        if content is not None:
            if item["kind"] != "template":
                raise ConfigError("Only template bindings have editable content")
            item["content"] = content
        if all(value is None for value in (args.name, args.description, content)):
            raise ConfigError("Provide at least one of --name, --description, --content, or --file")
        return _run_mutation(args, path, config), 0
    if command_name == "bind":
        _binding(config, args.id)["hotkey"] = parse_hotkey(args.hotkey)[0]
        return _run_mutation(args, path, config), 0
    if command_name == "remove":
        _binding(config, args.id)
        config["bindings"] = [item for item in config["bindings"] if item["id"] != args.id]
        return _run_mutation(args, path, config), 0
    if command_name in {"enable", "disable"}:
        _binding(config, args.id)["enabled"] = command_name == "enable"
        return _run_mutation(args, path, config), 0
    if command_name == "list":
        return {"config": str(path), "bindings": config["bindings"]}, 0
    if command_name == "show":
        return _binding(config, args.id), 0
    if command_name == "status":
        executable, version = find_autohotkey()
        runtime = runtime_status(runtime_default_path())
        startup = _startup_status(path)
        return {
            "backend": str(executable) if executable else None,
            "backend_version": version,
            "runtime": runtime,
            "startup": startup,
            "legacy_run_value": legacy_startup_value(),
            "config": str(path),
            "config_exists": path.exists(),
            "config_valid": True,
        }, 0
    if command_name == "doctor":
        executable, version = find_autohotkey()
        runtime = runtime_status(runtime_default_path())
        power_toys_file = (
            Path.home() / "AppData" / "Local" / "Microsoft" / "PowerToys" / "Keyboard Manager" / "default.json"
        )
        power_toys_detail = (
            f"Found Keyboard Manager remaps at {power_toys_file}; shortcut meanings are not safely inferred from its versioned file"
            if power_toys_file.exists()
            else "No Keyboard Manager remap file found; unrelated AutoHotkey hotkeys remain unenumerable"
        )
        startup_detail = _startup_status(path)
        checks = [
            {
                "name": "configuration",
                "ok": True,
                "detail": f"{len(config['bindings'])} binding(s), schema {config['schema_version']}",
            },
            {
                "name": "AutoHotkey v2",
                "ok": executable is not None,
                "detail": f"{executable} (v{version})" if executable else "not installed",
            },
            {"name": "runtime", "ok": runtime["running"], "detail": runtime},
            {
                "name": "startup",
                "ok": bool(startup_detail.get("configured")),
                "detail": startup_detail,
            },
            {
                "name": "external conflicts",
                "ok": True,
                "detail": power_toys_detail + "; runtime registration errors are reported on startup",
            },
        ]
        return {"checks": checks, "ok": all(item["ok"] for item in checks)}, 0 if all(
            item["ok"] for item in checks
        ) else 4
    if command_name == "reload":
        if not args.apply:
            return {"applied": False, "message": "Dry run; pass --apply to reload the runtime"}, 0
        executable, _ = find_autohotkey()
        if not executable:
            raise RuntimeError("AutoHotkey v2 is not installed; run `snips install --apply`")
        from snips.runtime import generate_script

        _, build_id, _ = generate_script(config, runtime_default_path() / "data", runtime_default_path() / "status.txt")
        ok, message = start_runtime(executable, runtime_default_path() / "snips.ahk", runtime_default_path(), build_id)
        return {"applied": ok, "message": message}, 0 if ok else 4
    if command_name == "export":
        content = serialize_config(config)
        if not args.apply:
            return {
                "applied": False,
                "output": str(args.output),
                "preview": content,
                "message": "Dry run; pass --apply to write the export",
            }, 0
        atomic_write(args.output, content)
        return {"applied": True, "output": str(args.output), "bindings": len(config["bindings"])}, 0
    if command_name == "import":
        try:
            imported = validate_config(json.loads(_read_exact(args.input_file)))
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            raise ConfigError(f"Could not read import file {args.input_file}: {exc}") from exc
        if args.replace:
            config = imported
        else:
            by_id = {item["id"]: item for item in config["bindings"]}
            by_id.update({item["id"]: item for item in imported["bindings"]})
            config = validate_config(
                {"schema_version": 1, "settings": imported["settings"], "bindings": list(by_id.values())}
            )
        result = _run_mutation(args, path, config)
        result["imported_bindings"] = len(imported["bindings"])
        return result, 0
    raise ConfigError(f"Unknown command: {command_name}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result, code = _dispatch(args)
        if isinstance(result, dict) and result.pop("quiet_noop", False):
            return code
        _print(result, args.json)
        return code
    except (ConfigError, OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        if args.json:
            _print({"error": str(exc)}, True)
        else:
            print(f"snips: error: {exc}", file=sys.stderr)
        return 2 if isinstance(exc, ConfigError) else 3 if isinstance(exc, OSError) else 4


if __name__ == "__main__":
    raise SystemExit(main())
