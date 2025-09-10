#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .cache import SimpleCache
from .datasources.poe2db_client import Poe2DBClient
from .datasources.poeninja_prices import PoENinjaPriceProvider
from .progress import progress

APP = "poe2craft"
log = logging.getLogger(APP)

# ---------- persistence ----------


def _state_path() -> Path:
    base = os.environ.get("POE2CRAFT_STATE_DIR")
    if base:
        p = Path(base).expanduser()
    else:
        # ~/.local/share on Linux/Termux/WSL; fallback to ~/.poe2craft
        p = Path.home() / ".local" / "share" / "poe2craft"
    p.mkdir(parents=True, exist_ok=True)
    return p / "state.json"


def _load_state() -> Dict[str, Any]:
    sp = _state_path()
    if sp.exists():
        try:
            return json.loads(sp.read_text("utf-8"))
        except Exception:
            return {}
    return {}


def _save_state(d: Dict[str, Any]) -> None:
    sp = _state_path()
    tmp = sp.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(sp)


def _set_state(k: str, v: Any) -> None:
    st = _load_state()
    st[k] = v
    _save_state(st)


def _get_state(k: str, default: Any = None) -> Any:
    return _load_state().get(k, default)


# ---------- utils ----------


def _json_out(obj: Any, out_file: Optional[str]) -> None:
    txt = json.dumps(obj, ensure_ascii=False, indent=2)
    if out_file:
        Path(out_file).expanduser().write_text(txt, encoding="utf-8")
    else:
        print(txt)


def _league_from_flag(s: Optional[str], provider: PoENinjaPriceProvider) -> str:
    if not s or s.lower() == "c":
        cur = provider.detect_current_league()
        if cur:
            return cur
        # Fallback if detection fails
        return "Standard"
    if s.lower() == "s":
        return "Standard"
    return s


# ---------- command handlers ----------


def cmd_currencies(args: argparse.Namespace) -> None:
    client = Poe2DBClient(cache=SimpleCache())
    with progress("Currencies", 1) as bar:
        data = [c.__dict__ for c in client.fetch_currencies()]
        bar.update(1, info=f"parsed {len(data)}")
    if args.save:
        _set_state("last_currencies_ts", time.time())
    _json_out(data if args.format == "json" else data, args.output)


def cmd_omens(args: argparse.Namespace) -> None:
    client = Poe2DBClient(cache=SimpleCache())
    with progress("Omens", 1) as bar:
        data = [o.__dict__ for o in client.fetch_omens()]
        bar.update(1, info=f"parsed {len(data)}")
    if args.save:
        _set_state("last_omens_ts", time.time())
    _json_out(data if args.format == "json" else data, args.output)


def cmd_essences(args: argparse.Namespace) -> None:
    client = Poe2DBClient(cache=SimpleCache())
    with progress("Essences", 1) as bar:
        data = [e.__dict__ for e in client.fetch_essences()]
        bar.update(1, info=f"parsed {len(data)}")
    if args.save:
        _set_state("last_essences_ts", time.time())
    _json_out(data if args.format == "json" else data, args.output)


def _iter_base_slugs(custom: Optional[List[str]]) -> List[str]:
    if custom:
        return custom
    return Poe2DBClient.default_base_slugs()


def cmd_base_items(args: argparse.Namespace) -> None:
    client = Poe2DBClient(cache=SimpleCache())
    slugs = _iter_base_slugs([args.slug] if args.slug else None)
    all_items: List[Dict[str, Any]] = []
    with progress("Base Items (slugs)", len(slugs)) as bar:
        for idx, slug in enumerate(slugs, 1):
            items = client.fetch_base_items(slug)
            bar.update(idx, info=f"{slug} -> {len(items)} items")
            all_items.extend([i.__dict__ for i in items])
    if args.save:
        _set_state("last_base_items_ts", time.time())
    _json_out(all_items if args.format == "json" else all_items, args.output)


