from __future__ import annotations

import math
import shutil
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

from .models import GameRecord
from .service import GameService
from .utils import format_playtime, parse_iso


BLOCKS = " ▁▂▃▄▅▆▇█"
GAME_GLYPHS = "●■◆▲▼★✦✚✖◉◇"


def human_bytes(value: int) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    number = float(max(0, value))
    index = 0
    while number >= 1024 and index < len(units) - 1:
        number /= 1024
        index += 1
    return f"{number:.1f} {units[index]}" if index else f"{int(number)} B"


def archive_size(root: Path) -> int:
    total = 0
    if root.exists():
        for path in root.rglob("*"):
            if path.is_file():
                try:
                    total += path.stat().st_size
                except OSError:
                    pass
    return total


def overview(service: GameService) -> str:
    games = list(service.games.values())
    protected = sum(1 for game in games if game.last_snapshot_id)
    unresolved = sum(1 for game in games if not game.save_sources)
    running = sum(1 for game in games if game.active_session_id)
    total_playtime = sum(game.effective_playtime_seconds for game in games)
    lines = [
        "Saved Game Archiver",
        "=" * 72,
        f"Tracked games: {len(games)}  Protected: {protected}  Waiting for save: {unresolved}  Running: {running}",
        f"Tracked/imported playtime: {format_playtime(total_playtime)}",
        f"Archive storage: {human_bytes(archive_size(service.archive.root))}",
        f"Default retention: {service.config['backup']['normal_retention']}",
        f"Running rates: {' '.join(service.config['backup']['running_rates'])}",
        f"Exit checkpoints/game: {service.config['backup']['exit_checkpoint_keep']}",
        "",
    ]
    for game in sorted(games, key=lambda item: item.name.casefold()):
        lines.append(game_summary_line(game, service))
    return "\n".join(lines)


def game_summary_line(game: GameRecord, service: GameService) -> str:
    manifests = service.archive.list_manifests(game.id)
    return (
        f"{game.name:<32.32} {game.status:<20.20} "
        f"play={format_playtime(game.effective_playtime_seconds):>13} "
        f"states={len(set(game.save_states.values())):>2} snapshots={len(manifests):>3}"
    )


def game_detail(service: GameService, game: GameRecord) -> str:
    manifests = service.archive.list_manifests(game.id)
    physical = 0
    referenced: set[str] = set()
    for manifest in manifests:
        for entry in manifest.entries:
            referenced.add(entry.blob_sha256)
    for digest in referenced:
        path = service.archive.blobs_root / digest[:2] / digest
        try:
            physical += path.stat().st_size
        except OSError:
            pass
    latest = manifests[-1] if manifests else None
    lines = [
        game.name,
        "=" * min(88, max(20, len(game.name))),
        f"ID: {game.id}",
        f"Status: {game.status}",
        f"Steam app ID: {game.steam_app_id or '-'}",
        f"Playtime: {format_playtime(game.effective_playtime_seconds)} "
        f"(tracked {format_playtime(game.tracked_playtime_seconds)}, "
        f"imported baseline {format_playtime(game.imported_playtime_seconds)})",
        f"First tracked: {game.first_seen_at or '-'}",
        f"First play: {game.first_play_at or '-'}",
        f"Last play: {game.last_play_at or '-'}",
        f"Last checked: {game.last_checked_at or '-'}",
        f"Last changed: {game.last_changed_at or '-'}",
        f"Latest restore point: {latest.created_at if latest else '-'}",
        f"Restore points: {len(manifests)}; exit checkpoints: {len(game.exit_checkpoints)}",
        f"Save sources: {len(game.save_sources)}; logical states: {len(set(game.save_states.values()))}",
        f"Referenced physical data: {human_bytes(physical)}",
        "",
        "Executables:",
    ]
    for exe in sorted(game.executables, key=lambda item: (-item.score, item.path.casefold())):
        lines.append(f"  {exe.score:0.2f} {exe.origin:<18} runs={exe.observed_runs:<3} {exe.path}")
    lines.append("Save sources:")
    for source in game.save_sources:
        lines.append(f"  [{source.kind}] {source.origin} confidence={source.confidence:.2f} {source.path}")
    return "\n".join(lines)


