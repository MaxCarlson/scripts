#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .datasources.poe2db_client import Poe2DBClient
from .datasources.poeninja_prices import PoENinjaPriceProvider, detect_active_league

LOG = logging.getLogger("poe2craft.cli")

DEFAULT_BASE_SLUGS = ["Bows", "Boots", "Gloves", "Helmets", "Body_Armours", "Quivers"]

# ---------- utilities ----------

def _setup_logging(verbosity: int, log_file: Optional[str]):
    level = logging.WARNING
    if verbosity == 1:
        level = logging.INFO
    elif verbosity >= 2:
        level = logging.DEBUG
    handlers: List[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(
        level=level,
        format="%(levelname)s %(name)s:%(lineno)d %(message)s",
        handlers=handlers,
        force=True,
    )

def _progress(prefix: str, i: int, n: int, suffix: str = ""):
    pct = int((i / max(1, n)) * 100)
    left = f"[{prefix}] {i}/{n} {pct:3d}.0%"
    if suffix:
        left += f" | {suffix}"
    print(left, file=sys.stderr)

def _safe_default(o: Any):
    if is_dataclass(o):
        return asdict(o)
    if isinstance(o, Enum):
        return o.value
    if isinstance(o, (set,)):
        return list(o)
    raise TypeError(f"Object of type {o.__class__.__name__} is not JSON serializable")

def _stdout_json(obj: Any):
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=_safe_default))

def _write_json(path: Path, obj: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, default=_safe_default)

def _resolve_league(arg: str, provider: PoENinjaPriceProvider) -> str:
    if arg and arg.lower() in {"c", "current"}:
        detected = detect_active_league(provider.session)
        if detected:
            LOG.info("Detected active league: %s", detected)
            return detected
        LOG.warning("Could not detect active league; falling back to Standard")
        return "Standard"
    return arg or "Standard"

# ---------- commands ----------

def cmd_currencies(args):
    c = Poe2DBClient()
    items = c.fetch_currencies()
    _progress("Currencies", 1, 1, f"parsed {len(items)}")
    if args.format == "stdout":
        _stdout_json(items)
    else:
        _write_json(Path(args.output or "currencies.json"), items)

def cmd_omens(args):
    c = Poe2DBClient()
    items = c.fetch_omens()
    _progress("Omens", 1, 1, f"parsed {len(items)}")
    if args.format == "stdout":
        _stdout_json(items)
    else:
        _write_json(Path(args.output or "omens.json"), items)

def cmd_essences(args):
    c = Poe2DBClient()
    items = c.fetch_essences()
    _progress("Essences", 1, 1, f"parsed {len(items)}")
    if args.format == "stdout":
        _stdout_json(items)
    else:
        _write_json(Path(args.output or "essences.json"), items)

def cmd_base_items(args):
    c = Poe2DBClient()
    slugs = args.slugs or DEFAULT_BASE_SLUGS
    all_items: List[Dict[str, Any]] = []
    for i, slug in enumerate(slugs, 1):
        items = c.fetch_base_items(slug)
        _progress("Base Items (slugs)", i, len(slugs), f"{slug} -> {len(items)} items")
        all_items.extend(items)
    if args.format == "stdout":
        _stdout_json(all_items)
    else:
        _write_json(Path(args.output or "base-items.json"), all_items)

def cmd_prices(args):
    prov = PoENinjaPriceProvider()
    league = _resolve_league(args.league, prov)
    prices = prov.get_currency_prices(league=league)
    _progress(f"Prices [{league}]", 1, 1, f"{len(prices)} entries")
    if args.format == "stdout":
        _stdout_json(prices)
    else:
        _write_json(Path(args.output or "prices.json"), prices)

def cmd_all(args):
    # Decide stdout vs files
    to_stdout = (args.format == "stdout") or (args.output is None and args.format == "json")
    out_dir = Path(args.output) if args.output else Path(os.getcwd())

    # Run each subcommand in sequence with progress
    c = Poe2DBClient()
    currencies = c.fetch_currencies()
    _progress("Currencies", 1, 1, f"parsed {len(currencies)}")

    omens = c.fetch_omens()
    _progress("Omens", 1, 1, f"parsed {len(omens)}")

    essences = c.fetch_essences()
    _progress("Essences", 1, 1, f"parsed {len(essences)}")

    base_all: List[Dict[str, Any]] = []
    for i, slug in enumerate(DEFAULT_BASE_SLUGS, 1):
        items = c.fetch_base_items(slug)
        _progress("Base Items (slugs)", i, len(DEFAULT_BASE_SLUGS), f"{slug} -> {len(items)} items")
        base_all.extend(items)

    prov = PoENinjaPriceProvider()
    league = _resolve_league(args.league, prov)
    prices = prov.get_currency_prices(league=league)
    _progress(f"Prices [{league}]", 1, 1, f"{len(prices)} entries")

    if to_stdout:
        # Print a structured object with sections to STDOUT
        _stdout_json(
            {
                "currencies": currencies,
                "omens": omens,
                "essences": essences,
                "base_items": base_all,
                "prices": prices,
                "league": league,
            }
        )
    else:
        _write_json(out_dir / "currencies.json", currencies)
        _write_json(out_dir / "omens.json", omens)
        _write_json(out_dir / "essences.json", essences)
        _write_json(out_dir / "base-items.json", base_all)
        _write_json(out_dir / "prices.json", prices)
        # mimic your “sizes” footer
        for fname in ("currencies.json", "omens.json", "essences.json", "base-items.json", "prices.json"):
            p = out_dir / fname
            try:
                print(f"{p.stat().st_size:<6}  -I  {fname}", file=sys.stderr)
            except Exception:
                pass

# ---------- main ----------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="poe2craft", description="PoE2 data scrapers & price fetchers")
    p.add_argument("-v", action="count", default=0, help="Increase verbosity (-v, -vv)")
    p.add_argument("--log-file", default=None, help="Write logs to this file")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_common(sp):
        sp.add_argument("-f", "--format", choices=("json", "stdout"), default="json")
        sp.add_argument("-o", "--output", default=None, help="Output file (json) or directory for 'all'")

    sp = sub.add_parser("currencies"); add_common(sp); sp.set_defaults(func=cmd_currencies)
    sp = sub.add_parser("omens");      add_common(sp); sp.set_defaults(func=cmd_omens)
    sp = sub.add_parser("essences");   add_common(sp); sp.set_defaults(func=cmd_essences)

    sp = sub.add_parser("base-items")
    add_common(sp)
    sp.add_argument("slugs", nargs="*", help="One or more category slugs (default: common armour/weapon classes)")
    sp.set_defaults(func=cmd_base_items)

    sp = sub.add_parser("prices")
    add_common(sp)
    sp.add_argument("-l", "--league", default="Standard", help="League name, or 'C'/'Current' for the active league")
    sp.set_defaults(func=cmd_prices)

    sp = sub.add_parser("all")
    add_common(sp)
    sp.add_argument("-l", "--league", default="Standard", help="League name, or 'C'/'Current' for the active league")
    sp.set_defaults(func=cmd_all)

    return p

def main(argv: Optional[List[str]] = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        _setup_logging(args.v, args.log_file)
        args.func(args)
        return 0
    except SystemExit as e:
        return int(e.code)
    except Exception:
        LOG.exception("Command failed")
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
