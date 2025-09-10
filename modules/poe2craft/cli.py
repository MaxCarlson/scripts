#!/usr/bin/env python3
"""
poe2craft CLI

- Progress/logs -> STDERR only (clean JSON on STDOUT).
- `-C/--current` resolves active PoE2 league automatically (prices).
- `all` runs {currencies, omens, essences, base-items, prices}.
  * --format stdout   -> one JSON object with keys: currencies, omens, essences, base_items, prices
  * --format json -o DIR -> writes files in DIR:
        currencies.json, omens.json, essences.json, base-items.json, prices.json
- Verbose logging via -v (repeatable) and optional --log-file.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

# Allow running directly (without package install)
if __package__ is None and __name__ == "__main__":
    sys.path.append(str(Path(__file__).resolve().parent.parent))

# ---- imports with safe fallback for DEFAULT_BASE_SLUGS
from poe2craft.datasources.poe2db_client import Poe2DBClient  # type: ignore
try:
    from poe2craft.datasources.poe2db_client import DEFAULT_BASE_SLUGS  # type: ignore
except Exception:
    DEFAULT_BASE_SLUGS = ["Bows", "Boots", "Gloves", "Helmets", "Body_Armours", "Quivers"]

from poe2craft.datasources.poeninja_prices import PoENinjaPriceProvider  # type: ignore

LOG = logging.getLogger("poe2craft.cli")

# ---------- logging & progress ----------

def _setup_logging(verbosity: int, log_file: Optional[str]) -> None:
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
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )

def _progress(label: str, current: int, total: int, extra: str = "") -> None:
    pct = (current / total * 100.0) if total else 0.0
    msg = f"[{label}] {current}/{total} {pct:5.1f}%"
    if extra:
        msg += f" | {extra}"
    print(msg, file=sys.stderr)

# ---------- JSON helpers ----------

def _json_default(o: Any) -> Any:
    if is_dataclass(o):
        return asdict(o)
    if isinstance(o, Enum):
        return getattr(o, "name", o.value)
    if hasattr(o, "to_dict") and callable(getattr(o, "to_dict")):
        try:
            return o.to_dict()
        except Exception:
            pass
    if hasattr(o, "__dict__"):
        try:
            return dict(o.__dict__)
        except Exception:
            pass
    return str(o)

def _stdout_json(obj: Any) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=_json_default))

def _save_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, default=_json_default)
    LOG.info("Wrote %s (%d bytes)", str(path), path.stat().st_size)

# ---------- fetch helpers ----------

def _fetch_currencies(client: Poe2DBClient) -> List[dict]:
    fn = getattr(client, "fetch_stackable_currency", None) or getattr(client, "fetch_currencies", None)
    if not fn:
        LOG.error("No currency fetcher found on Poe2DBClient.")
        return []
    out = fn()
    _progress("Currencies", 1, 1, f"parsed {len(out)}")
    return out

def _fetch_omens(client: Poe2DBClient) -> List[dict]:
    out = client.fetch_omens()
    _progress("Omens", 1, 1, f"parsed {len(out)}")
    return out

def _fetch_essences(client: Poe2DBClient) -> List[dict]:
    out = client.fetch_essences()
    _progress("Essences", 1, 1, f"parsed {len(out)}")
    return out

def _fetch_base_items(client: Poe2DBClient, slugs: Iterable[str]) -> List[dict]:
    slugs = list(slugs) if slugs else DEFAULT_BASE_SLUGS
    all_items: List[dict] = []
    total = len(slugs)
    for i, slug in enumerate(slugs, start=1):
        items = client.fetch_base_items(slug)
        all_items.extend(items)
        _progress("Base Items (slugs)", i, total, f"{slug} -> {len(items)} items")
    return all_items

def _fetch_prices(provider: PoENinjaPriceProvider, league_arg: Optional[str], use_current_flag: bool) -> Dict[str, float]:
    league = "Standard"

    # treat -l C or --league C as "current" too
    if league_arg and league_arg.strip().lower() in {"c", "current"}:
        use_current_flag = True

    if use_current_flag:
        detected = provider.detect_current_league()
        if detected:
            league = detected
            LOG.info("Using current league detected: %s", league)
        else:
            LOG.warning("Could not detect current league; falling back to Standard")
    elif league_arg:
        league = league_arg

    prices = provider.get_currency_prices(league=league)
    _progress(f"Prices [{league}]", 1, 1, f"{len(prices)} entries")
    return prices

# ---------- argparse + handlers ----------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="poe2craft", description="Path of Exile 2 data scraper/CLI")
    p.add_argument("-v", action="count", default=0, help="Increase verbosity (repeat for more)")
    p.add_argument("--log-file", default=None, help="Write logs to this file (in addition to STDERR)")

    sub = p.add_subparsers(dest="cmd", required=True)

    # currencies
    sp = sub.add_parser("currencies", help="Fetch stackable currencies")
    sp.add_argument("-f", "--format", choices=["stdout", "json"], default="stdout")
    sp.add_argument("-o", "--output", default=None, help="Output file when --format json")
    sp.set_defaults(handler=cmd_currencies)

    # omens
    sp = sub.add_parser("omens", help="Fetch omens")
    sp.add_argument("-f", "--format", choices=["stdout", "json"], default="stdout")
    sp.add_argument("-o", "--output", default=None, help="Output file when --format json")
    sp.set_defaults(handler=cmd_omens)

    # essences
    sp = sub.add_parser("essences", help="Fetch essences")
    sp.add_argument("-f", "--format", choices=["stdout", "json"], default="stdout")
    sp.add_argument("-o", "--output", default=None, help="Output file when --format json")
    sp.set_defaults(handler=cmd_essences)

    # base-items
    sp = sub.add_parser("base-items", help="Fetch base items for one or more slugs")
    sp.add_argument("slugs", nargs="*", help="Item class slugs (default: curated set)")
    sp.add_argument("-f", "--format", choices=["stdout", "json"], default="stdout")
    sp.add_argument("-o", "--output", default=None, help="Output file when --format json")
    sp.set_defaults(handler=cmd_base_items)

    # prices
    sp = sub.add_parser("prices", help="Fetch poe.ninja currency prices for PoE2")
    sp.add_argument("-l", "--league", default="Standard", help="League name (use -C or -l C for active league)")
    sp.add_argument("-C", "--current", action="store_true", help="Use currently active league")
    sp.add_argument("-f", "--format", choices=["stdout", "json"], default="stdout")
    sp.add_argument("-o", "--output", default=None, help="Output file when --format json")
    sp.set_defaults(handler=cmd_prices)

    # all
    sp = sub.add_parser("all", help="Run currencies, omens, essences, base-items, prices")
    sp.add_argument("-l", "--league", default="Standard", help="League name for prices (use -C or -l C for active league)")
    sp.add_argument("-C", "--current", action="store_true", help="Use currently active league (prices)")
    sp.add_argument("-f", "--format", choices=["stdout", "json"], default="stdout",
                    help="stdout = single JSON object; json = write individual files")
    sp.add_argument("-o", "--output", default=None,
                    help="When --format json: directory (or any path whose parent will be used) to write files into")
    sp.add_argument("--base-slugs", nargs="*", default=None,
                    help="Custom slugs for base-items; defaults to curated set")
    sp.set_defaults(handler=cmd_all)

    return p

def cmd_currencies(args: argparse.Namespace) -> int:
    client = Poe2DBClient()
    data = _fetch_currencies(client)
    if args.format == "stdout":
        _stdout_json(data)
    else:
        if not args.output:
            print("ERROR: --output required with --format json", file=sys.stderr)
            return 2
        _save_json(Path(args.output), data)
    return 0

def cmd_omens(args: argparse.Namespace) -> int:
    client = Poe2DBClient()
    data = _fetch_omens(client)
    if args.format == "stdout":
        _stdout_json(data)
    else:
        if not args.output:
            print("ERROR: --output required with --format json", file=sys.stderr)
            return 2
        _save_json(Path(args.output), data)
    return 0

def cmd_essences(args: argparse.Namespace) -> int:
    client = Poe2DBClient()
    data = _fetch_essences(client)
    if args.format == "stdout":
        _stdout_json(data)
    else:
        if not args.output:
            print("ERROR: --output required with --format json", file=sys.stderr)
            return 2
        _save_json(Path(args.output), data)
    return 0

def cmd_base_items(args: argparse.Namespace) -> int:
    client = Poe2DBClient()
    slugs = args.slugs if args.slugs else DEFAULT_BASE_SLUGS
    data = _fetch_base_items(client, slugs)
    if args.format == "stdout":
        _stdout_json(data)
    else:
        if not args.output:
            print("ERROR: --output required with --format json", file=sys.stderr)
            return 2
        _save_json(Path(args.output), data)
    return 0

def cmd_prices(args: argparse.Namespace) -> int:
    provider = PoENinjaPriceProvider()
    data = _fetch_prices(provider, args.league, args.current)
    if args.format == "stdout":
        _stdout_json(data)
    else:
        if not args.output:
            print("ERROR: --output required with --format json", file=sys.stderr)
            return 2
        _save_json(Path(args.output), data)
    return 0

def cmd_all(args: argparse.Namespace) -> int:
    client = Poe2DBClient()
    provider = PoENinjaPriceProvider()

    base_slugs = args.base_slugs if args.base_slugs else DEFAULT_BASE_SLUGS

    currencies = _fetch_currencies(client)
    omens = _fetch_omens(client)
    essences = _fetch_essences(client)
    base_items = _fetch_base_items(client, base_slugs)
    prices = _fetch_prices(provider, args.league, args.current)

    if args.format == "stdout":
        bundle = {
            "currencies": currencies,
            "omens": omens,
            "essences": essences,
            "base_items": base_items,
            "prices": prices,
        }
        _stdout_json(bundle)
        return 0

    # --format json: write individual files
    outdir: Path
    if not args.output:
        outdir = Path(".")
    else:
        outpath = Path(args.output)
        outdir = outpath if outpath.is_dir() else outpath.parent

    files = {
        "currencies.json": currencies,
        "omens.json": omens,
        "essences.json": essences,
        "base-items.json": base_items,
        "prices.json": prices,
    }
    for fname, payload in files.items():
        _save_json(outdir / fname, payload)

    # Summary to STDERR
    for fname in files.keys():
        f = outdir / fname
        try:
            size = f.stat().st_size
        except Exception:
            size = 0
        print(f"{size:>6}  -I  {fname}", file=sys.stderr)

    return 0

def main_cli(argv: Optional[List[str]] = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.v, args.log_file)
    try:
        return args.handler(args)
    except Exception as e:
        LOG.exception("Command failed: %s", e)
        return 2

# tests and older console-scripts may import `main`
def main(argv: Optional[List[str]] = None) -> int:  # noqa: D401
    """Backward-compatible entrypoint used by tests and old wrappers."""
    return main_cli(argv)

if __name__ == "__main__":
    raise SystemExit(main_cli())
