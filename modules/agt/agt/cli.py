#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
from typing import Any, Dict, List, Optional, Tuple

from .agent import (
    build_prompt_with_attachments,
    expand_attachments,
    apply_tools,
    extract_reasoning,
)
from .client import WebAIClient
from .tui import TUI
from .tokens import count_messages_tokens, count_text_tokens


def _add_common(parser: argparse.ArgumentParser):
    parser.add_argument(
        "-u", "--url", default=None, help="Base URL (e.g., http://192.168.50.100:6969)"
    )
    parser.add_argument("-m", "--model", default=None, help="Model name")
    parser.add_argument("-p", "--provider", default=None, help="Provider (gpt4free)")
    parser.add_argument("-s", "--stream", action="store_true", help="Stream responses")
    parser.add_argument("-t", "--thinking", action="store_true", help="Show/stream 'thinking'")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose HTTP/debug logs")


def _build_parsers() -> Tuple[argparse.ArgumentParser, argparse.ArgumentParser]:
    root = argparse.ArgumentParser(
        prog="agt", description="agt – lightweight WebAI-to-API client", add_help=False
    )
    root.add_argument("-h", "--help", action="store_true", help="Show help and exit")
    _add_common(root)
    root.add_argument("-H", "--health", action="store_true", help="Check server health and exit")
    root.add_argument("-a", "--ask", metavar="TEXT", help="One-shot ask (supports @file/globs)")

    subs = root.add_subparsers(dest="cmd")
    gem = subs.add_parser("gemini", prog="agt gemini", description="Gemini subcommands", add_help=False)
    gem.add_argument("-h", "--help", action="store_true", help="Show help and exit")
    _add_common(gem)
    gem.add_argument("--list-models", action="store_true", help="List models and exit")
    gem.add_argument("--list-providers", action="store_true", help="List providers and exit")
    gem.add_argument("-a", "--ask", metavar="TEXT", help="One-shot ask for Gemini profile")
    gem.add_argument("-H", "--health", action="store_true", help="Check server health and exit")
    return root, gem


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    root, gem = _build_parsers()
    ns, extras = root.parse_known_args(argv)
    if ns.cmd == "gemini":
        g_ns = gem.parse_args([a for a in (argv or [])[1:]])
        for k, v in vars(g_ns).items():
            setattr(ns, k, v)
    return ns


def one_shot(
    client: WebAIClient,
    *,
    text: str,
    model: Optional[str],
    provider: Optional[str],
    stream: bool,
    thinking: bool,
    verbose: bool,
) -> int:
    messages: List[Dict[str, str]] = [
        {"role": "system", "content": "You are a helpful assistant. Return tool JSON when acting."}
    ]
    cleaned, atts = expand_attachments(text)
    messages.append({"role": "user", "content": build_prompt_with_attachments(cleaned, atts)})

    prompt_tokens = count_messages_tokens(messages, model)

    try:
        if verbose:
            print(f"[debug] one-shot -> url={client.base_url} model={model or client.model} provider={provider or client.provider}")
        if stream or thinking:
            agg: List[str] = []
            for evt in client.chat_stream_events(messages, model=model, provider=provider):  # type: ignore[arg-type]
                event = evt.get("event")
                if event == "content":
                    chunk = evt.get("text", "")
                    print(chunk, end="")
                    agg.append(chunk)
                elif event == "reasoning" and thinking:
                    print(evt.get("text", ""), end="")
                    agg.append(evt.get("text", ""))
                elif event == "usage":
                    u = evt.get("usage", {})
                    if "prompt_tokens" in u or "completion_tokens" in u:
                        print(f"\n[usage] prompt={u.get('prompt_tokens',0)} completion={u.get('completion_tokens',0)} total={u.get('total_tokens',0)}")
            print()
            content = "".join(agg)
            comp_tokens = count_text_tokens(content, model) if content else 0
            print(f"[tokens] prompt≈{prompt_tokens} completion≈{comp_tokens}")
            for outcome in apply_tools(content, ask=lambda *_: False):
                print(outcome)
            return 0
        resp = client.chat_once(messages, model=model, provider=provider, stream=False)  # type: ignore[arg-type]
        if thinking:
            rsn = extract_reasoning(resp) or ""
            if rsn:
                print(rsn)
        content = resp.get("choices", [{}])[0].get("message", {}).get("content", "")
        if content:
            print(content)
            for outcome in apply_tools(content, ask=lambda *_: False):
                print(outcome)
        else:
            print(json.dumps(resp, ensure_ascii=False, indent=2))
        usage = resp.get("usage", {})
        if usage:
            print(f"[usage] prompt={usage.get('prompt_tokens',0)} completion={usage.get('completion_tokens',0)} total={usage.get('total_tokens',0)}")
        else:
            comp_tokens = count_text_tokens(content, model) if content else 0
            print(f"[tokens] prompt≈{prompt_tokens} completion≈{comp_tokens}")
        return 0
    except Exception as e:
        print(f"Error: {e}")
        return 2


def main(argv: Optional[List[str]] = None) -> int:
    root_parser, gem_parser = _build_parsers()
    args = parse_args(argv)

    # Manual help (no SystemExit)
    if getattr(args, "help", False):
        if args.cmd == "gemini":
            print(gem_parser.format_help())
        else:
            print(root_parser.format_help())
        return 0

    client = WebAIClient(
        base_url=args.url,
        model=args.model,
        provider=args.provider,
        verbose=args.verbose,
    )

    if args.cmd == "gemini":
        if args.health:
            ok, detail = client.health_detail()
            print("OK" if ok else "DOWN")
            if args.verbose:
                print(f"[debug] health: {detail}")
            return 0 if ok else 1
        if getattr(args, "list_models", False):
            print(json.dumps(client.list_models(), ensure_ascii=False, indent=2))
            return 0
        if getattr(args, "list_providers", False):
            print(json.dumps(client.list_providers(), ensure_ascii=False, indent=2))
            return 0
        if args.ask:
            return one_shot(
                client,
                text=args.ask,
                model=args.model,
                provider=args.provider,
                stream=args.stream,
                thinking=args.thinking,
                verbose=args.verbose,
            )
        tui = TUI(client, model=args.model, provider=args.provider, stream=args.stream, thinking=args.thinking, verbose=args.verbose)
        tui.run()
        return 0

    if args.health:
        ok, detail = client.health_detail()
        print("OK" if ok else "DOWN")
        if args.verbose:
            print(f"[debug] health: {detail}")
        return 0 if ok else 1

    if args.ask:
        return one_shot(
            client,
            text=args.ask,
            model=args.model,
            provider=args.provider,
            stream=args.stream,
            thinking=args.thinking,
            verbose=args.verbose,
        )

    tui = TUI(client, model=args.model, provider=args.provider, stream=args.stream, thinking=args.thinking, verbose=args.verbose)
    tui.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

