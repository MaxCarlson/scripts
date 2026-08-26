from __future__ import annotations

import fnmatch
import glob
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

from .models import ExecutableCandidate, GameRecord, SaveSource
from .utils import iso_now, slugify, stable_game_id


_VDF_TOKEN = re.compile(r'"((?:\\.|[^"\\])*)"|([{}])')
_EXECUTABLE_EXCLUDES = (
    "unins", "uninstall", "setup", "install", "redist", "vc_redist", "dxsetup",
    "crashhandler", "unitycrashhandler", "reportcrash", "easyanticheat", "eac",
    "battleye", "benchmark", "config", "settings", "server", "dedicated",
)
_EXECUTABLE_LAUNCHER_HINTS = ("launcher", "start", "bootstrap")
_COMMON_SAVE_PARENT_NAMES = {"saves", "save", "savegames", "savegame", "profiles", "characters", "players"}


def parse_vdf(text: str) -> dict[str, Any]:
    tokens: list[str] = []
    for match in _VDF_TOKEN.finditer(text):
        if match.group(2):
            tokens.append(match.group(2))
        else:
            tokens.append(bytes(match.group(1), "utf-8").decode("unicode_escape"))
    index = 0

    def parse_object(stop_on_brace: bool = False) -> dict[str, Any]:
        nonlocal index
        result: dict[str, Any] = {}
        while index < len(tokens):
            token = tokens[index]
            if token == "}":
                if not stop_on_brace:
                    raise ValueError("Unexpected VDF closing brace")
                index += 1
                return result
            if token == "{":
                raise ValueError("Unexpected VDF opening brace")
            key = token
            index += 1
            if index >= len(tokens):
                result[key] = ""
                break
            if tokens[index] == "{":
                index += 1
                result[key] = parse_object(stop_on_brace=True)
            else:
                result[key] = tokens[index]
                index += 1
        if stop_on_brace:
            raise ValueError("Unclosed VDF object")
        return result

    return parse_object()


def read_vdf(path: Path) -> dict[str, Any]:
    return parse_vdf(path.read_text(encoding="utf-8", errors="replace"))


def configured_and_default_steam_roots(config: dict[str, Any]) -> list[Path]:
    roots = [Path(item).expanduser() for item in config.get("steam_roots", [])]
    if os.name == "nt":
        for env_name in ("PROGRAMFILES(X86)", "PROGRAMFILES"):
            base = os.environ.get(env_name)
            if base:
                roots.append(Path(base) / "Steam")
    else:
        roots.extend([Path.home() / ".steam" / "steam", Path.home() / ".local" / "share" / "Steam"])
    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root).casefold()
        if key not in seen:
            seen.add(key)
            unique.append(root)
    return unique


def discover_steam_library_roots(steam_root: Path) -> list[Path]:
    roots = [steam_root]
    library_file = steam_root / "steamapps" / "libraryfolders.vdf"
    if not library_file.exists():
        return roots
    try:
        raw = read_vdf(library_file)
    except (OSError, ValueError):
        return roots
    node = raw.get("libraryfolders", raw)
    if isinstance(node, dict):
        for value in node.values():
            if isinstance(value, dict) and value.get("path"):
                roots.append(Path(str(value["path"])))
    dedup: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root).casefold()
        if key not in seen:
            seen.add(key)
            dedup.append(root)
    return dedup


def discover_steam_games(config: dict[str, Any]) -> list[GameRecord]:
    games: list[GameRecord] = []
    for steam_root in configured_and_default_steam_roots(config):
        for library in discover_steam_library_roots(steam_root):
            steamapps = library / "steamapps"
            if not steamapps.exists():
                continue
            for manifest in steamapps.glob("appmanifest_*.acf"):
                try:
                    raw = read_vdf(manifest)
                    app = raw.get("AppState", raw)
                    appid = int(app.get("appid", manifest.stem.split("_")[-1]))
                    name = str(app.get("name") or f"Steam {appid}")
                    install_dir_name = str(app.get("installdir") or "")
                except (OSError, ValueError, TypeError):
                    continue
                install_dir = steamapps / "common" / install_dir_name
                record = GameRecord(
                    id=stable_game_id(name, appid, str(install_dir)),
                    name=name,
                    install_dirs=[str(install_dir)],
                    steam_app_id=appid,
                    discovery_origins=["steam"],
                    first_seen_at=iso_now(),
                )
                record.executables = discover_executables(record)
                games.append(record)
    return games


