#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any, List, Optional

from .datasources.poe2db_client import Poe2DBClient, DEFAULT_BASE_SLUGS
from .datasources.poeninja_prices import PoENinjaPriceProvider, detect_active_league
from .progress import progress  # keep compatibility with your progress bar

LOG = logging.getLogger("poe2craft")


def _setup_logging(verbosity: int) -> None:
    level = logging.WARNING
    if verbosity == 1:
        level = logging.INFO
    elif verbosity >= 2:
        level = logging.DEBUG
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")


def _dump_json(obj: Any, out_file: Path) -> None:
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _stdout_json(obj: Any) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


# ---------------- helpers ----------------

def _resolve_league(flag: Optional[str]) -> str:
    """
    - None or 'C' -> detect active league, fallback Standard
    - 'S'         -> Standard
    - other       -> as provided
    """
    if flag is None or flag.upper() == "C":
        cur = detect_active_league()
        if cur:
            LOG.info("Using league (detected): %s", cur)
            return cur
        LOG.info("Falling back to Standard (no current league detected)")
        return "Standard"
    if flag.upper() == "S":
        return "Standard"
    return flag


# ---------------- commands ----------------

def cmd_currencies(args: argparse.Namespace) -> None:
    client = Poe2DBClient()
    with progress("Currencies", 1) as bar:
        data = [vars(x) for x in client.fetch_stackable_currency()]
        bar.update(1, info=f"parsed {len(data)}")
    if args.save:
        _dump_json(data, Path(args.save).with_name("currencies.json"))
    if args.format == "json":
        _dump_json(data, Path(args.output))
    else:
        _stdout_json(data)


def cmd_omens(args: argparse.Namespace) -> None:
    client = Poe2DBClient()
    with progress("Omens", 1) as bar:
        data = [vars(x) for x in client.fetch_omens()]
        bar.update(1, info=f"parsed {len(data)}")
    if args.save:
        _dump_json(data, Path(args.save).with_name("omens.json"))
    if args.format == "json":
        _dump_json(data, Path(args.output))
    else:
        _stdout_json(data)


def cmd_essences(args: argparse.Namespace) -> None:
    client = Poe2DBClient()
    with progress("Essences", 1) as bar:
        data = [vars(x) for x in client.fetch_essences()]
        bar.update(1, info=f"parsed {len(data)}")
    if args.save:
        _dump_json(data, Path(args.save).with_name("essences.json"))
    if args.format == "json":
        _dump_json(data, Path(args.output))
    else:
        _stdout_json(data)


def cmd_base_items(args: argparse.Namespace) -> None:
    client = Poe2DBClient()
    slugs: List[str] = args.slug or []
    if not slugs:
        slugs = list(DEFAULT_BASE_SLUGS)

    all_items: List[dict] = []
    with progress("Base Items (slugs)", len(slugs)) as bar:
        for i, slug in enumerate(slugs, start=1):
            try:
                items = [vars(x) for x in client.fetch_base_items(slug)]
                all_items.extend(items)
                bar.update(i, info=f"{slug} -> {len(items)} items")
                if args.save:
                    _dump_json(items, Path(args.save).with_name(f"base_{slug}.json"))
            except Exception as e:
                LOG.error("Failed to fetch base items for %s: %s", slug, e)
                bar.update(i, info=f"{slug} -> error")

    if args.format == "json":
        _dump_json(all_items, Path(args.output))
    else:
        _stdout_json(all_items)


def cmd_prices(args: argparse.Namespace) -> None:
    league = _resolve_league(args.league)
    prov = PoENinjaPriceProvider()

    with progress(f"Prices [{league}]", 1) as bar:
        prices = prov.get_currency_prices(league=league)
        bar.update(1, info=f"{len(prices)} entries")

    if args.save:
        _dump_json(prices, Path(args.save).with_name("prices.json"))

    if args.format == "json":
        _dump_json(prices, Path(args.output))
    else:
        _stdout_json(prices)


def cmd_consumables(args: argparse.Namespace) -> None:
    client = Poe2DBClient()
    out = {}

    with progress("Consumables", 3) as bar:
        cur = [vars(x) for x in client.fetch_stackable_currency()]
        bar.update(1, info=f"currencies: {len(cur)}")
        om = [vars(x) for x in client.fetch_omens()]
        bar.update(2, info=f"omens: {len(om)}")
        es = [vars(x) for x in client.fetch_essences()]
        bar.update(3, info=f"essences: {len(es)}")

    if args.save:
        base = Path(args.save)
        _dump_json(cur, base.with_name("currencies.json"))
        _dump_json(om, base.with_name("omens.json"))
        _dump_json(es, base.with_name("essences.json"))

    out = {"currencies": cur, "omens": om, "essences": es}
    if args.format == "json":
        _dump_json(out, Path(args.output))
    else:
        _stdout_json(out)