def cmd_prices(args: argparse.Namespace) -> None:
    prov = PoENinjaPriceProvider()
    league = _league_from_flag(args.league, prov)

    if args.if_stale:
        last = _get_state("last_prices_ts")
        stale = last is None or (time.time() - last) > args.if_stale * 3600
        if stale:
            log.info("Prices are stale or missing; refreshing")

    with progress(f"Prices [{league}]", 1) as bar:
        prices = prov.get_currency_prices(league=league)
        bar.update(1, info=f"{len(prices)} entries")

    if prices:
        _set_state("last_prices_ts", time.time())
        _set_state("last_prices_league", league)

    # Augment with metadata about recency when printing to stdout
    if args.format == "stdout":
        meta = {
            "league": league,
            "updated_ago_s": (time.time() - _get_state("last_prices_ts", time.time())) if prices else None,
            "count": len(prices),
        }
        print(json.dumps(meta, ensure_ascii=False, indent=2))
        print(json.dumps(prices, ensure_ascii=False, indent=2))
    else:
        _json_out(prices, args.output)


def cmd_consumables(args: argparse.Namespace) -> None:
    """
    Convenience: currencies + omens + essences in one run.
    """
    out_dir = Path(args.output_dir).expanduser() if args.output_dir else None
    out_dir.mkdir(parents=True, exist_ok=True) if out_dir else None
    client = Poe2DBClient(cache=SimpleCache())

    jobs = [
        ("Currencies", client.fetch_currencies, "currencies.json"),
        ("Omens", client.fetch_omens, "omens.json"),
        ("Essences", client.fetch_essences, "essences.json"),
    ]

    with progress("Consumables", len(jobs)) as bar:
        for idx, (label, fn, fname) in enumerate(jobs, 1):
            data = [asdict for asdict in map(lambda x: x.__dict__, fn())]
            if out_dir:
                (out_dir / fname).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            bar.update(idx, info=f"{label}: {len(data)}")

    print("Saved to", str(out_dir) if out_dir else "(stdout only)")