def render_game_timeline(service: GameService, game: GameRecord, *, width: int | None = None) -> str:
    manifests = service.archive.list_manifests(game.id)
    events = list(service.store.iter_events(game_id=game.id, types={"session_start", "session_end", "exit_checkpoint"}))
    if not manifests and not events:
        return f"{game.name}: no timeline events yet"
    timestamps = [parse_iso(item.created_at) for item in manifests]
    timestamps.extend(parse_iso(item["timestamp"]) for item in events if item.get("timestamp"))
    start, end = min(timestamps), max(timestamps)
    columns = _timeline_columns(width)
    rows: dict[int, list[str]] = {}
    known_indices = sorted(set(game.save_states.values()))
    for index in known_indices:
        rows[index] = [" "] * columns
    for manifest in manifests:
        col = _time_to_column(parse_iso(manifest.created_at), start, end, columns)
        indices = manifest.state_indices_changed or sorted({entry.state_index for entry in manifest.entries})
        marker = "◆" if manifest.reason == "session_exit" else ("•" if manifest.reason == "in_session" else "●")
        for index in indices:
            rows.setdefault(index, [" "] * columns)[col] = marker
    session_row = [" "] * columns
    starts: dict[str, datetime] = {}
    for event in events:
        if event["type"] == "session_start":
            starts[event["session_id"]] = parse_iso(event["timestamp"])
        elif event["type"] == "session_end" and event.get("session_id") in starts:
            _paint_interval(session_row, starts[event["session_id"]], parse_iso(event["timestamp"]), start, end, "━")
        elif event["type"] == "exit_checkpoint":
            session_row[_time_to_column(parse_iso(event["timestamp"]), start, end, columns)] = "◆"
    lines = [f"{game.name} — save/session timeline", _axis(start, end, columns), f"session  |{''.join(session_row)}|"]
    for index in sorted(rows):
        lines.append(f"state {index:<2} |{''.join(rows[index])}|")
    lines.append("          • in-session save  ● scheduled/manual save  ◆ exit checkpoint  ━ gameplay")
    return "\n".join(lines)


def render_overall_timeline(service: GameService, *, width: int | None = None, selectors: Iterable[str] | None = None) -> str:
    games = list(service.games.values())
    if selectors:
        wanted = {service.get_game(item).id for item in selectors}
        games = [game for game in games if game.id in wanted]
    sessions = list(service.store.iter_events(types={"session_start", "session_end"}))
    relevant = [event for event in sessions if event.get("game_id") in {game.id for game in games}]
    if not relevant:
        return "No gameplay sessions have been recorded yet."
    timestamps = [parse_iso(event["timestamp"]) for event in relevant]
    start, end = min(timestamps), max(timestamps)
    columns = _timeline_columns(width)
    rows = {game.id: [" "] * columns for game in games}
    starts: dict[tuple[str, str], datetime] = {}
    for event in relevant:
        key = (event["game_id"], event["session_id"])
        if event["type"] == "session_start":
            starts[key] = parse_iso(event["timestamp"])
        elif event["type"] == "session_end" and key in starts:
            _paint_interval(rows[event["game_id"]], starts[key], parse_iso(event["timestamp"]), start, end, "█")
    lines = ["All-games gameplay timeline", _axis(start, end, columns)]
    for index, game in enumerate(sorted(games, key=lambda item: item.name.casefold())):
        glyph = GAME_GLYPHS[index % len(GAME_GLYPHS)]
        rendered = "".join(glyph if cell == "█" else " " for cell in rows[game.id])
        lines.append(f"{game.name:<22.22} |{rendered}|")
    return "\n".join(lines)


