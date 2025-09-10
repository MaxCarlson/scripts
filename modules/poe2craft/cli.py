#!/usr/bin/env python3
import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, List, Optional
import dataclasses
import enum

# Support running as a package OR directly from the folder.
try:
    from poe2craft.datasources.poe2db_client import Poe2DBClient, DEFAULT_BASE_SLUGS
    from poe2craft.datasources.poeninja_prices import PoENinjaPriceProvider, detect_active_league
    from poe2craft.progress import progress
except Exception:  # pragma: no cover
    # fall back to relative when executed as a script in the package dir
    from datasources.poe2db_client import Poe2DBClient, DEFAULT_BASE_SLUGS
    from datasources.poeninja_prices import PoENinjaPriceProvider, detect_active_league
    from progress import progress

APP_LOGGER = logging.getLogger("poe2craft")


# ---------------- persistence (timestamps, user prefs) ----------------

def _state_dir() -> Path:
    env = os.environ.get("POE2CRAFT_STATE_DIR")
    if env:
        p = Path(env).expanduser()
    else:
        p = Path.home() / ".local" / "share" / "poe2craft"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _state_path() -> Path:
    return _state_dir() / "state.json"


def _load_state() -> dict:
    sp = _state_path()
    if sp.exists():
        try:
            return json.loads(sp.read_text("utf-8"))
        except Exception:
            return {}
    return {}


def _save_state(d: dict) -> None:
    sp = _state_path()
    tmp = sp.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(sp)


def _state_set(k: str, v: Any) -> None:
    st = _load_state()
    st[k] = v
    _save_state(st)


def _state_get(k: str, default: Any = None) -> Any:
    return _load_state().get(k, default)


# ---------------- JSON helpers (handle Enums, dataclasses) ----------------

def _json_default(o: Any):
    if dataclasses.is_dataclass(o):
        return dataclasses.asdict(o)
    if isinstance(o, enum.Enum):
        # stringify enums so json.dumps never crashes in tests
        return getattr(o, "value", o.name)
    if hasattr(o, "__dict__"):
        # fallback: best-effort
        return {k: _json_default(v) for k, v in o.__dict__.items()}
    return str(o)


def _stdout_json(obj: Any) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=_json_default))