def discover_root_games(config: dict[str, Any]) -> list[GameRecord]:
    games: list[GameRecord] = []
    for root_text in config.get("game_roots", []):
        root = Path(root_text).expanduser()
        if not root.is_dir():
            continue
        for child in root.iterdir():
            if not child.is_dir() or child.name.startswith("."):
                continue
            record = GameRecord(
                id=stable_game_id(child.name, install_dir=str(child)),
                name=child.name,
                install_dirs=[str(child)],
                discovery_origins=[f"game_root:{root}"],
                first_seen_at=iso_now(),
            )
            record.executables = discover_executables(record)
            games.append(record)
    return games


def merge_discovered(existing: dict[str, GameRecord], discovered: Iterable[GameRecord]) -> tuple[dict[str, GameRecord], list[str]]:
    games = dict(existing)
    new_ids: list[str] = []
    by_install: dict[str, str] = {}
    for game_id, game in games.items():
        for path in game.install_dirs:
            by_install[str(Path(path)).casefold()] = game_id
    for incoming in discovered:
        matching_id = None
        if incoming.steam_app_id is not None:
            for game_id, game in games.items():
                if game.steam_app_id == incoming.steam_app_id:
                    matching_id = game_id
                    break
        if matching_id is None:
            for path in incoming.install_dirs:
                if str(Path(path)).casefold() in by_install:
                    matching_id = by_install[str(Path(path)).casefold()]
                    break
        if matching_id is None:
            games[incoming.id] = incoming
            new_ids.append(incoming.id)
            matching_id = incoming.id
        else:
            current = games[matching_id]
            current.name = incoming.name if current.name.startswith("Steam ") else current.name
            current.steam_app_id = current.steam_app_id or incoming.steam_app_id
            current.install_dirs = _unique(current.install_dirs + incoming.install_dirs)
            current.discovery_origins = _unique(current.discovery_origins + incoming.discovery_origins)
            _merge_executables(current, incoming.executables)
        for path in games[matching_id].install_dirs:
            by_install[str(Path(path)).casefold()] = matching_id
    return games, new_ids


def _unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = value.casefold()
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


def _merge_executables(game: GameRecord, candidates: Iterable[ExecutableCandidate]) -> None:
    by_path = {str(Path(item.path)).casefold(): item for item in game.executables}
    for candidate in candidates:
        key = str(Path(candidate.path)).casefold()
        if key not in by_path:
            game.executables.append(candidate)
        else:
            existing = by_path[key]
            existing.score = max(existing.score, candidate.score)


def executable_score(path: Path, game_name: str, install_dir: Path) -> float:
    stem = path.stem.casefold()
    relative_depth = max(0, len(path.relative_to(install_dir).parts) - 1) if path.is_relative_to(install_dir) else 10
    if any(token in stem for token in _EXECUTABLE_EXCLUDES):
        return 0.05
    score = 0.25
    game_slug = slugify(game_name).replace("-", "")
    stem_slug = slugify(stem).replace("-", "")
    folder_slug = slugify(install_dir.name).replace("-", "")
    if game_slug and (game_slug in stem_slug or stem_slug in game_slug):
        score += 0.45
    if folder_slug and (folder_slug in stem_slug or stem_slug in folder_slug):
        score += 0.25
    if any(token in stem for token in _EXECUTABLE_LAUNCHER_HINTS):
        score += 0.05
    try:
        size = path.stat().st_size
        if size >= 5 * 1024 * 1024:
            score += 0.12
        elif size < 256 * 1024:
            score -= 0.10
    except OSError:
        pass
    score -= min(0.25, relative_depth * 0.04)
    return max(0.0, min(1.0, score))


def discover_executables(game: GameRecord) -> list[ExecutableCandidate]:
    candidates: list[ExecutableCandidate] = []
    for install_text in game.install_dirs:
        install = Path(install_text)
        if not install.is_dir():
            continue
        patterns = ["*.exe"] if os.name == "nt" else ["*"]
        for pattern in patterns:
            for path in install.rglob(pattern):
                if not path.is_file():
                    continue
                if os.name != "nt" and not os.access(path, os.X_OK):
                    continue
                score = executable_score(path, game.name, install)
                if score >= 0.20:
                    candidates.append(ExecutableCandidate(str(path), score, "scan"))
    candidates.sort(key=lambda item: (-item.score, len(item.path), item.path.casefold()))
    return candidates[:32]