def render_playtime_bars(service: GameService, *, width: int | None = None) -> str:
    games = sorted(service.games.values(), key=lambda item: item.effective_playtime_seconds, reverse=True)
    max_seconds = max((game.effective_playtime_seconds for game in games), default=0.0)
    terminal_width = width or shutil.get_terminal_size((110, 24)).columns
    bar_width = max(10, min(36, terminal_width - 70))
    daily = _daily_playtime_by_game(service)
    all_days = sorted({day for values in daily.values() for day in values})
    spark_width = max(8, min(24, terminal_width - 82))
    lines = ["Playtime by game — total and recorded daily activity"]
    for game in games:
        ratio = game.effective_playtime_seconds / max_seconds if max_seconds else 0
        filled = int(round(ratio * bar_width))
        spark = _daily_sparkline(daily.get(game.id, {}), all_days, spark_width)
        lines.append(
            f"{game.name:<26.26} {'█' * filled:<{bar_width}} {format_playtime(game.effective_playtime_seconds)}  {spark}"
        )
    if all_days:
        lines.append(f"Daily activity span: {all_days[0]} -> {all_days[-1]} (sparkline is recorded session time, not imported pre-SGA history)")
    return "\n".join(lines)


def render_hourly_histogram(service: GameService, *, selectors: Iterable[str] | None = None) -> str:
    selected_ids = None
    if selectors:
        selected_ids = {service.get_game(item).id for item in selectors}
    events = list(service.store.iter_events(types={"session_start", "session_end"}))
    starts: dict[tuple[str, str], datetime] = {}
    bins = [0.0] * 24
    per_game: dict[str, list[float]] = defaultdict(lambda: [0.0] * 24)
    for event in events:
        game_id = event.get("game_id")
        if selected_ids is not None and game_id not in selected_ids:
            continue
        key = (game_id, event.get("session_id"))
        if event["type"] == "session_start":
            starts[key] = parse_iso(event["timestamp"]).astimezone()
        elif event["type"] == "session_end" and key in starts:
            end = parse_iso(event["timestamp"]).astimezone()
            _allocate_hours(starts[key], end, bins)
            _allocate_hours(starts[key], end, per_game[game_id])
    max_bin = max(bins, default=0.0)
    spark = "".join(_block(value, max_bin) for value in bins)
    lines = ["Gaming by hour of day", "hours  00 03 06 09 12 15 18 21", f"all    {spark}"]
    for game in sorted(service.games.values(), key=lambda item: item.name.casefold()):
        if game.id not in per_game:
            continue
        local_max = max(per_game[game.id], default=0.0)
        row = "".join(_block(value, local_max) for value in per_game[game.id])
        lines.append(f"{game.name:<6.6} {row}")
    lines.append("Each character represents one local-clock hour; height indicates relative playtime.")
    return "\n".join(lines)


def doctor(service: GameService) -> tuple[int, str]:
    problems: list[str] = []
    warnings: list[str] = []
    for root in service.config.get("game_roots", []):
        if not Path(root).expanduser().is_dir():
            problems.append(f"configured game root missing: {root}")
    for game in service.games.values():
        if not game.executables:
            warnings.append(f"{game.name}: no executable candidate")
        if not game.save_sources:
            warnings.append(f"{game.name}: no save source yet (first launch may be required)")
        if game.active_session_id:
            warnings.append(f"{game.name}: catalog contains an active session; watcher should verify it")
        inverse: dict[int, list[str]] = defaultdict(list)
        for key, index in game.save_states.items():
            inverse[int(index)].append(key)
        for index, keys in inverse.items():
            if len(keys) > 1:
                problems.append(f"{game.name}: save-state index {index} is assigned to multiple keys: {', '.join(keys)}")
        if game.last_snapshot_id:
            try:
                manifest = service.archive.load_manifest(game.id, game.last_snapshot_id)
                for entry in manifest.entries:
                    blob = service.archive.blobs_root / entry.blob_sha256[:2] / entry.blob_sha256
                    if not blob.is_file():
                        problems.append(f"{game.name}: snapshot {manifest.snapshot_id} references missing blob {entry.blob_sha256}")
            except (OSError, ValueError):
                problems.append(f"{game.name}: latest snapshot manifest cannot be read")
    code = 2 if problems else (1 if warnings else 0)
    lines = ["Saved Game Archiver doctor"]
    lines.extend(f"ERROR  {item}" for item in problems)
    lines.extend(f"WARN   {item}" for item in warnings)
    if not problems and not warnings:
        lines.append("OK     catalog, configured roots, and referenced archive blobs are aligned")
    return code, "\n".join(lines)


