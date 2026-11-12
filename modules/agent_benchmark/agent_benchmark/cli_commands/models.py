"""CLI definitions and handlers for model inventory inspection."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
import inspect
import json
import sys
from typing import Any

from termdash import Table

from ..models_lifecycle import (
    get_loaded_models,
    list_codex_models,
    list_downloaded_models,
    list_gemini_models,
)


def add_models_parser(actions: Any) -> None:
    """Add 'models' command parser."""
    models_p = actions.add_parser(
        "models", help="Inspect available model configurations",
        description="Inspect model configurations available from supported providers.",
        epilog="Examples:\n  agent-benchmark models list\n  agent-benchmark models list --provider lmstudio --format json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    models_actions = models_p.add_subparsers(dest="models_command")
    models_list = models_actions.add_parser(
        "list", help="List available models across LM Studio, Gemini (via agy), and Codex"
    )
    models_list.add_argument(
        "-p",
        "--provider",
        choices=("all", "lmstudio", "gemini", "codex"),
        default="all",
        help="Filter models by provider (default: all)",
    )
    models_list.add_argument("-u", "--base-url", default="http://127.0.0.1:1234")
    models_list.add_argument("--format", choices=("table", "json"), default="table")


def handle_models(args: argparse.Namespace) -> int:
    """Handle models inventory command."""
    cmd = getattr(args, "models_command", None) or "list"
    if cmd == "list":
        prov = getattr(args, "provider", "all") or "all"

        # Check for monkeypatched functions in cli module if present
        import agent_benchmark.cli as cli_mod

        fetch_downloaded = getattr(cli_mod, "list_downloaded_models", list_downloaded_models)
        fetch_loaded = getattr(cli_mod, "get_loaded_models", get_loaded_models)
        fetch_gemini = getattr(cli_mod, "list_gemini_models", list_gemini_models)
        fetch_codex = getattr(cli_mod, "list_codex_models", list_codex_models)

        async def _fetch():
            downloaded, loaded, gemini_list, codex_list = [], [], [], []
            if prov in ("all", "lmstudio"):
                try:
                    res_d = fetch_downloaded()
                    if inspect.isawaitable(res_d):
                        res_d = await res_d
                    downloaded = res_d
                except Exception:
                    if prov == "lmstudio":
                        raise
                try:
                    res_l = fetch_loaded()
                    if inspect.isawaitable(res_l):
                        res_l = await res_l
                    loaded = res_l
                except Exception:
                    loaded = []

            if prov in ("all", "gemini"):
                res_g = fetch_gemini()
                if inspect.isawaitable(res_g):
                    res_g = await res_g
                gemini_list = res_g

            if prov in ("all", "codex"):
                res_c = fetch_codex()
                if inspect.isawaitable(res_c):
                    res_c = await res_c
                codex_list = res_c

            return downloaded, loaded, gemini_list, codex_list

        try:
            needs = []
            if prov in ("all", "lmstudio"):
                needs.extend((fetch_downloaded, fetch_loaded))
            if prov in ("all", "gemini"):
                needs.append(fetch_gemini)
            if prov in ("all", "codex"):
                needs.append(fetch_codex)
            if not any(inspect.iscoroutinefunction(fn) for fn in needs):
                downloaded = fetch_downloaded() if prov in ("all", "lmstudio") else []
                loaded = fetch_loaded() if prov in ("all", "lmstudio") else []
                gemini_list = fetch_gemini() if prov in ("all", "gemini") else []
                codex_list = fetch_codex() if prov in ("all", "codex") else []
            else:
                downloaded, loaded, gemini_list, codex_list = asyncio.run(
                    _fetch(), loop_factory=asyncio.SelectorEventLoop
                )
        except Exception as exc:
            print(f"agent-bench: model discovery failed: {exc}", file=sys.stderr)
            return 1

        if args.format == "json":
            out = {
                "downloaded_models": [asdict(m) for m in downloaded],
                "loaded_models": [asdict(m) for m in loaded],
                "gemini_models": [asdict(m) for m in gemini_list],
                "codex_models": [asdict(m) for m in codex_list],
            }
            print(json.dumps(out, indent=2))
        else:
            if not downloaded and not gemini_list and not codex_list:
                print("No models found.")
                return 0
            tbl = Table(
                headers=["Model Key", "Architecture", "Quantization", "Status"],
                style="dash",
            )
            loaded_keys = {m.model_key for m in loaded}
            for m in downloaded:
                status_str = "LOADED (active)" if m.model_key in loaded_keys else "DOWNLOADED"
                tbl.add_row(
                    m.model_key,
                    m.architecture or "N/A",
                    m.quantization or "N/A",
                    status_str,
                )
            for m in gemini_list:
                tbl.add_row(
                    m.canonical_id,
                    m.architecture or "gemini",
                    "cloud-cli",
                    m.status,
                )
            for m in codex_list:
                tbl.add_row(
                    m.canonical_id,
                    m.architecture or "gpt",
                    "cloud-cli",
                    m.status,
                )
            print(tbl.render())
        return 0
    return 0