def steam_playtime_minutes(steam_roots: Iterable[Path]) -> dict[int, int]:
    totals: dict[int, int] = {}
    for root in steam_roots:
        userdata = root / "userdata"
        if not userdata.is_dir():
            continue
        for localconfig in userdata.glob("*/config/localconfig.vdf"):
            try:
                raw = read_vdf(localconfig)
            except (OSError, ValueError):
                continue
            apps = _find_apps_mapping(raw)
            if not apps:
                continue
            for appid_text, values in apps.items():
                if not str(appid_text).isdigit() or not isinstance(values, dict):
                    continue
                value = values.get("Playtime") or values.get("playtime") or values.get("Playtime2")
                try:
                    minutes = int(value)
                except (TypeError, ValueError):
                    continue
                appid = int(appid_text)
                totals[appid] = max(totals.get(appid, 0), minutes)
    return totals


def _find_apps_mapping(raw: dict[str, Any]) -> dict[str, Any] | None:
    stack: list[Any] = [raw]
    while stack:
        node = stack.pop()
        if not isinstance(node, dict):
            continue
        for key, value in node.items():
            if key.casefold() == "apps" and isinstance(value, dict):
                numeric = sum(1 for item in value if str(item).isdigit())
                if numeric:
                    return value
            if isinstance(value, dict):
                stack.append(value)
    return None


@dataclass
class LudusaviManifest:
    data: dict[str, Any]

    @classmethod
    def load(cls, path: Path) -> "LudusaviManifest":
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError("Ludusavi manifest root must be a mapping")
        return cls(raw)

    def find_game(self, game: GameRecord) -> tuple[str, dict[str, Any]] | None:
        if game.steam_app_id is not None:
            for name, entry in self.data.items():
                if isinstance(entry, dict) and _steam_id(entry) == game.steam_app_id:
                    return str(name), entry
        wanted = slugify(game.name)
        for name, entry in self.data.items():
            if slugify(str(name)) == wanted and isinstance(entry, dict):
                return str(name), entry
        return None


def _steam_id(entry: dict[str, Any]) -> int | None:
    steam = entry.get("steam")
    if not isinstance(steam, dict):
        return None
    try:
        return int(steam.get("id"))
    except (TypeError, ValueError):
        return None


def refresh_manifest(config: dict[str, Any], *, timeout: float = 20.0) -> tuple[Path, bool]:
    manifest_cfg = config["manifest"]
    target = Path(manifest_cfg["cache_path"]).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(manifest_cfg["url"], headers={"User-Agent": "saved-game-archiver/1.0"})
    if manifest_cfg.get("etag"):
        request.add_header("If-None-Match", manifest_cfg["etag"])
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read()
            target.write_bytes(data)
            manifest_cfg["etag"] = response.headers.get("ETag")
            return target, True
    except urllib.error.HTTPError as exc:
        if exc.code == 304 and target.exists():
            return target, False
        raise


def resolve_ludusavi_sources(game: GameRecord, config: dict[str, Any], manifest: LudusaviManifest) -> list[SaveSource]:
    found = manifest.find_game(game)
    if found is None:
        return []
    canonical_name, entry = found
    sources: list[SaveSource] = []
    install_dirs = [Path(item) for item in game.install_dirs] or [Path.cwd()]
    roots = _manifest_roots(config, install_dirs)
    files = entry.get("files", {})
    if isinstance(files, dict):
        for template, attributes in files.items():
            if not _when_applies(attributes, game):
                continue
            for expanded in _expand_manifest_template(str(template), game, canonical_name, entry, roots, install_dirs):
                matches = [Path(item) for item in glob.glob(expanded, recursive=True)]
                candidates = matches or [Path(expanded)]
                for candidate in candidates:
                    source_id = f"ludusavi-file-{len(sources):03d}"
                    sources.append(SaveSource(source_id, "files", str(candidate), "ludusavi", 0.98))
    registry = entry.get("registry", {})
    if os.name == "nt" and isinstance(registry, dict):
        for key, attributes in registry.items():
            if not _when_applies(attributes, game):
                continue
            source_id = f"ludusavi-reg-{len(sources):03d}"
            sources.append(SaveSource(source_id, "registry", str(key), "ludusavi", 0.98))
    return _dedup_sources(sources)