def _timeline_columns(width: int | None) -> int:
    terminal = width or shutil.get_terminal_size((100, 24)).columns
    return max(24, min(120, terminal - 14))


def _time_to_column(moment: datetime, start: datetime, end: datetime, columns: int) -> int:
    span = max(1.0, (end - start).total_seconds())
    offset = max(0.0, min(span, (moment - start).total_seconds()))
    return min(columns - 1, int(round(offset / span * (columns - 1))))


def _paint_interval(row: list[str], left: datetime, right: datetime, start: datetime, end: datetime, glyph: str) -> None:
    first = _time_to_column(left, start, end, len(row))
    last = _time_to_column(right, start, end, len(row))
    for index in range(first, max(first, last) + 1):
        row[index] = glyph


def _axis(start: datetime, end: datetime, columns: int) -> str:
    left = start.astimezone().strftime("%Y-%m-%d %H:%M")
    right = end.astimezone().strftime("%Y-%m-%d %H:%M")
    gap = max(1, columns - len(left) - len(right))
    return f"          {left}{'─' * gap}{right}"


def _allocate_hours(start: datetime, end: datetime, bins: list[float]) -> None:
    cursor = start
    while cursor < end:
        next_hour = cursor.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        stop = min(end, next_hour)
        bins[cursor.hour] += max(0.0, (stop - cursor).total_seconds())
        cursor = stop


def _block(value: float, maximum: float) -> str:
    if maximum <= 0 or value <= 0:
        return BLOCKS[0]
    index = min(len(BLOCKS) - 1, max(1, int(math.ceil(value / maximum * (len(BLOCKS) - 1)))))
    return BLOCKS[index]


def _daily_playtime_by_game(service: GameService) -> dict[str, dict[str, float]]:
    events = list(service.store.iter_events(types={"session_start", "session_end"}))
    starts: dict[tuple[str, str], datetime] = {}
    result: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for event in events:
        key = (event.get("game_id"), event.get("session_id"))
        if event["type"] == "session_start":
            starts[key] = parse_iso(event["timestamp"]).astimezone()
            continue
        if event["type"] != "session_end" or key not in starts:
            continue
        cursor = starts[key]
        end = parse_iso(event["timestamp"]).astimezone()
        while cursor < end:
            next_day = cursor.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            stop = min(end, next_day)
            result[key[0]][cursor.date().isoformat()] += max(0.0, (stop - cursor).total_seconds())
            cursor = stop
    return {game_id: dict(values) for game_id, values in result.items()}


def _daily_sparkline(values: dict[str, float], all_days: list[str], width: int) -> str:
    if not all_days or not values:
        return " " * width
    if len(all_days) <= width:
        points = [values.get(day, 0.0) for day in all_days]
    else:
        points = []
        for index in range(width):
            left = int(index * len(all_days) / width)
            right = max(left + 1, int((index + 1) * len(all_days) / width))
            points.append(sum(values.get(day, 0.0) for day in all_days[left:right]))
    maximum = max(points, default=0.0)
    rendered = "".join(_block(point, maximum) for point in points)
    return rendered.ljust(width)
