from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from .config import default_config_path, load_config, save_config, set_dotted
from .models import ExecutableCandidate, GameRecord, SaveSource
from .retention import parse_interval, parse_retention
from .scheduler import install_scheduler, remove_scheduler, scheduler_health, scheduler_plan
from .service import GameService
from .sessions import ProcessMatcher
from .stats import doctor, game_detail, overview, render_game_timeline, render_hourly_histogram, render_overall_timeline, render_playtime_bars
from .ui import WatchDashboard
from .utils import iso_now, stable_game_id
from .watcher import GameWatcher


EXIT_OK = 0
EXIT_WARN = 1
EXIT_ERROR = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="saved-game-archiver",
        description=(
            "Discover installed games and save locations, track gameplay sessions, archive every distinct save state, "
            "and visualize save/play history. Mutating commands preview by default and require --apply."
        ),
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=(
            "Core areas:\n"
            "  config    Persistent JSON configuration and game roots\n"
            "  schedule  Normal/running backup policies and OS scheduler\n"
            "  modify    Scan games, correct executables/save sources/state indices, export saves\n"
            "  stats     Health, per-game details, save timelines, playtime visualizations\n"
            "  watch     Track running games, sessions, playtime, and in-session save writes\n"
            "  run       Noninteractive maintenance/capture operations for the scheduler"
        ),
    )
    parser.add_argument("-c", "--config", dest="config_path", type=Path, default=None, help="JSON configuration path.")
    parser.add_argument("-d", "--data-root", type=Path, default=None, help="Override catalog/events state directory.")
    parser.add_argument("-j", "--json", action="store_true", help="Emit JSON where supported.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Emit additional diagnostics.")
    areas = parser.add_subparsers(dest="area", required=True)
    _add_config_parser(areas)
    _add_schedule_parser(areas)
    _add_modify_parser(areas)
    _add_stats_parser(areas)
    _add_watch_parser(areas)
    _add_run_parser(areas)
    return parser


