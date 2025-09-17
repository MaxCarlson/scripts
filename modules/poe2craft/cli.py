# File: poe2craft/cli.py
import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Module-local logger (tests assert/inspect this name in traces)
LOG = logging.getLogger("poe2craft.cli")

# Imports that tests monkeypatch in-place
from .datasources.poe2db_client import Poe2DBClient  # noqa: E402
from .datasources.poeninja_prices import (  # noqa: E402
    PoENinjaPriceProvider,
    detect_active_league,
)

# -------------------------
# Helpers
# -------------------------
def _configure_logging(verbosity: int, log_file: Optional[str]) -> None:
    level = logging.WARNING
    if verbosity >= 2:
        level = logging.DEBUG
    elif verbosity == 1:
        level = logging.INFO

    handlers: List[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    logging.basicConfig(
        level=level,
        format="%(levelname)s %(name)s:%(lineno)d %(message)s",
        handlers=handlers,
    )


def _progress(label: str, i: int, n: int, msg: str) -> None:
    pct = 100.0 if n == 0 else round(100.0 * i / max(n, 1), 1)
    print(f"[{label}] {i}/{n} {pct:>5}% | {msg}", file=sys.stderr)


def _stdout_json(obj: Any) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def _resolve_league(arg: Optional[str], provider: PoENinjaPriceProvider) -> Optional[str]:
    """
    Resolves a league argument. Special values:
      - None: return None (caller decides)
      - "current": attempt to detect from poe.ninja; provider may be monkeypatched in tests
    """
    if not arg:
        return None
    if arg.lower() == "current":
        detected = detect_active_league(session=provider.session)
        return detected
    return arg


# -------------------------
# Command implementations
# -------------------------
def cmd_currencies(args: argparse.Namespace) -> None:
    c = Poe2DBClient()
    # Tests' fake client exposes fetch_stackable_currency (not fetch_currencies).
    items = c.fetch_stackable_currency()
    _progress("Currencies", 1, 1, f"parsed {len(items)}")
    if args.format == "stdout":
        _stdout_json(items)
    else:
        out = Path(args.output or "currencies.json")
        _write_json(out, items)


def cmd_omens(args: argparse.Namespace) -> None:
    c = Poe2DBClient()
    items = c.fetch_omens()
    _progress("Omens", 1, 1, f"parsed {len(items)}")
    if args.format == "stdout":
        _stdout_json(items)
    else:
        out = Path(args.output or "omens.json")
        _write_json(out, items)


def cmd_essences(args: argparse.Namespace) -> None:
    c = Poe2DBClient()
    items = c.fetch_essences()
    _progress("Essences", 1, 1, f"parsed {len(items)}")
    if args.format == "stdout":
        _stdout_json(items)
    else:
        out = Path(args.output or "essences.json")
        _write_json(out, items)


def cmd_base_items(args: argparse.Namespace) -> None:
    c = Poe2DBClient()
    slugs = args.slugs or ["Bows", "Boots", "Gloves", "Helmets", "Body_Armours", "Quivers"]
    out_all: List[dict] = []
    for i, slug in enumerate(slugs, 1):
        items = c.fetch_base_items(slug)
        out_all.extend(items)
        _progress("Base Items (slugs)", i, len(slugs), f"{slug} -> {len(items)} items")
    if args.format == "stdout":
        _stdout_json(out_all)
    else:
        out = Path(args.output or "base_items.json")
        _write_json(out, out_all)


def cmd_prices(args: argparse.Namespace) -> None:
    provider = PoENinjaPriceProvider()
    league = _resolve_league(args.league, provider) or "Standard"
    prices = provider.fetch_prices(league)
    _progress(f"Prices [{league}]", 1, 1, f"{len(prices)} entries")
    if args.format == "stdout":
        _stdout_json(prices)
    else:
        out = Path(args.output or "prices.json")
        _write_json(out, prices)


def cmd_all(args: argparse.Namespace) -> None:
    # scrape everything and dump a single JSON
    provider = PoENinjaPriceProvider()
    league = _resolve_league(args.league, provider) or "Standard"

    c = Poe2DBClient()

    currencies = c.fetch_stackable_currency()
    _progress("Currencies", 1, 1, f"parsed {len(currencies)}")

    omens = c.fetch_omens()
    _progress("Omens", 1, 1, f"parsed {len(omens)}")

    essences = c.fetch_essences()
    _progress("Essences", 1, 1, f"parsed {len(essences)}")

    base_slugs = ["Bows", "Boots", "Gloves", "Helmets", "Body_Armours", "Quivers"]
    base_items_all: List[dict] = []
    for i, slug in enumerate(base_slugs, 1):
        items = c.fetch_base_items(slug)
        base_items_all.extend(items)
        _progress("Base Items (slugs)", i, len(base_slugs), f"{slug} -> {len(items)} items")

    prices = provider.fetch_prices(league)
    _progress(f"Prices [{league}]", 1, 1, f"{len(prices)} entries")

    bundle: Dict[str, Any] = {
        "currencies": currencies,
        "omens": omens,
        "essences": essences,
        "base_items": base_items_all,
        "prices": prices,
        "league": league,
    }

    if args.format == "stdout":
        _stdout_json(bundle)
    else:
        out = Path(args.output or "all.json")
        _write_json(out, bundle)


# -------------------------
# CLI plumbing
# -------------------------
def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="poe2craft", description="PoE2 data grabber / utilities")
    p.add_argument("-v", "--verbose", action="count", default=0, help="Increase verbosity")
    p.add_argument("--log-file", default=None, help="Optional log file path")

    sub = p.add_subparsers(dest="cmd", required=True)

    def add_common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("-f", "--format", choices=["stdout", "json"], default="json")
        sp.add_argument("-o", "--output", default=None)

    sp = sub.add_parser("currencies", help="Scrape stackable currencies from PoE2DB")
    add_common(sp)
    sp.set_defaults(func=cmd_currencies)

    sp = sub.add_parser("omens", help="Scrape omens from PoE2DB")
    add_common(sp)
    sp.set_defaults(func=cmd_omens)

    sp = sub.add_parser("essences", help="Scrape essences from PoE2DB")
    add_common(sp)
    sp.set_defaults(func=cmd_essences)

    sp = sub.add_parser("base-items", help="Scrape base items for given slugs")
    add_common(sp)
    sp.add_argument("slugs", nargs="*", help="Category slugs like Bows, Boots, ...")
    sp.set_defaults(func=cmd_base_items)

    sp = sub.add_parser("prices", help="Fetch currency prices from poe.ninja")
    add_common(sp)
    sp.add_argument("-l", "--league", default="current", help='League name or "current"')
    sp.set_defaults(func=cmd_prices)

    sp = sub.add_parser("all", help="Run all scrapers and bundle output")
    add_common(sp)
    sp.add_argument("-l", "--league", default="current", help='League name or "current"')
    sp.set_defaults(func=cmd_all)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    _configure_logging(args.verbose, args.log_file)

    try:
        args.func(args)
        return 0
    except SystemExit:
        raise
    except Exception as e:
        LOG.error("Command failed", exc_info=e)
        return 2


if __name__ == "__main__":
    sys.exit(main())
