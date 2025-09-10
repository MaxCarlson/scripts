#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any, List, Optional

from poe2craft.datasources.poe2db_client import Poe2DBClient, DEFAULT_BASE_SLUGS
from poe2craft.datasources.poeninja_prices import PoENinjaPriceProvider, detect_active_league
from poe2craft.ui.progress import Progress
from poe2craft.util.serde import as_serializable  # existing util in your tree

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


# ------------------- helpers -------------------

def _league_resolve(val: Optional[str]) -> str:
    """
    - None or 'C' -> try to auto-detect active league; fallback Standard
    - 'S'         -> Standard
    - other       -> as provided
    """
    if not val or val.upper() == "C":
        l = detect_active_league() or "Standard"
        LOG.info("Using league: %s", l)
        return l
    if val.upper() == "S":
        return "Standard"
    return val


# ------------------- commands -------------------

def cmd_currencies(args) -> None:
    # DO NOT pass kwargs; tests monkeypatch Poe2DBClient() with a zero-arg lambda.
    client = Poe2DBClient()
    with Progress().task("Currencies"):
        data = client.fetch_stackable_currency()
    if args.save:
        dump_json([c for c in data], Path(args.save))
    if args.format == "json":
        dump_json([c for c in data], Path(args.output))
    else:
        _print_stdout([c for c in data])


def cmd_omens(args) -> None:
    client = Poe2DBClient()
    with Progress().task("Omens"):
        data = client.fetch_omens()
    if args.save:
        dump_json([o for o in data], Path(args.save))
    if args.format == "json":
        dump_json([o for o in data], Path(args.output))
    else:
        _print_stdout([o for o in data])


def cmd_essences(args) -> None:
    client = Poe2DBClient()
    with Progress().task("Essences"):
        data = client.fetch_essences()
    if args.save:
        dump_json([e for e in data], Path(args.save))
    if args.format == "json":
        dump_json([e for e in data], Path(args.output))
    else:
        _print_stdout([e for e in data])


def cmd_base_items(args) -> None:
    client = Poe2DBClient()
    slugs = args.slug or []
    if not slugs:
        slugs = DEFAULT_BASE_SLUGS
    prog = Progress()
    all_items = []
    with prog.task("Base Items (slugs)", total=len(slugs)) as bar:
        for slug in slugs:
            items = client.fetch_base_items(slug)
            all_items.extend(items)
            bar.update(detail=f"{slug} -> {len(items)} items")
    if args.save:
        for slug in slugs:
            items = [b for b in all_items if b.name]  # simple split; we still saved per-page above if desired
            dump_json([b for b in items], Path(args.save))
    if args.format == "json":
        dump_json([b for b in all_items], Path(args.output))
    else:
        _print_stdout([b for b in all_items])


def cmd_prices(args) -> None:
    league = _league_resolve(args.league)
    provider = PoENinjaPriceProvider()
    with Progress().task(f"Prices [{league}]"):
        prices = provider.get_currency_prices(league=league)

    # IMPORTANT for tests: print a plain {name: value} map when stdout
    if args.format == "json":
        dump_json(prices, Path(args.output))
    else:
        _print_stdout(prices)


def cmd_consumables(args) -> None:
    """Download currencies + omens + essences together."""
    client = Poe2DBClient()
    p = Progress()
    out = {}
    with p.task("Consumables: currencies"):
        cur = client.fetch_stackable_currency()
        out["currencies"] = cur
    with p.task("Consumables: omens"):
        om = client.fetch_omens()
        out["omens"] = om
    with p.task("Consumables: essences"):
        ess = client.fetch_essences()
        out["essences"] = ess

    if args.save:
        dump_json([c for c in cur], Path(args.save).with_name("currencies.json"))
        dump_json([o for o in om], Path(args.save).with_name("omens.json"))
        dump_json([e for e in ess], Path(args.save).with_name("essences.json"))

    if args.format == "json":
        dump_json(out, Path(args.output))
    else:
        _print_stdout(out)