def _dump_json_to(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")


# ---------------- league helper ----------------

def _resolve_league(flag: Optional[str], provider: Optional[PoENinjaPriceProvider] = None) -> str:
    """
    None or 'C' -> detect active league (fallback Standard).
    'S'         -> Standard
    otherwise   -> literal value
    """
    if not flag or flag.upper() == "C":
        display = detect_active_league(session=(provider.session if provider else None)) or "Standard"
        return display
    if flag.upper() == "S":
        return "Standard"
    return flag


# ---------------- commands ----------------

def cmd_currencies(args: argparse.Namespace) -> None:
    client = Poe2DBClient()
    with progress("Currencies", total=1, quiet=(args.format == "json")) as bar:
        data = [c for c in client.fetch_stackable_currency()]
        bar.update(1, info=f"parsed {len(data)}")

    if args.save:
        _dump_json_to(Path(args.save).expanduser(), data)

    if args.format == "json":
        if args.output:
            _dump_json_to(Path(args.output).expanduser(), data)
        else:
            _stdout_json(data)
    else:
        _stdout_json(data)


def cmd_omens(args: argparse.Namespace) -> None:
    client = Poe2DBClient()
    with progress("Omens", total=1, quiet=(args.format == "json")) as bar:
        data = [o for o in client.fetch_omens()]
        bar.update(1, info=f"parsed {len(data)}")

    if args.save:
        _dump_json_to(Path(args.save).expanduser(), data)

    if args.format == "json":
        if args.output:
            _dump_json_to(Path(args.output).expanduser(), data)
        else:
            _stdout_json(data)
    else:
        _stdout_json(data)


def cmd_essences(args: argparse.Namespace) -> None:
    client = Poe2DBClient()
    with progress("Essences", total=1, quiet=(args.format == "json")) as bar:
        data = [e for e in client.fetch_essences()]
        bar.update(1, info=f"parsed {len(data)}")

    if args.save:
        _dump_json_to(Path(args.save).expanduser(), data)

    if args.format == "json":
        if args.output:
            _dump_json_to(Path(args.output).expanduser(), data)
        else:
            _stdout_json(data)
    else:
        _stdout_json(data)


def cmd_base_items(args: argparse.Namespace) -> None:
    client = Poe2DBClient()
    slugs: List[str] = args.slug or []
    if not slugs:
        slugs = list(DEFAULT_BASE_SLUGS)

    all_items = []
    with progress("Base Items (slugs)", total=len(slugs), quiet=(args.format == "json")) as bar:
        for idx, slug in enumerate(slugs, 1):
            items = [i for i in client.fetch_base_items(slug)]
            all_items.extend(items)
            bar.update(idx, info=f"{slug} -> {len(items)} items")

    if args.save:
        _dump_json_to(Path(args.save).expanduser(), all_items)

    if args.format == "json":
        if args.output:
            _dump_json_to(Path(args.output).expanduser(), all_items)
        else:
            _stdout_json(all_items)
    else:
        _stdout_json(all_items)


def cmd_prices(args: argparse.Namespace) -> None:
    provider = PoENinjaPriceProvider()
    league = _resolve_league(args.league, provider)

    if args.if_stale:
        last = _state_get("last_prices_ts")
        stale = last is None or (time.time() - last) > float(args.if_stale) * 3600.0
        if stale:
            APP_LOGGER.info("Prices are stale/missing; refreshing for league: %s", league)

    with progress(f"Prices [{league}]", total=1, quiet=(args.format == "json")) as bar:
        prices = provider.get_currency_prices(league=league)
        bar.update(1, info=f"{len(prices)} entries")

    if prices:
        _state_set("last_prices_ts", time.time())
        _state_set("last_prices_league", league)

    if args.format == "json":
        if args.output:
            _dump_json_to(Path(args.output).expanduser(), prices)
        else:
            _stdout_json(prices)
    else:
        _stdout_json(prices)


def cmd_consumables(args: argparse.Namespace) -> None:
    out_dir = Path(args.output_dir).expanduser() if args.output_dir else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)

    client = Poe2DBClient()

    with progress("Consumables", total=3, quiet=False) as bar:
        cur = [c for c in client.fetch_stackable_currency()]
        bar.update(1, info=f"currencies: {len(cur)}")
        om = [o for o in client.fetch_omens()]
        bar.update(2, info=f"omens: {len(om)}")
        es = [e for e in client.fetch_essences()]
        bar.update(3, info=f"essences: {len(es)}")

    bundle = {"currencies": cur, "omens": om, "essences": es}

    if out_dir:
        _dump_json_to(out_dir / "currencies.json", cur)
        _dump_json_to(out_dir / "omens.json", om)
        _dump_json_to(out_dir / "essences.json", es)

    if args.format == "json":
        if args.output:
            _dump_json_to(Path(args.output).expanduser(), bundle)
        else:
            _stdout_json(bundle)
    else:
        _stdout_json(bundle)


def cmd_all(args: argparse.Namespace) -> None:
    out_dir = Path(args.output_dir).expanduser() if args.output_dir else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)

    league = _resolve_league(args.league, None)
    client = Poe2DBClient()
    provider = PoENinjaPriceProvider()

    with progress("All: currencies", total=1, quiet=False) as bar:
        cur = [c for c in client.fetch_stackable_currency()]
        bar.update(1, info=f"{len(cur)}")

    with progress("All: omens", total=1, quiet=False) as bar:
        om = [o for o in client.fetch_omens()]
        bar.update(1, info=f"{len(om)}")

    with progress("All: essences", total=1, quiet=False) as bar:
        es = [e for e in client.fetch_essences()]
        bar.update(1, info=f"{len(es)}")

    base_agg = []
    with progress("All: base items", total=len(DEFAULT_BASE_SLUGS), quiet=False) as bar:
        for idx, slug in enumerate(DEFAULT_BASE_SLUGS, 1):
            items = [i for i in client.fetch_base_items(slug)]
            base_agg.extend(items)
            bar.update(idx, info=f"{slug}: {len(items)}")

    with progress(f"All: prices [{league}]", total=1, quiet=False) as bar:
        prices = provider.get_currency_prices(league=league)
        bar.update(1, info=f"{len(prices)}")

    if out_dir:
        _dump_json_to(out_dir / "currencies.json", cur)
        _dump_json_to(out_dir / "omens.json", om)
        _dump_json_to(out_dir / "essences.json", es)
        _dump_json_to(out_dir / "base-items.json", base_agg)
        _dump_json_to(out_dir / "prices.json", prices)

    summary = {
        "saved": bool(out_dir),
        "league": league,
        "counts": {
            "currencies": len(cur),
            "omens": len(om),
            "essences": len(es),
            "base_items": len(base_agg),
            "prices": len(prices),
        },
    }
    if args.format == "json":
        if args.output:
            _dump_json_to(Path(args.output).expanduser(), summary)
        else:
            _stdout_json(summary)
    else:
        _stdout_json(summary)