def _manifest_roots(config: dict[str, Any], install_dirs: list[Path]) -> list[Path]:
    roots = [Path(item).expanduser() for item in config.get("game_roots", [])]
    roots.extend(Path(item).expanduser() for item in config.get("steam_roots", []))
    roots.extend(path.parent for path in install_dirs)
    return list(dict.fromkeys(roots))


def _when_applies(attributes: Any, game: GameRecord) -> bool:
    if not isinstance(attributes, dict):
        return True
    clauses = attributes.get("when")
    if not isinstance(clauses, list) or not clauses:
        return True
    current_os = "windows" if os.name == "nt" else ("mac" if os.uname().sysname == "Darwin" else "linux")
    for clause in clauses:
        if not isinstance(clause, dict):
            continue
        os_value = clause.get("os")
        store = clause.get("store")
        os_ok = os_value is None or str(os_value).casefold() == current_os
        store_ok = store is None or (str(store).casefold() == "steam" and game.steam_app_id is not None)
        if os_ok and store_ok:
            return True
    return False


def _expand_manifest_template(
    template: str,
    game: GameRecord,
    canonical_name: str,
    entry: dict[str, Any],
    roots: list[Path],
    install_dirs: list[Path],
) -> list[str]:
    home = Path.home()
    env = os.environ
    placeholders = {
        "<home>": str(home),
        "<osUserName>": home.name,
        "<winAppData>": env.get("APPDATA", str(home / "AppData" / "Roaming")),
        "<winLocalAppData>": env.get("LOCALAPPDATA", str(home / "AppData" / "Local")),
        "<winLocalAppDataLow>": str(home / "AppData" / "LocalLow"),
        "<winDocuments>": str(home / "Documents"),
        "<winPublic>": env.get("PUBLIC", str(home.parent / "Public")),
        "<winProgramData>": env.get("PROGRAMDATA", "C:/ProgramData"),
        "<winDir>": env.get("WINDIR", "C:/Windows"),
        "<xdgData>": env.get("XDG_DATA_HOME", str(home / ".local" / "share")),
        "<xdgConfig>": env.get("XDG_CONFIG_HOME", str(home / ".config")),
        "<storeGameId>": str(game.steam_app_id or ""),
    }
    install_names = list((entry.get("installDir") or {}).keys()) if isinstance(entry.get("installDir"), dict) else []
    game_names = install_names or [canonical_name]
    variants: list[str] = []
    if "<base>" in template or "<root>" in template or "<game>" in template:
        bases = install_dirs or [root / game_name for root in roots for game_name in game_names]
        for base in bases:
            text = template.replace("<base>", str(base)).replace("<game>", base.name).replace("<root>", str(base.parent))
            variants.append(text)
    else:
        variants.append(template)
    expanded: list[str] = []
    for text in variants:
        for key, value in placeholders.items():
            text = text.replace(key, value)
        expanded.append(os.path.expandvars(os.path.expanduser(text)))
    return expanded


def _dedup_sources(sources: list[SaveSource]) -> list[SaveSource]:
    result: list[SaveSource] = []
    seen: set[tuple[str, str]] = set()
    for source in sources:
        key = (source.kind, source.path.casefold())
        if key not in seen:
            seen.add(key)
            source.id = f"{source.origin}-{source.kind}-{len(result):03d}"
            result.append(source)
    return result


def merge_save_sources(game: GameRecord, incoming: Iterable[SaveSource]) -> None:
    existing = {(item.kind, item.path.casefold()): item for item in game.save_sources}
    for source in incoming:
        key = (source.kind, source.path.casefold())
        if key in existing:
            item = existing[key]
            item.confidence = max(item.confidence, source.confidence)
        else:
            used_ids = {item.id for item in game.save_sources}
            candidate = source.id
            suffix = 1
            while candidate in used_ids:
                candidate = f"{source.id}-{suffix}"
                suffix += 1
            source.id = candidate
            game.save_sources.append(source)


def likely_common_save_paths(game: GameRecord) -> list[Path]:
    home = Path.home()
    candidates = [
        home / "Documents" / "My Games" / game.name,
        home / "Saved Games" / game.name,
    ]
    if os.name == "nt":
        local = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
        roaming = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
        low = home / "AppData" / "LocalLow"
        for base in (local, roaming, low):
            candidates.extend([base / game.name, base / slugify(game.name), base / game.name.replace(" ", "")])
    return list(dict.fromkeys(candidates))