def cmd_all(args: argparse.Namespace) -> None:
    """
    Download everything: currencies, omens, essences, base items (all slugs), and prices.
    """
    out_dir = Path(args.output_dir).expanduser() if args.output_dir else None
    out_dir.mkdir(parents=True, exist_ok=True) if out_dir else None
    client = Poe2DBClient(cache=SimpleCache())
    prov = PoENinjaPriceProvider()
    league = _league_from_flag(args.league, prov)

    base_slugs = _iter_base_slugs(None)
    total_steps = 3 + len(base_slugs) + 1  # consumables 3 + base-items + prices

    with progress("All", total_steps) as bar:
        # Currencies
        cur = [c.__dict__ for c in client.fetch_currencies()]
        if out_dir:
            (out_dir / "currencies.json").write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")
        bar.update(info=f"currencies: {len(cur)}")

        # Omens
        om = [o.__dict__ for o in client.fetch_omens()]
        if out_dir:
            (out_dir / "omens.json").write_text(json.dumps(om, ensure_ascii=False, indent=2), encoding="utf-8")
        bar.update(info=f"omens: {len(om)}")

        # Essences
        es = [e.__dict__ for e in client.fetch_essences()]
        if out_dir:
            (out_dir / "essences.json").write_text(json.dumps(es, ensure_ascii=False, indent=2), encoding="utf-8")
        bar.update(info=f"essences: {len(es)}")

        # Base items (all slugs)
        all_bi: List[Dict[str, Any]] = []
        for slug in base_slugs:
            items = [i.__dict__ for i in client.fetch_base_items(slug)]
            all_bi.extend(items)
            if out_dir:
                (out_dir / f"base_{slug}.json").write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
            bar.update(info=f"{slug}: {len(items)}")

        # Prices
        prices = prov.get_currency_prices(league=league)
        if out_dir:
            (out_dir / f"prices_{league.replace(' ', '_')}.json").write_text(
                json.dumps(prices, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        _set_state("last_prices_ts", time.time())
        _set_state("last_prices_league", league)
        bar.update(info=f"prices: {len(prices)}")

    print("Saved to", str(out_dir) if out_dir else "(stdout only)")


# ---------- CLI ----------


def _common_output_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("-f", "--format", choices=["json", "stdout"], default="json", help="Output format (default: json)")
    p.add_argument("-o", "--output", help="Output file (when --format json)")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="poe2craft",
        description="PoE2 data & price utilities (definitions + economy).",
    )
    p.add_argument("-v", "--verbose", action="count", default=0, help="Increase verbosity (-v, -vv).")

    sub = p.add_subparsers(dest="cmd")

    sp = sub.add_parser("currencies", help="Fetch PoE2 stackable currencies from PoE2DB.")
    _common_output_args(sp)
    sp.add_argument("-s", "--save", action="store_true", help="Also save to persistent dataset dir.")
    sp.set_defaults(func=cmd_currencies)

    sp = sub.add_parser("omens", help="Fetch PoE2 Omens from PoE2DB.")
    _common_output_args(sp)
    sp.add_argument("-s", "--save", action="store_true", help="Also save to persistent dataset dir.")
    sp.set_defaults(func=cmd_omens)

    sp = sub.add_parser("essences", help="Fetch PoE2 Essences from PoE2DB.")
    _common_output_args(sp)
    sp.add_argument("-s", "--save", action="store_true", help="Also save to persistent dataset dir.")
    sp.set_defaults(func=cmd_essences)

    sp = sub.add_parser(
        "base-items",
        help="Fetch base items for a PoE2DB page slug (e.g., 'Bows'). If no slug is provided, downloads common base categories.",
    )
    _common_output_args(sp)
    sp.add_argument("slug", nargs="?", help="PoE2DB page slug (e.g., Bows, Boots, Gloves_int).")
    sp.add_argument("-s", "--save", action="store_true", help="Also save to persistent dataset dir.")
    sp.set_defaults(func=cmd_base_items)

    sp = sub.add_parser("prices", help="Fetch PoE2 currency prices and print/save a mapping.")
    _common_output_args(sp)
    sp.add_argument(
        "-l",
        "--league",
        help="League name (e.g., 'Standard', 'Rise of the Abyssal'); use 'S' for Standard, 'C' for current league.",
    )
    sp.add_argument(
        "-H",
        "--if-stale",
        type=float,
        help="Auto-refresh prices if last update is older than N hours (uses persisted timestamp).",
    )
    sp.set_defaults(func=cmd_prices)

    sp = sub.add_parser("consumables", help="Download currencies, omens, and essences together.")
    sp.add_argument("-O", "--output-dir", help="Directory to save JSON files.")
    sp.set_defaults(func=cmd_consumables)

    sp = sub.add_parser("all", help="Download currencies, omens, essences, all base items, and prices.")
    sp.add_argument("-O", "--output-dir", help="Directory to save JSON files.")
    sp.add_argument(
        "-l",
        "--league",
        help="League name (e.g., 'Standard', 'Rise of the Abyssal'); use 'S' for Standard, 'C' for current league.",
    )
    sp.set_defaults(func=cmd_all)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(argv or sys.argv[1:])
    parser = build_parser()
    args = parser.parse_args(argv)

    lvl = logging.WARNING
    if args.verbose == 1:
        lvl = logging.INFO
    elif args.verbose >= 2:
        lvl = logging.DEBUG
    logging.basicConfig(level=lvl, format="%(levelname)s %(name)s: %(message)s")

    if not hasattr(args, "func"):
        parser.print_help()
        return 0

    try:
        args.func(args)
        return 0
    except SystemExit:
        raise
    except Exception as e:
        log.error("Command failed: %s", e, exc_info=True)
        return 2


if __name__ == "__main__":
    sys.exit(main())