def _add_apply(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-y", "--apply", action="store_true", help="Apply the previewed mutation.")


def _add_config_parser(areas: argparse._SubParsersAction) -> None:
    parser = areas.add_parser("config", help="Inspect or change persistent JSON configuration.")
    ops = parser.add_subparsers(dest="config_command", required=True)
    show = ops.add_parser("show", help="Show the effective configuration.")
    show.set_defaults(handler=handle_config_show)
    set_parser = ops.add_parser("set", help="Set a dotted configuration key.")
    set_parser.add_argument("key")
    set_parser.add_argument("value")
    _add_apply(set_parser)
    set_parser.set_defaults(handler=handle_config_set)
    root = ops.add_parser("game-root", help="Manage directories whose child folders are treated as installed games.")
    root_ops = root.add_subparsers(dest="game_root_command", required=True)
    root_list = root_ops.add_parser("list", help="List configured game roots.")
    root_list.set_defaults(handler=handle_game_root_list)
    for name, handler in (("add", handle_game_root_add), ("remove", handle_game_root_remove)):
        child = root_ops.add_parser(name, help=f"{name.title()} a configured game root.")
        child.add_argument("path", type=Path)
        _add_apply(child)
        child.set_defaults(handler=handler)
    archive = ops.add_parser("archive-root", help="Set the local archive root (may be a Google Drive-synced directory).")
    archive.add_argument("path", type=Path)
    _add_apply(archive)
    archive.set_defaults(handler=handle_archive_root)
    manifest = ops.add_parser("manifest", help="Manage the cached Ludusavi manifest.")
    manifest_ops = manifest.add_subparsers(dest="manifest_command", required=True)
    refresh = manifest_ops.add_parser("refresh", help="Refresh the primary save-location manifest using ETag caching.")
    _add_apply(refresh)
    refresh.set_defaults(handler=handle_manifest_refresh)


def _add_schedule_parser(areas: argparse._SubParsersAction) -> None:
    parser = areas.add_parser("schedule", help="Configure backup retention/running focus and reconcile OS scheduling.")
    ops = parser.add_subparsers(dest="schedule_command")
    parser.set_defaults(handler=handle_schedule_show, schedule_command="show")
    show = ops.add_parser("show", help="Show effective backup policies and scheduler plan.")
    show.set_defaults(handler=handle_schedule_show)
    set_parser = ops.add_parser("set", help="Set normal GFS retention and maintenance check cadence.")
    set_parser.add_argument("-r", "--retention", default=None, help="GFS retention, e.g. '24h 7d 4w 12m'.")
    set_parser.add_argument("-m", "--maintenance-interval", default=None, help="Inactive-game safety check cadence, e.g. 15m.")
    _add_apply(set_parser)
    set_parser.set_defaults(handler=handle_schedule_set)
    running = ops.add_parser("running", help="Set rates/retention used while a game is running.")
    running.add_argument("-r", "--rates", nargs="+", default=None, help="Running rates: 'change' plus optional intervals, e.g. change 15m.")
    running.add_argument("-s", "--settle-seconds", type=float, default=None, help="Quiescence before capturing a write burst.")
    running.add_argument("-k", "--keep-cycles", type=int, default=None, help="Gameplay cycles of in-session snapshots to retain.")
    running.add_argument("-e", "--exit-keep", type=int, default=None, help="Number of exit checkpoints retained per game.")
    _add_apply(running)
    running.set_defaults(handler=handle_schedule_running)
    install = ops.add_parser("install", help="Install/reconcile watcher and maintenance OS tasks.")
    _add_apply(install)
    install.set_defaults(handler=handle_schedule_install)
    remove = ops.add_parser("remove", help="Remove Saved Game Archiver OS tasks.")
    _add_apply(remove)
    remove.set_defaults(handler=handle_schedule_remove)


def _add_modify_parser(areas: argparse._SubParsersAction) -> None:
    parser = areas.add_parser("modify", help="Discover/correct tracked games and export save history.")
    ops = parser.add_subparsers(dest="modify_command", required=True)
    scan = ops.add_parser("scan", help="Scan Steam and configured game roots, then resolve save paths.")
    scan.add_argument("-r", "--refresh-manifest", action="store_true", help="Refresh Ludusavi manifest first if needed.")
    _add_apply(scan)
    scan.set_defaults(handler=handle_modify_scan)
    game = ops.add_parser("game", help="Manually add/remove/enable tracked games.")
    game_ops = game.add_subparsers(dest="game_command", required=True)
    add = game_ops.add_parser("add", help="Add a game not found by automatic discovery.")
    add.add_argument("name")
    add.add_argument("-i", "--install-dir", type=Path, required=True, help="Game installation directory.")
    add.add_argument("-s", "--steam-app-id", type=int, default=None, help="Optional Steam application ID.")
    _add_apply(add)
    add.set_defaults(handler=handle_game_add)
    remove = game_ops.add_parser("remove", help="Remove a game from tracking (archive data is preserved).")
    remove.add_argument("game")
    _add_apply(remove)
    remove.set_defaults(handler=handle_game_remove)
    exe = ops.add_parser("exe", help="Inspect or correct executable detection for a game.")
    exe_ops = exe.add_subparsers(dest="exe_command", required=True)
    exe_list = exe_ops.add_parser("list", help="List executable candidates.")
    exe_list.add_argument("game")
    exe_list.set_defaults(handler=handle_exe_list)
    exe_add = exe_ops.add_parser("add", help="Add a manual executable override.")
    exe_add.add_argument("game")
    exe_add.add_argument("path", type=Path)
    _add_apply(exe_add)
    exe_add.set_defaults(handler=handle_exe_add)
    exe_remove = exe_ops.add_parser("remove", help="Remove/disable an executable candidate.")
    exe_remove.add_argument("game")
    exe_remove.add_argument("path", type=Path)
    _add_apply(exe_remove)
    exe_remove.set_defaults(handler=handle_exe_remove)
    source = ops.add_parser("save-source", help="Inspect or correct save file/registry sources.")
    source_ops = source.add_subparsers(dest="source_command", required=True)
    source_list = source_ops.add_parser("list", help="List save sources.")
    source_list.add_argument("game")
    source_list.set_defaults(handler=handle_source_list)
    source_add = source_ops.add_parser("add", help="Add a manual filesystem or registry save source.")
    source_add.add_argument("game")
    source_add.add_argument("path")
    source_add.add_argument("-k", "--kind", choices=("files", "registry"), default="files", help="Save source kind.")
    _add_apply(source_add)
    source_add.set_defaults(handler=handle_source_add)
    source_remove = source_ops.add_parser("remove", help="Remove a save source by ID.")
    source_remove.add_argument("game")
    source_remove.add_argument("source_id")
    _add_apply(source_remove)
    source_remove.set_defaults(handler=handle_source_remove)
    state = ops.add_parser("state", help="Inspect or override persistent logical save-state indices.")
    state_ops = state.add_subparsers(dest="state_command", required=True)
    state_list = state_ops.add_parser("list", help="List state keys and stable indices.")
    state_list.add_argument("game")
    state_list.set_defaults(handler=handle_state_list)
    state_set = state_ops.add_parser("set", help="Force a state key to a specific stable index.")
    state_set.add_argument("game")
    state_set.add_argument("state_key")
    state_set.add_argument("index", type=int)
    _add_apply(state_set)
    state_set.set_defaults(handler=handle_state_set)
    export = ops.add_parser("export", help="Export latest or complete save history without overwriting by default.")
    export_ops = export.add_subparsers(dest="export_command", required=True)
    for name, handler in (("latest", handle_export_latest), ("history", handle_export_history)):
        child = export_ops.add_parser(name, help=f"Export {name} save snapshots.")
        child.add_argument("game", nargs="?", default=None, help="Game selector; omit with --all for every game.")
        child.add_argument("-a", "--all", action="store_true", help="Export every tracked game.")
        child.add_argument("-o", "--output-dir", type=Path, required=True, help="Export destination root.")
        child.add_argument("-f", "--force", action="store_true", help="Allow existing export directories to be reused.")
        _add_apply(child)
        child.set_defaults(handler=handler)


def _add_stats_parser(areas: argparse._SubParsersAction) -> None:
    parser = areas.add_parser("stats", help="Inspect protection state, gameplay history, and visualizations.")
    ops = parser.add_subparsers(dest="stats_command")
    parser.set_defaults(handler=handle_stats_overview, stats_command="overview")
    overview_parser = ops.add_parser("overview", help="Show high-level protection/playtime statistics.")
    overview_parser.set_defaults(handler=handle_stats_overview)
    game = ops.add_parser("game", help="Show detailed information for one game.")
    game.add_argument("game")
    game.set_defaults(handler=handle_stats_game)
    timeline = ops.add_parser("timeline", help="Show per-save-state timeline for one game.")
    timeline.add_argument("game")
    timeline.add_argument("-w", "--width", type=int, default=None, help="Timeline width.")
    timeline.set_defaults(handler=handle_stats_timeline)
    all_timeline = ops.add_parser("all-timeline", help="Visualize gameplay intervals across all/selected games.")
    all_timeline.add_argument("-g", "--game", action="append", default=[], help="Limit to selected game; repeatable.")
    all_timeline.add_argument("-w", "--width", type=int, default=None, help="Timeline width.")
    all_timeline.set_defaults(handler=handle_stats_all_timeline)
    playtime = ops.add_parser("playtime", help="Show total playtime graph for tracked games.")
    playtime.add_argument("-w", "--width", type=int, default=None, help="Graph width.")
    playtime.set_defaults(handler=handle_stats_playtime)
    hourly = ops.add_parser("hourly", help="Show gaming frequency by local hour of day.")
    hourly.add_argument("-g", "--game", action="append", default=[], help="Limit to selected game; repeatable.")
    hourly.set_defaults(handler=handle_stats_hourly)
    doc = ops.add_parser("doctor", help="Audit catalog/archive/scheduler alignment and missing protection.")
    doc.add_argument("-s", "--scheduler", action="store_true", help="Also query OS scheduler state.")
    doc.set_defaults(handler=handle_stats_doctor)


def _add_watch_parser(areas: argparse._SubParsersAction) -> None:
    parser = areas.add_parser("watch", help="Run the session/save-change watcher.")
    parser.add_argument("-P", "--plain", action="store_true", help="Disable TermDash live dashboard.")
    parser.add_argument("-o", "--once", action="store_true", help="Run one watcher tick and exit.")
    parser.add_argument("-s", "--scan-first", action="store_true", help="Run installation/save discovery before watching.")
    parser.set_defaults(handler=handle_watch)


def _add_run_parser(areas: argparse._SubParsersAction) -> None:
    parser = areas.add_parser("run", help="Noninteractive operations intended for the OS scheduler.")
    ops = parser.add_subparsers(dest="run_command", required=True)
    cycle = ops.add_parser("cycle", help="Scan and capture changed saves for inactive games, then prune retention.")
    cycle.set_defaults(handler=handle_run_cycle)
    backup = ops.add_parser("backup", help="Capture one specific game immediately.")
    backup.add_argument("game")
    backup.add_argument("-r", "--reason", default="manual", help="Snapshot reason label.")
    backup.set_defaults(handler=handle_run_backup)


def _service(args: argparse.Namespace) -> GameService:
    return GameService(config_path=args.config_path, data_root=args.data_root)


def _config_target(args: argparse.Namespace) -> Path:
    return args.config_path or default_config_path()


def _print_preview(args: argparse.Namespace, message: str, payload: Any | None = None) -> None:
    if args.json:
        print(json.dumps({"apply": bool(getattr(args, "apply", False)), "message": message, "payload": payload}, indent=2, default=str))
    else:
        prefix = "APPLY" if getattr(args, "apply", False) else "DRY-RUN"
        print(f"[{prefix}] {message}")
        if payload is not None:
            if isinstance(payload, (dict, list)):
                print(json.dumps(payload, indent=2, default=str))
            else:
                print(payload)


def handle_config_show(args: argparse.Namespace) -> int:
    print(json.dumps(load_config(args.config_path), indent=2, sort_keys=True))
    return EXIT_OK


def _parse_config_value(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def handle_config_set(args: argparse.Namespace) -> int:
    config = load_config(args.config_path)
    set_dotted(config, args.key, _parse_config_value(args.value))
    _print_preview(args, f"set {args.key}", _parse_config_value(args.value))
    if args.apply:
        save_config(config, _config_target(args))
    return EXIT_OK


def handle_game_root_list(args: argparse.Namespace) -> int:
    for root in load_config(args.config_path).get("game_roots", []):
        print(root)
    return EXIT_OK


def _game_root_change(args: argparse.Namespace, add: bool) -> int:
    config = load_config(args.config_path)
    path = str(args.path.expanduser().resolve())
    roots = list(config.get("game_roots", []))
    if add and path not in roots:
        roots.append(path)
    if not add:
        roots = [item for item in roots if item.casefold() != path.casefold()]
    config["game_roots"] = roots
    _print_preview(args, f"{'add' if add else 'remove'} game root {path}")
    if args.apply:
        save_config(config, _config_target(args))
        service = _service(args)
        service.config = config
        service.scan(persist=True)
    return EXIT_OK


def handle_game_root_add(args: argparse.Namespace) -> int:
    return _game_root_change(args, True)


def handle_game_root_remove(args: argparse.Namespace) -> int:
    return _game_root_change(args, False)


def handle_archive_root(args: argparse.Namespace) -> int:
    config = load_config(args.config_path)
    config["archive_root"] = str(args.path.expanduser().resolve())
    _print_preview(args, "set archive root", config["archive_root"])
    if args.apply:
        save_config(config, _config_target(args))
    return EXIT_OK


def handle_manifest_refresh(args: argparse.Namespace) -> int:
    service = _service(args)
    _print_preview(args, "refresh Ludusavi manifest", service.config["manifest"]["url"])
    if args.apply:
        path, changed = service.refresh_manifest()
        print(f"manifest: {path} ({'updated' if changed else 'unchanged'})")
    return EXIT_OK


def handle_schedule_show(args: argparse.Namespace) -> int:
    config = load_config(args.config_path)
    payload = {
        "normal_retention": config["backup"]["normal_retention"],
        "running_rates": config["backup"]["running_rates"],
        "running_settle_seconds": config["backup"]["running_settle_seconds"],
        "in_session_keep_cycles": config["backup"]["in_session_keep_cycles"],
        "exit_checkpoint_keep": config["backup"]["exit_checkpoint_keep"],
        "maintenance_interval": config["backup"]["maintenance_interval"],
        "scheduler_plan": scheduler_plan(config, args.config_path),
    }
    print(json.dumps(payload, indent=2, default=str) if args.json else _format_schedule(payload))
    return EXIT_OK


def _format_schedule(payload: dict[str, Any]) -> str:
    lines = [
        f"Normal retention: {payload['normal_retention']}",
        f"Running rates: {' '.join(payload['running_rates'])}",
        f"Running settle: {payload['running_settle_seconds']}s",
        f"In-session cycles retained: {payload['in_session_keep_cycles']}",
        f"Exit checkpoints retained: {payload['exit_checkpoint_keep']}",
        f"Maintenance interval: {payload['maintenance_interval']}",
        "OS scheduler plan:",
    ]
    for item in payload["scheduler_plan"]:
        lines.append("  " + (" ".join(item) if isinstance(item, list) else item))
    return "\n".join(lines)


def handle_schedule_set(args: argparse.Namespace) -> int:
    config = load_config(args.config_path)
    if args.retention:
        parse_retention(args.retention)
        config["backup"]["normal_retention"] = args.retention
    if args.maintenance_interval:
        parse_interval(args.maintenance_interval)
        config["backup"]["maintenance_interval"] = args.maintenance_interval
    _print_preview(args, "update normal backup schedule", config["backup"])
    if args.apply:
        save_config(config, _config_target(args))
        install_scheduler(config, _config_target(args), apply=True)
    return EXIT_OK


def handle_schedule_running(args: argparse.Namespace) -> int:
    config = load_config(args.config_path)
    if args.rates is not None:
        for rate in args.rates:
            if rate != "change":
                parse_interval(rate)
        config["backup"]["running_rates"] = args.rates
    if args.settle_seconds is not None:
        if args.settle_seconds < 0:
            raise ValueError("settle seconds must be non-negative")
        config["backup"]["running_settle_seconds"] = args.settle_seconds
    if args.keep_cycles is not None:
        if args.keep_cycles < 1:
            raise ValueError("keep cycles must be >= 1")
        config["backup"]["in_session_keep_cycles"] = args.keep_cycles
    if args.exit_keep is not None:
        if args.exit_keep < 1:
            raise ValueError("exit checkpoint retention must be >= 1")
        config["backup"]["exit_checkpoint_keep"] = args.exit_keep
    _print_preview(args, "update running-game focus", config["backup"])
    if args.apply:
        save_config(config, _config_target(args))
        install_scheduler(config, _config_target(args), apply=True)
    return EXIT_OK


def handle_schedule_install(args: argparse.Namespace) -> int:
    config = load_config(args.config_path)
    commands = install_scheduler(config, args.config_path, apply=args.apply)
    _print_preview(args, "reconcile OS scheduler", commands)
    return EXIT_OK


def handle_schedule_remove(args: argparse.Namespace) -> int:
    config = load_config(args.config_path)
    commands = remove_scheduler(config, apply=args.apply)
    _print_preview(args, "remove OS scheduler tasks", commands)
    return EXIT_OK


def handle_modify_scan(args: argparse.Namespace) -> int:
    service = _service(args)
    before = set(service.games)
    if args.refresh_manifest and args.apply:
        try:
            service.refresh_manifest()
        except OSError as exc:
            print(f"manifest refresh failed: {exc}", file=sys.stderr)
    new_ids = service.scan(refresh_manifest_if_missing=args.refresh_manifest, persist=args.apply)
    payload = [{"id": game_id, "name": service.games[game_id].name, "status": service.games[game_id].status} for game_id in new_ids]
    _print_preview(args, f"scan found {len(service.games)} games ({len(set(service.games) - before)} new)", payload)
    return EXIT_OK


def handle_game_add(args: argparse.Namespace) -> int:
    service = _service(args)
    game_id = stable_game_id(args.name, args.steam_app_id, str(args.install_dir))
    game = GameRecord(
        id=game_id,
        name=args.name,
        install_dirs=[str(args.install_dir.expanduser().resolve())],
        steam_app_id=args.steam_app_id,
        discovery_origins=["manual"],
        first_seen_at=iso_now(),
    )
    _print_preview(args, f"add tracked game {args.name}", game.to_dict())
    if args.apply:
        service.games[game_id] = game
        service.scan(persist=True)
    return EXIT_OK


def handle_game_remove(args: argparse.Namespace) -> int:
    service = _service(args)
    game = service.get_game(args.game)
    _print_preview(args, f"remove {game.name} from catalog; archive remains untouched")
    if args.apply:
        del service.games[game.id]
        service.store.save_catalog(service.games)
        service.store.append_event({"type": "game_removed", "timestamp": iso_now(), "game_id": game.id})
    return EXIT_OK


def handle_exe_list(args: argparse.Namespace) -> int:
    game = _service(args).get_game(args.game)
    for item in sorted(game.executables, key=lambda x: (-x.score, x.path.casefold())):
        print(f"{item.score:.2f}\t{item.origin}\truns={item.observed_runs}\t{item.path}")
    return EXIT_OK


def handle_exe_add(args: argparse.Namespace) -> int:
    service = _service(args)
    game = service.get_game(args.game)
    path = str(args.path.expanduser().resolve())
    _print_preview(args, f"add manual executable to {game.name}", path)
    if args.apply:
        if not any(Path(item.path) == Path(path) for item in game.executables):
            game.executables.append(ExecutableCandidate(path, 1.0, "manual"))
        service.store.save_catalog(service.games)
    return EXIT_OK


def handle_exe_remove(args: argparse.Namespace) -> int:
    service = _service(args)
    game = service.get_game(args.game)
    target = str(args.path.expanduser().resolve()).casefold()
    _print_preview(args, f"disable executable for {game.name}", str(args.path))
    if args.apply:
        for item in game.executables:
            if str(Path(item.path)).casefold() == target:
                item.enabled = False
        service.store.save_catalog(service.games)
    return EXIT_OK


def handle_source_list(args: argparse.Namespace) -> int:
    game = _service(args).get_game(args.game)
    for item in game.save_sources:
        print(f"{item.id}\t{item.kind}\t{item.origin}\t{item.confidence:.2f}\t{item.path}")
    return EXIT_OK


def handle_source_add(args: argparse.Namespace) -> int:
    service = _service(args)
    game = service.get_game(args.game)
    source = SaveSource(f"manual-{args.kind}-{len(game.save_sources):03d}", args.kind, args.path, "manual", 1.0)
    _print_preview(args, f"add save source to {game.name}", source.to_dict())
    if args.apply:
        game.save_sources.append(source)
        service.store.save_catalog(service.games)
    return EXIT_OK


def handle_source_remove(args: argparse.Namespace) -> int:
    service = _service(args)
    game = service.get_game(args.game)
    _print_preview(args, f"remove save source {args.source_id} from {game.name}")
    if args.apply:
        game.save_sources = [item for item in game.save_sources if item.id != args.source_id]
        service.store.save_catalog(service.games)
    return EXIT_OK


def handle_state_list(args: argparse.Namespace) -> int:
    game = _service(args).get_game(args.game)
    for key, index in sorted(game.save_states.items(), key=lambda item: (item[1], item[0])):
        marker = "manual" if key in game.state_overrides else "auto"
        print(f"{index}\t{marker}\t{key}")
    return EXIT_OK


def handle_state_set(args: argparse.Namespace) -> int:
    if args.index < 0:
        raise ValueError("state index must be non-negative")
    service = _service(args)
    game = service.get_game(args.game)
    for key, existing_index in game.save_states.items():
        if key != args.state_key and int(existing_index) == args.index:
            raise ValueError(f"state index {args.index} is already assigned to {key!r}; indices must remain unique")
    _print_preview(args, f"set save-state index for {game.name}", {args.state_key: args.index})
    if args.apply:
        game.state_overrides[args.state_key] = args.index
        game.save_states[args.state_key] = args.index
        service.store.save_catalog(service.games)
    return EXIT_OK


def _selected_games(service: GameService, selector: str | None, all_games: bool) -> list[GameRecord]:
    if all_games:
        return list(service.games.values())
    if selector is None:
        raise ValueError("Specify a game or use --all")
    return [service.get_game(selector)]


def handle_export_latest(args: argparse.Namespace) -> int:
    service = _service(args)
    games = _selected_games(service, args.game, args.all)
    exports: list[str] = []
    for game in games:
        manifest = service.archive.latest_manifest(game)
        if manifest is None:
            continue
        target = args.output_dir / game.name / manifest.snapshot_id
        exports.append(str(target))
        if args.apply:
            service.archive.export_snapshot(game, manifest.snapshot_id, args.output_dir, overwrite=args.force)
    _print_preview(args, f"export latest snapshots for {len(games)} game(s)", exports)
    return EXIT_OK


def handle_export_history(args: argparse.Namespace) -> int:
    service = _service(args)
    games = _selected_games(service, args.game, args.all)
    exports: list[str] = []
    for game in games:
        for manifest in service.archive.list_manifests(game.id):
            exports.append(str(args.output_dir / game.name / manifest.snapshot_id))
            if args.apply:
                service.archive.export_snapshot(game, manifest.snapshot_id, args.output_dir, overwrite=args.force)
    _print_preview(args, f"export {len(exports)} restore point(s)", exports)
    return EXIT_OK


def handle_stats_overview(args: argparse.Namespace) -> int:
    print(overview(_service(args)))
    return EXIT_OK


def handle_stats_game(args: argparse.Namespace) -> int:
    service = _service(args)
    print(game_detail(service, service.get_game(args.game)))
    return EXIT_OK


def handle_stats_timeline(args: argparse.Namespace) -> int:
    service = _service(args)
    print(render_game_timeline(service, service.get_game(args.game), width=args.width))
    return EXIT_OK


def handle_stats_all_timeline(args: argparse.Namespace) -> int:
    service = _service(args)
    print(render_overall_timeline(service, width=args.width, selectors=args.game))
    return EXIT_OK


def handle_stats_playtime(args: argparse.Namespace) -> int:
    print(render_playtime_bars(_service(args), width=args.width))
    return EXIT_OK


def handle_stats_hourly(args: argparse.Namespace) -> int:
    print(render_hourly_histogram(_service(args), selectors=args.game))
    return EXIT_OK


def handle_stats_doctor(args: argparse.Namespace) -> int:
    service = _service(args)
    code, text = doctor(service)
    if args.scheduler:
        healthy, missing = scheduler_health(service.config)
        text += "\n" + ("OK     OS scheduler tasks present" if healthy else f"WARN   scheduler missing: {', '.join(missing)}")
        if not healthy and code == 0:
            code = 1
    print(text)
    return code


def handle_watch(args: argparse.Namespace) -> int:
    service = _service(args)
    if args.scan_first:
        service.scan(refresh_manifest_if_missing=False, persist=True)
    watcher = GameWatcher(service)
    if args.plain:
        watcher.run(once=args.once)
        return EXIT_OK
    try:
        with WatchDashboard(service.games) as dashboard:
            watcher.run(once=args.once, dashboard=dashboard)
    except ImportError:
        watcher.run(once=args.once)
    return EXIT_OK


def handle_run_cycle(args: argparse.Namespace) -> int:
    service = _service(args)
    service.scan(refresh_manifest_if_missing=False, persist=True)
    running = ProcessMatcher(float(service.config["watcher"]["auto_accept_executable_score"])).scan(service.games)
    changed = 0
    for game in service.games.values():
        if not game.enabled or running.get(game.id):
            continue
        result = service.capture(game, reason="scheduled", session_id=None, playtime_seconds=game.effective_playtime_seconds)
        changed += int(result.changed)
        service.prune(game)
    print(f"maintenance cycle complete: {len(service.games)} tracked, {changed} changed restore point(s) created")
    return EXIT_OK


def handle_run_backup(args: argparse.Namespace) -> int:
    service = _service(args)
    game = service.get_game(args.game)
    result = service.capture(game, reason=args.reason, session_id=game.active_session_id, playtime_seconds=game.effective_playtime_seconds)
    print(json.dumps(result.__dict__, indent=2) if args.json else result)
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
        return int(args.handler(args))
    except (ValueError, KeyError, OSError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"{parser.prog}: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:
        print(f"{parser.prog}: interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