def cmd_all(args: argparse.Namespace) -> None:
    """
    Download currencies, omens, essences, base items (curated slugs), and prices.
    Writes individual files when --save is given; always honors -o for a summary file when --format json.
    """
    client = Poe2DBClient()
    league = _resolve_league(args.league)

    base_summary: dict = {"league": league, "base_slugs": DEFAULT_BASE_SLUGS, "counts": {}}

    with progress("All: currencies", 1) as bar:
        cur = [vars(x) for x in client.fetch_stackable_currency()]
        bar.update(1, info=f"{len(cur)}")
        if args.save:
            _dump_json(cur, Path(args.save).with_name("currencies.json"))
        base_summary["counts"]["currencies"] = len(cur)

    with progress("All: omens", 1) as bar:
        om = [vars(x) for x in client.fetch_omens()]
        bar.update(1, info=f"{len(om)}")
        if args.save:
            _dump_json(om, Path(args.save).with_name("omens.json"))
        base_summary["counts"]["omens"] = len(om)

    with progress("All: essences", 1) as bar:
        es = [vars(x) for x in client.fetch_essences()]
        bar.update(1, info=f"{len(es)}")
        if args.save:
            _dump_json(es, Path(args.save).with_name("essences.json"))
        base_summary["counts"]["essences"] = len(es)

    all_bi: List[dict] = []
    with progress("All: base items", len(DEFAULT_BASE_SLUGS)) as bar:
        for i, slug in enumerate(DEFAULT_BASE_SLUGS, start=1):
            items = [vars(x) for x in client.fetch_base_items(slug)]
            all_bi.extend(items)
            if args.save:
                _dump_json(items, Path(args.save).with_name(f"base_{slug}.json"))
            bar.update(i, info=f"{slug}: {len(items)}")
    base_summary["counts"]["base_items_total"] = len(all_bi)

    with progress(f"All: prices [{league}]", 1) as bar:
        prov = PoENinjaPriceProvider()
        prices = prov.get_currency_prices(league=league)
        bar.update(1, info=f"{len(prices)}")
        if args.save:
            _dump_json(prices, Path(args.save).with_name("prices.json"))
    base_summary["counts"]["prices"] = len(prices)

    # Summary
    if args.format == "json":
        _dump_json(base_summary, Path(args.output))
    else:
        _stdout_json(base_summary)


# ---------------- parser ----------------

def _common_output_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("-f", "--format", choices=["json", "stdout"], default="json", help="Output format (default: json)")
    p.add_argument("-o", "--output", default="out.json", help="Output file (when --format json)")
    p.add_argument("-S", "--save", help="Also save JSON to this directory/file path (varies per command).")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="poe2craft",
        description="PoE2 data & price utilities (definitions + economy).",
    )
    p.add_argument("-v", "--verbose", action="count", default=0, help="Increase verbosity (-v, -vv).")

    sub = p.add_subparsers(dest="cmd", required=True)

    # currencies
    sp = sub.add_parser("currencies", help="Fetch PoE2 stackable currencies from PoE2DB.")
    _common_output_args(sp)
    sp.set_defaults(func=cmd_currencies)

    # omens
    sp = sub.add_parser("omens", help="Fetch PoE2 Omens from PoE2DB.")
    _common_output_args(sp)
    sp.set_defaults(func=cmd_omens)

    # essences
    sp = sub.add_parser("essences", help="Fetch PoE2 Essences from PoE2DB.")
    _common_output_args(sp)
    sp.set_defaults(func=cmd_essences)

    # base-items
    sp = sub.add_parser(
        "base-items",
        help="Fetch base items. Default is a curated set (Bows, Boots, Gloves, Helmets, Body_Armours, Quivers). "
             "Pass one or more slugs to limit (e.g., 'Bows Boots').",
    )
    _common_output_args(sp)
    sp.add_argument("slug", nargs="*", help="Optional PoE2DB page slugs (e.g., Bows, Boots, Helmets, Body_Armours, Quivers).")
    sp.set_defaults(func=cmd_base_items)

    # prices
    sp = sub.add_parser(
        "prices",
        help="Fetch PoE2 currency prices and print a plain mapping. Use '-l C' to auto-detect the current league.",
    )
    sp.add_argument("-l", "--league", help="League name (e.g., 'Standard'); use 'S' for Standard, 'C' for current league.")
    sp.add_argument("-f", "--format", choices=["json", "stdout"], default="json")
    sp.add_argument("-o", "--output", default="prices.json", help="Output file (when --format json).")
    sp.add_argument("-S", "--save", help="Also save JSON to this directory/file path (writes prices.json).")
    sp.set_defaults(func=cmd_prices)

    # consumables
    sp = sub.add_parser("consumables", help="Download currencies, omens, and essences together.")
    _common_output_args(sp)
    sp.set_defaults(func=cmd_consumables)

    # all
    sp = sub.add_parser("all", help="Download currencies, omens, essences, base items (curated), and prices.")
    sp.add_argument("-l", "--league", help="League name; 'S' for Standard, 'C' for current league.")
    _common_output_args(sp)
    sp.set_defaults(func=cmd_all)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    _setup_logging(args.verbose)
    try:
        args.func(args)
        return 0
    except Exception as e:
        LOG.error("Command failed: %s", e, exc_info=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
