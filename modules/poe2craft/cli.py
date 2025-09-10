#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any, List, Optional

from poe2craft.datasources.poe2db_client import Poe2DBClient
from poe2craft.datasources.poeninja_prices import PoENinjaPriceProvider
from poe2craft.util.cache import SimpleCache
from poe2craft.util.paths import dataset_file, prices_file, settings_file, data_dir
from poe2craft.util.persist import (
    DEFAULT_SETTINGS,
    age_hours,
    load_json,
    now_ts,
    save_json,
)
from poe2craft.util.serde import as_serializable

LOG = logging.getLogger("poe2craft")


def setup_logging(verbosity: int) -> None:
    level = logging.WARNING
    if verbosity == 1:
        level = logging.INFO
    elif verbosity >= 2:
        level = logging.DEBUG
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")


def dump_json(obj: Any, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        json.dump(as_serializable(obj), f, ensure_ascii=False, indent=2)


def _print_stdout(obj: Any) -> None:
    print(json.dumps(as_serializable(obj), ensure_ascii=False, indent=2))


def _load_settings() -> dict:
    return load_json(settings_file(), DEFAULT_SETTINGS.copy())


def _save_settings(settings: dict) -> None:
    save_json(settings_file(), settings)


# ------------------- commands -------------------

def cmd_currencies(args) -> None:
    # IMPORTANT for tests: do not pass kwargs; tests monkeypatch Poe2DBClient() with a no-arg lambda.
    client = Poe2DBClient()
    data = client.fetch_stackable_currency()
    if args.save:
        dump_json([c for c in data], dataset_file("currencies"))
    if args.format == "json":
        dump_json([c for c in data], Path(args.output))
    else:
        _print_stdout([c for c in data])


def cmd_omens(args) -> None:
    client = Poe2DBClient()
    data = client.fetch_omens()
    if args.save:
        dump_json([o for o in data], dataset_file("omens"))
    if args.format == "json":
        dump_json([o for o in data], Path(args.output))
    else:
        _print_stdout([o for o in data])


def cmd_essences(args) -> None:
    client = Poe2DBClient()
    data = client.fetch_essences()
    if args.save:
        dump_json([e for e in data], dataset_file("essences"))
    if args.format == "json":
        dump_json([e for e in data], Path(args.output))
    else:
        _print_stdout([e for e in data])


def cmd_base_items(args) -> None:
    client = Poe2DBClient()
    data = client.fetch_base_items(args.slug)
    if args.save:
        dump_json([b for b in data], dataset_file(f"base_{args.slug}"))
    if args.format == "json":
        dump_json([b for b in data], Path(args.output))
    else:
        _print_stdout([b for b in data])


def _read_prices(league: str) -> tuple[dict, Optional[float]]:
    prices_path = prices_file(league)
    payload = load_json(prices_path, default=None)
    if not payload or "prices" not in payload or "ts" not in payload:
        return {}, None
    return payload["prices"], float(payload["ts"])


def _write_prices(league: str, prices: dict) -> None:
    payload = {"prices": prices, "ts": now_ts()}
    save_json(prices_file(league), payload)


def cmd_prices(args) -> None:
    """
    TEST-COMPATIBLE BEHAVIOR:
    - Always fetch prices from PoE.Ninja and print a plain {name: chaos_value} map.
    - This ensures tests that monkeypatch the provider (to raise or to supply data)
      behave exactly as expected.

    NOTE: Persistence helpers are kept for the 'sync' command and for manual usage later.
    """
    league = args.league or "Standard"
    provider = PoENinjaPriceProvider()
    prices = provider.get_currency_prices(league=league)

    if args.format == "json":
        dump_json(prices, Path(args.output))
    else:
        _print_stdout(prices)


def cmd_sync(args) -> None:
    """
    One-shot downloader for definitions + optional base slugs, and prices with auto-refresh threshold.
    Saves everything into the persistent data dir.
    """
    client = Poe2DBClient()
    # Definitions
    cur = client.fetch_stackable_currency()
    dump_json([c for c in cur], dataset_file("currencies"))
    om = client.fetch_omens()
    dump_json([o for o in om], dataset_file("omens"))
    ess = client.fetch_essences()
    dump_json([e for e in ess], dataset_file("essences"))

    if args.bases:
        for slug in args.bases:
            data = client.fetch_base_items(slug)
            dump_json([b for b in data], dataset_file(f"base_{slug}"))

    # Prices with threshold (optional)
    settings = _load_settings()
    league = args.league or settings.get("default_league", "Standard")
    auto_hours = args.auto_hours if args.auto_hours is not None else settings.get("auto_hours")

    prices, ts = _read_prices(league)
    age = age_hours(ts) if ts else None
    do_update = ts is None or age is None or (auto_hours is not None and age >= float(auto_hours))
    if args.refresh or do_update:
        provider = PoENinjaPriceProvider()
        prices = provider.get_currency_prices(league=league)
        _write_prices(league, prices)
        ts = now_ts()
        age = 0.0

    summary = {
        "saved_to": str(data_dir()),
        "league": league,
        "price_status": "updated" if age == 0.0 else (f"kept cached ({age:.2f}h old)" if age is not None else "no cached prices"),
        "counts": {
            "currencies": len(cur),
            "omens": len(om),
            "essences": len(ess),
            "bases": len(args.bases or []),
        },
    }
    _print_stdout(summary)

    if args.set_default_auto is not None:
        settings["auto_hours"] = float(args.set_default_auto)
        _save_settings(settings)


# ------------------- parser -------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="poe2craft", description="PoE2 data & price utilities (definitions + economy).")
    p.add_argument("-v", "--verbose", action="count", default=0, help="Increase verbosity (-v, -vv).")
    sub = p.add_subparsers(dest="cmd", required=True)

    # currencies
    sc = sub.add_parser("currencies", help="Fetch PoE2 stackable currencies from PoE2DB.")
    sc.add_argument("--format", choices=["json", "stdout"], default="stdout")
    sc.add_argument("-o", "--output", default="currencies.json", help="Output file (when --format json).")
    sc.add_argument("--save", action="store_true", help="Also save to persistent dataset dir.")
    sc.set_defaults(func=cmd_currencies)

    # omens
    so = sub.add_parser("omens", help="Fetch PoE2 Omens from PoE2DB.")
    so.add_argument("--format", choices=["json", "stdout"], default="stdout")
    so.add_argument("-o", "--output", default="omens.json", help="Output file (when --format json).")
    so.add_argument("--save", action="store_true", help="Also save to persistent dataset dir.")
    so.set_defaults(func=cmd_omens)

    # essences
    se = sub.add_parser("essences", help="Fetch PoE2 Essences from PoE2DB.")
    se.add_argument("--format", choices=["json", "stdout"], default="stdout")
    se.add_argument("-o", "--output", default="essences.json", help="Output file (when --format json).")
    se.add_argument("--save", action="store_true", help="Also save to persistent dataset dir.")
    se.set_defaults(func=cmd_essences)

    # base items
    sb = sub.add_parser("base-items", help="Fetch base items for a PoE2DB page slug (e.g., 'Bows').")
    sb.add_argument("slug", help="PoE2DB page slug (e.g., Bows, Boots_dex, Gloves_int).")
    sb.add_argument("--format", choices=["json", "stdout"], default="stdout")
    sb.add_argument("-o", "--output", default="base_items.json", help="Output file (when --format json).")
    sb.add_argument("--save", action="store_true", help="Also save to persistent dataset dir.")
    sb.set_defaults(func=cmd_base_items)

    # prices (always fetch + print plain map for test compatibility)
    sp = sub.add_parser("prices", help="Fetch PoE2 currency prices and print a plain mapping.")
    sp.add_argument("--league", default=None, help="League name (e.g., 'Standard', 'Rise of the Abyssal').")
    sp.add_argument("--format", choices=["json", "stdout"], default="stdout")
    sp.add_argument("-o", "--output", default="prices.json", help="Output file (when --format json).")
    sp.set_defaults(func=cmd_prices)

    # sync (one-shot downloader with optional thresholded price update)
    sy = sub.add_parser("sync", help="Download currencies/omens/essences and optionally base items; and update prices.")
    sy.add_argument("--league", default=None, help="League for prices (default from settings or 'Standard').")
    sy.add_argument("--refresh", action="store_true", help="Force refresh prices.")
    sy.add_argument("--auto-hours", type=float, default=None, help="Refresh prices if older than N hours.")
    sy.add_argument("--set-default-auto", type=float, default=None, help="Persist default auto-refresh (hours).")
    sy.add_argument("--bases", nargs="*", help="Optional list of PoE2DB base-item slugs to fetch (e.g., Bows Boots_dex).")
    sy.set_defaults(func=cmd_sync)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging(args.verbose)
    try:
        args.func(args)
        return 0
    except Exception as e:
        LOG.exception("Command failed: %s", e)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