def save_state_key(source_id: str, relative_path: str) -> str:
    path = Path(relative_path)
    parts = [part for part in path.parts if part not in (".", "")]
    if len(parts) >= 2:
        first = parts[0].casefold()
        if first in _COMMON_SAVE_PARENT_NAMES and len(parts) >= 3:
            return f"{source_id}:{parts[1].casefold()}"
        return f"{source_id}:{first}"
    return f"{source_id}:{path.stem.casefold()}"


def matches_any_pattern(value: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatch(value.casefold(), pattern.casefold()) for pattern in patterns)


def steam_userdata_sources(game: GameRecord, config: dict[str, Any]) -> list[SaveSource]:
    if game.steam_app_id is None:
        return []
    sources: list[SaveSource] = []
    for steam_root in configured_and_default_steam_roots(config):
        userdata = steam_root / "userdata"
        if not userdata.is_dir():
            continue
        for user in userdata.iterdir():
            if not user.is_dir():
                continue
            app_root = user / str(game.steam_app_id)
            remote = app_root / "remote"
            if remote.exists():
                sources.append(
                    SaveSource(
                        f"steam-userdata-{user.name}",
                        "files",
                        str(remote),
                        "steam-userdata",
                        0.95,
                    )
                )
    return _dedup_sources(sources)


def common_save_search_roots() -> list[Path]:
    home = Path.home()
    roots = [home / "Documents" / "My Games", home / "Saved Games"]
    if os.name == "nt":
        roots.extend(
            [
                Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local")),
                Path(os.environ.get("APPDATA", home / "AppData" / "Roaming")),
                home / "AppData" / "LocalLow",
            ]
        )
    return [root for root in roots if root.is_dir()]


def correlated_save_sources(game: GameRecord, *, since_epoch: float) -> list[SaveSource]:
    wanted = set(_name_tokens(game.name))
    for install in game.install_dirs:
        wanted.update(_name_tokens(Path(install).name))
    found: list[SaveSource] = []
    for base in common_save_search_roots():
        for candidate in _walk_dirs_limited(base, depth=2):
            tokens = set(_name_tokens(candidate.name))
            overlap = len(wanted & tokens) / max(1, len(wanted))
            exact = slugify(candidate.name) == slugify(game.name)
            changed = _directory_changed_since(candidate, since_epoch, max_files=300)
            score = 0.0
            if exact:
                score = 0.92
            elif overlap >= 0.75:
                score = 0.78
            elif overlap >= 0.40:
                score = 0.60
            if changed:
                score += 0.18
            if score >= 0.78:
                found.append(
                    SaveSource(
                        f"session-correlated-{len(found):03d}",
                        "files",
                        str(candidate),
                        "session-correlation",
                        min(0.99, score),
                    )
                )
    return _dedup_sources(found)


def _name_tokens(value: str) -> list[str]:
    stop = {"the", "a", "an", "and", "of", "edition", "game", "remastered", "definitive"}
    return [token for token in re.findall(r"[a-z0-9]+", value.casefold()) if len(token) >= 2 and token not in stop]


def _walk_dirs_limited(root: Path, *, depth: int) -> Iterable[Path]:
    frontier = [(root, 0)]
    visited = 0
    while frontier and visited < 5000:
        current, level = frontier.pop(0)
        if level >= depth:
            continue
        try:
            children = list(current.iterdir())
        except (OSError, PermissionError):
            continue
        for child in children:
            if not child.is_dir() or child.name.startswith("."):
                continue
            visited += 1
            yield child
            frontier.append((child, level + 1))


def _directory_changed_since(path: Path, since_epoch: float, *, max_files: int) -> bool:
    checked = 0
    frontier = [(path, 0)]
    while frontier and checked < max_files:
        current, depth = frontier.pop()
        try:
            children = list(current.iterdir())
        except (OSError, PermissionError):
            continue
        for child in children:
            if child.is_file():
                checked += 1
                try:
                    if child.stat().st_mtime >= since_epoch:
                        return True
                except OSError:
                    pass
            elif child.is_dir() and depth < 1:
                frontier.append((child, depth + 1))
            if checked >= max_files:
                break
    return False
