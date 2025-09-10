#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any, List, Optional

from poe2craft.datasources.poe2db_client import Poe2DBClient
from poe2craft.datasources.poeninja_prices import PoENinjaPriceProvider
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


def cmd_currencies(args) -> None:
    client = Poe2DBClient()
    data = client.fetch_stackable_currency()
    if args.format == "json":
        dump_json([c for c in data], Path(args.output))
    else:
        _print_stdout([c for c in data])


def cmd_omens(args) -> None:
    client = Poe2DBClient()
    data = client.fetch_omens()
    if args.format == "json":
        dump_json([o for o in data], Path(args.output))
    else:
        _print_stdout([o for o in data])


def cmd_essences(args) -> None:
    client = Poe2DBClient()
    data = client.fetch_essences()
    if args.format == "json":
        dump_json([e for e in data], Path(args.output))
    else:
        _print_stdout([e for e in data])


def cmd_base_items(args) -> None:
    client = Poe2DBClient()
    data = client.fetch_base_items(args.slug)
    if args.format == "json":
        dump_json([b for b in data], Path(args.output))
    else:
        _print_stdout([b for b in data])


def cmd_prices(args) -> None:
    provider = PoENinjaPriceProvider()
    prices = provider.get_currency_prices(league=args.league)
    if args.format == "json":
        dump_json(prices, Path(args.output))
    else:
        _print_stdout(prices)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="poe2craft", description="PoE2 data & price utilities (definitions + economy).")
    p.add_argument("-v", "--verbose", action="count", default=0, help="Increase verbosity (-v, -vv).")
    sub = p.add_subparsers(dest="cmd", required=True)

    sc = sub.add_parser("currencies", help="Fetch PoE2 stackable currencies from PoE2DB.")
    sc.add_argument("--format", choices=["json", "stdout"], default="stdout")
    sc.add_argument("-o", "--output", default="currencies.json", help="Output file (when --format json).")
    sc.set_defaults(func=cmd_currencies)

    so = sub.add_parser("omens", help="Fetch PoE2 Omens from PoE2DB.")
    so.add_argument("--format", choices=["json", "stdout"], default="stdout")
    so.add_argument("-o", "--output", default="omens.json", help="Output file (when --format json).")
    so.set_defaults(func=cmd_omens)

    se = sub.add_parser("essences", help="Fetch PoE2 Essences from PoE2DB.")
    se.add_argument("--format", choices=["json", "stdout"], default="stdout")
    se.add_argument("-o", "--output", default="essences.json", help="Output file (when --format json).")
    se.set_defaults(func=cmd_essences)

    sb = sub.add_parser("base-items", help="Fetch base items for a given PoE2DB item-class page slug (e.g., 'Bows').")
    sb.add_argument("slug", help="PoE2DB page slug (e.g., Bows, Boots_dex, Gloves_int, etc).")
    sb.add_argument("--format", choices=["json", "stdout"], default="stdout")
    sb.add_argument("-o", "--output", default="base_items.json", help="Output file (when --format json).")
    sb.set_defaults(func=cmd_base_items)

    sp = sub.add_parser("prices", help="Fetch PoE2 currency prices from poe.ninja (API if available, else page scrape).")
    sp.add_argument("--league", default="Standard", help="League name (e.g., 'Standard', 'Rise of the Abyssal').")
    sp.add_argument("--format", choices=["json", "stdout"], default="stdout")
    sp.add_argument("-o", "--output", default="prices.json", help="Output file (when --format json).")
    sp.set_defaults(func=cmd_prices)

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