def cmd_all(args) -> None:
    """Download everything: currencies, omens, essences, base items (curated), and prices."""
    client = Poe2DBClient()
    league = _league_resolve(args.league)
    p = Progress()

    with p.task("All: currencies"):
        cur = client.fetch_stackable_currency()
        if args.save:
            dump_json([c for c in cur], Path(args.save).with_name("currencies.json"))

    with p.task("All: omens"):
        om = client.fetch_omens()
        if args.save:
            dump_json([o for o in om], Path(args.save).with_name("omens.json"))

    with p.task("All: essences"):
        ess = client.fetch_essences()
        if args.save:
            dump_json([e for e in ess], Path(args.save).with_name("essences.json"))

    with p.task("All: base items", total=len(DEFAULT_BASE_SLUGS)) as bar:
        for slug in DEFAULT_BASE_SLUGS:
            items = client.fetch_base_items(slug)
            if args.save:
                dump_json([b for b in items], Path(args.save).with_name(f"base_{slug}.json"))
            bar.update(detail=f"{slug}: {len(items)}")

    with p.task(f"All: prices [{league}]"):
        provider = PoENinjaPriceProvider()
        prices = provider.get_currency_prices(league=league)
        if args.save:
            dump_json(prices, Path(args.save).with_name(f"prices_{league.replace(' ', '_').lower()}.json"))

    # Brief summary to stdout
    _print_stdout({
        "saved": bool(args.save),
        "league": league,
        "base_slugs": DEFAULT_BASE_SLUGS,
        "counts": {
            "currencies": len(cur),
            "omens": len(om),
            "essences": len(ess),
        },
    })


# ------------------- parser -------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="poe2craft", description="PoE2 data & price utilities (definitions + economy).")
    p.add_argument("-v", "--verbose", action="count", default=0, help="Increase verbosity (-v, -vv).")
    sub = p.add_subparsers(dest="cmd", required=True)

    # Small helper to keep options consistent
    def add_common_io(sp):
        sp.add_argument("-f", "--format", choices=["json", "stdout"], default="json", help="Output format (default: json).")
        sp.add_argument("-o", "--output", default="out.json", help="Output file when --format json.")
        sp.add_argument("-S", "--save", help="Also save JSON to this directory/file path (varies per command).")

    # currencies
    sc = sub.add_parser("currencies", help="Fetch PoE2 stackable currencies from PoE2DB.")
    add_common_io(sc)
    sc.set_defaults(func=cmd_currencies)

    # omens
    so = sub.add_parser("omens", help="Fetch PoE2 Omens from PoE2DB.")
    add_common_io(so)
    so.set_defaults(func=cmd_omens)

    # essences
    se = sub.add_parser("essences", help="Fetch PoE2 Essences from PoE2DB.")
    add_common_io(se)
    se.set_defaults(func=cmd_essences)

    # base items
    sb = sub.add_parser(
        "base-items",
        help="Fetch base items. Default is all curated slugs; pass one or more slugs to limit (e.g., 'Bows').",
    )
    add_common_io(sb)
    sb.add_argument("slug", nargs="*", help="Optional PoE2DB page slugs (e.g., Bows, Boots, Helmets, Body_Armours).")
    sb.set_defaults(func=cmd_base_items)

    # prices (always fetch + print plain map when --format stdout)
    sp = sub.add_parser(
        "prices",
        help="Fetch PoE2 currency prices and print a plain mapping (use -l C to auto-detect current league).",
    )
    sp.add_argument("-l", "--league", default=None, help="League name or shorthand (S=Standard, C=Current).")
    sp.add_argument("-f", "--format", choices=["json", "stdout"], default="json", help="Output format (default: json).")
    sp.add_argument("-o", "--output", default="prices.json", help="Output file when --format json.")
    sp.set_defaults(func=cmd_prices)

    # consumables
    sm = sub.add_parser("consumables", help="Download currencies + omens + essences together.")
    add_common_io(sm)
    sm.set_defaults(func=cmd_consumables)

    # all
    sa = sub.add_parser("all", help="Download currencies, omens, essences, base items (curated), and prices.")
    sa.add_argument("-l", "--league", default=None, help="League name or shorthand (S=Standard, C=Current).")
    sa.add_argument("-S", "--save", help="Directory to save JSON outputs.")
    sa.add_argument("-f", "--format", choices=["json", "stdout"], default="json", help="Summary output format (default: json).")
    sa.add_argument("-o", "--output", default="all_summary.json", help="Summary file when --format json.")
    sa.set_defaults(func=cmd_all)

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