# ---------------- parser ----------------

def _add_common_io(p: argparse.ArgumentParser) -> None:
    p.add_argument("-f", "--format", choices=["json", "stdout"], default="json", help="Output format (default: json).")
    p.add_argument("-o", "--output", help="Output file (when --format json).")
    p.add_argument("-s", "--save", help="Also save JSON to this path.")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="poe2craft",
        description="PoE2 data & price utilities (definitions + economy).",
    )
    p.add_argument("-v", "--verbose", action="count", default=0, help="Increase verbosity (-v, -vv).")

    sub = p.add_subparsers(dest="cmd", required=True)

    # currencies
    sc = sub.add_parser("currencies", help="Fetch PoE2 stackable currencies from PoE2DB.")
    _add_common_io(sc)
    sc.set_defaults(func=cmd_currencies)

    # omens
    so = sub.add_parser("omens", help="Fetch PoE2 Omens from PoE2DB.")
    _add_common_io(so)
    so.set_defaults(func=cmd_omens)

    # essences
    se = sub.add_parser("essences", help="Fetch PoE2 Essences from PoE2DB.")
    _add_common_io(se)
    se.set_defaults(func=cmd_essences)

    # base-items
    sb = sub.add_parser(
        "base-items",
        help="Fetch base items. Default pulls curated slugs; pass one or more slugs to limit (e.g., 'Bows').",
    )
    _add_common_io(sb)
    sb.add_argument("slug", nargs="*", help="Optional PoE2DB page slugs (e.g., Bows, Boots, Helmets, Body_Armours).")
    sb.set_defaults(func=cmd_base_items)

    # prices
    sp = sub.add_parser("prices", help="Fetch PoE2 currency prices and print a plain mapping.")
    sp.add_argument("-l", "--league", help="League name or shorthand (S=Standard, C=Current).")
    sp.add_argument("-H", "--if-stale", type=float, help="Refresh if last update is older than N hours.")
    sp.add_argument("-f", "--format", choices=["json", "stdout"], default="json", help="Output format (default: json).")
    sp.add_argument("-o", "--output", help="Output file (when --format json).")
    sp.set_defaults(func=cmd_prices)

    # consumables
    sm = sub.add_parser("consumables", help="Download currencies, omens, and essences together.")
    sm.add_argument("-O", "--output-dir", help="Directory to save JSON files.")
    sm.add_argument("-f", "--format", choices=["json", "stdout"], default="json", help="Output format (default: json).")
    sm.add_argument("-o", "--output", help="Output file for the combined JSON (when --format json).")
    sm.set_defaults(func=cmd_consumables)

    # all
    sa = sub.add_parser("all", help="Download currencies, omens, essences, base items, and prices.")
    sa.add_argument("-O", "--output-dir", help="Directory to save JSON files (separate files).")
    sa.add_argument("-l", "--league", help="League name or shorthand (S=Standard, C=Current).")
    sa.add_argument("-f", "--format", choices=["json", "stdout"], default="json", help="Summary output format (default: json).")
    sa.add_argument("-o", "--output", help="Summary output file (when --format json).")
    sa.set_defaults(func=cmd_all)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(argv or sys.argv[1:])
    parser = build_parser()
    args = parser.parse_args(argv)

    level = logging.WARNING
    if args.verbose == 1:
        level = logging.INFO
    elif args.verbose >= 2:
        level = logging.DEBUG
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")

    try:
        args.func(args)
        return 0
    except SystemExit:
        raise
    except Exception as e:
        APP_LOGGER.error("Command failed: %s", e, exc_info=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
