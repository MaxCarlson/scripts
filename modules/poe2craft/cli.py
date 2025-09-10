#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any, List, Optional

from poe2craft.datasources.poe2db_client import Poe2DBClient
from poe2craft.datasources.poe2db_client import DEFAULT_BASE_SLUGS
from poe2craft.datasources.poeninja_prices import PoENinjaPriceProvider, detect_active_league
from poe2craft.ui.progress import Progress
from poe2craft.util.paths import dataset_file
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


# ------------------- commands -------------------

def _league_resolve(val: Optional[str]) -> str:
    """Map aliases: 'S' -> Standard, 'C' -> active league; None -> active league or Standard fallback."""
    if not val or val.upper() == "C":
        league = detect_active_league() or "Standard"
        LOG.info("Using league: %s", league)
        return league
    if val.upper() == "S":
        return "Standard"
    return val


def cmd_currencies(args) -> None:
    client = Poe2DBClient()
    with Progress(enabled=not args.quiet_progress).task("Currencies") as bar:
        data = client.fetch_stackable_currency()
        bar.set(len(data), f"parsed {len(data)}")
    if args.save:
        dump_json([c for c in data], dataset_file("currencies"))
    if args.format == "json":
        dump_json([c for c in data], Path(args.output))
    else:
        _print_stdout([c for c in data])


def cmd_omens(args) -> None:
    client = Poe2DBClient()
    with Progress(enabled=not args.quiet_progress).task("Omens") as bar:
        data = client.fetch_omens()
        bar.set(len(data), f"parsed {len(data)}")
    if args.save:
        dump_json([o for o in data], dataset_file("omens"))
    if args.format == "json":
        dump_json([o for o in data], Path(args.output))
    else:
        _print_stdout([o for o in data])


def cmd_essences(args) -> None:
    client = Poe2DBClient()
    with Progress(enabled=not args.quiet_progress).task("Essences") as bar:
        data = client.fetch_essences()
        bar.set(len(data), f"parsed {len(data)}")
    if args.save:
        dump_json([e for e in data], dataset_file("essences"))
    if args.format == "json":
        dump_json([e for e in data], Path(args.output))
    else:
        _print_stdout([e for e in data])


def cmd_base_items(args) -> None:
    client = Poe2DBClient()
    slugs = args.slug or []
    if not slugs:
        slugs = DEFAULT_BASE_SLUGS
    prog = Progress(enabled=not args.quiet_progress)
    all_items = []
    with prog.task("Base Items (slugs)", total=len(slugs)) as bar:
        for slug in slugs:
            items = client.fetch_base_items(slug)
            all_items.extend(items)
            bar.update(detail=f"{slug} -> {len(items)} items")
    if args.save:
        for slug in slugs:
            items = [b for b in all_items if b.item_class.value.lower() in slug.lower() or b.name]
            dump_json([b for b in items], dataset_file(f"base_{slug}"))
    if args.format == "json":
        dump_json([b for b in all_items], Path(args.output))
    else:
        _print_stdout([b for b in all_items])


def cmd_prices(args) -> None:
    league = _league_resolve(args.league)
    provider = PoENinjaPriceProvider()
    with Progress(enabled=not args.quiet_progress).task(f"Prices [{league}]"):
        prices = provider.get_currency_prices(league=league)
    if args.format == "json":
        dump_json(prices, Path(args.output))
    else:
        _print_stdout(prices)


def cmd_consumables(args) -> None:
    """Download currencies + omens + essences together."""
    client = Poe2DBClient()
    p = Progress(enabled=not args.quiet_progress)
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
        dump_json([c for c in cur], dataset_file("currencies"))
        dump_json([o for o in om], dataset_file("omens"))
        dump_json([e for e in ess], dataset_file("essences"))

    if args.format == "json":
        dump_json(out, Path(args.output))
    else:
        _print_stdout(out)


def cmd_all(args) -> None:
    """Download everything: currencies, omens, essences, base items (default slugs), and prices."""
    client = Poe2DBClient()
    league = _league_resolve(args.league)
    p = Progress(enabled=not args.quiet_progress)

    with p.task("All: currencies"):
        cur = client.fetch_stackable_currency()
        dump_json([c for c in cur], dataset_file("currencies"))

    with p.task("All: omens"):
        om = client.fetch_omens()
        dump_json([o for o in om], dataset_file("omens"))

    with p.task("All: essences"):
        ess = client.fetch_essences()
        dump_json([e for e in ess], dataset_file("essences"))

    with p.task("All: base items", total=len(DEFAULT_BASE_SLUGS)) as bar:
        for slug in DEFAULT_BASE_SLUGS:
            items = client.fetch_base_items(slug)
            dump_json([b for b in items], dataset_file(f"base_{slug}"))
            bar.update(detail=f"{slug}: {len(items)}")

    with p.task(f"All: prices [{league}]"):
        provider = PoENinjaPriceProvider()
        prices = provider.get_currency_prices(league=league)
    dump_json(prices, dataset_file(f"prices_{league.replace(' ', '_').lower()}"))

    _print_stdout({
        "saved": True,
        "league": league,
        "base_slugs": DEFAULT_BASE_SLUGS,
        "counts": {
            "currencies": len(cur),
            "omens": len(om),
            "essences": len(ess)
        }
    })


# ------------------- parser -------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="poe2craft",
        description="PoE2 data & price utilities (definitions + economy)."
    )
    p.add_argument("-v", "--verbose", action="count", default=0, help="Increase verbosity (-v, -vv).")
    sub = p.add_subparsers(dest="cmd", required=True)

    # Shared options template
    def add_common_io(sp):
        sp.add_argument("-f", "--format", choices=["json", "stdout"], default="json", help="Output format.")
        sp.add_argument("-o", "--output", default="out.json", help="Output file when --format json.")
        sp.add_argument("-S", "--save", action="store_true", help="Also save to the persistent dataset directory.")
        sp.add_argument("-q", "--quiet-progress", action="store_true", help="Disable progress bars.")

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
        help="Fetch base items. Default is all curated slugs; pass one or more slugs to limit (e.g., 'Bows')."
    )
    add_common_io(sb)
    sb.add_argument("slug", nargs="*", help="Optional PoE2DB page slugs (e.g., Bows, Boots, Helmet).")
    sb.set_defaults(func=cmd_base_items)

    # prices
    sp = sub.add_parser(
        "prices",
        help="Fetch PoE2 currency prices and print a plain mapping (auto-detects active league with -l C)."
    )
    sp.add_argument("-l", "--league", default=None, help="League name or shorthand (S=Standard, C=Current).")
    sp.add_argument("-f", "--format", choices=["json", "stdout"], default="json", help="Output format.")
    sp.add_argument("-o", "--output", default="prices.json", help="Output file when --format json.")
    sp.add_argument("-q", "--quiet-progress", action="store_true", help="Disable progress bars.")
    sp.set_defaults(func=cmd_prices)

    # consumables
    sm = sub.add_parser("consumables", help="Download currencies + omens + essences together.")
    add_common_io(sm)
    sm.set_defaults(func=cmd_consumables)

    # all
    sa = sub.add_parser("all", help="Download currencies, omens, essences, base items (curated), and prices.")
    sa.add_argument("-l", "--league", default=None, help="League name or shorthand (S=Standard, C=Current).")
    sa.add_argument("-q", "--quiet-progress", action="store_true", help="Disable progress bars.")
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
