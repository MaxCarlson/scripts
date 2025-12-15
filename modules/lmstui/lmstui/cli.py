from __future__ import annotations

import argparse
import sys
import time
from typing import Any, Dict, List

from lmstui.api import LmStudioApi
from lmstui.config import load_config
from lmstui.formatting import format_table, pretty_json
from lmstui.logs import LogStreamArgs, stream_logs_over_ssh
from lmstui.repl import ReplState, run_chat_repl


def _add_common_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "-b",
        "--base_url",
        default=None,
        help="LM Studio root base URL (e.g. http://192.168.56.1:1234). You may also pass /v1 or /api/v0.",
    )
    p.add_argument(
        "-t",
        "--timeout_seconds",
        default=None,
        type=float,
        help="HTTP timeout seconds (default: 60).",
    )


def cmd_server_ping(args: argparse.Namespace) -> int:
    cfg = load_config(args.base_url, args.timeout_seconds)
    api = LmStudioApi(cfg)
    mode, detail = api.ping()
    print(f"{mode}: {detail}")
    return 0


def cmd_server_endpoints(args: argparse.Namespace) -> int:
    cfg = load_config(args.base_url, args.timeout_seconds)
    api = LmStudioApi(cfg)
    print("REST API v0:")
    print(f"  {cfg.rest_base}/models")
    print(f"  {cfg.rest_base}/chat/completions")
    print(f"  {cfg.rest_base}/completions")
    print(f"  {cfg.rest_base}/embeddings")
    print("")
    print("OpenAI-compatible:")
    print(f"  {cfg.openai_base}/models")
    print(f"  {cfg.openai_base}/chat/completions")
    print(f"  {cfg.openai_base}/responses")
    print(f"  {cfg.openai_base}/embeddings")
    return 0


def cmd_models_list(args: argparse.Namespace) -> int:
    cfg = load_config(args.base_url, args.timeout_seconds)
    api = LmStudioApi(cfg)

    rows: List[Dict[str, Any]] = []
    try:
        models = api.list_models_rest()
        for m in models:
            rows.append(
                {
                    "id": m.id,
                    "state": m.state or "",
                    "type": m.type or "",
                    "ctx": m.max_context_length or "",
                    "quant": m.quantization or "",
                }
            )
        print(
            format_table(
                rows,
                columns=[
                    ("id", "id"),
                    ("state", "state"),
                    ("type", "type"),
                    ("ctx", "max_ctx"),
                    ("quant", "quant"),
                ],
            )
        )
        return 0
    except Exception:
        pass

    models2 = api.list_models_openai()
    for m in models2:
        rows.append({"id": m.id})
    print(format_table(rows, columns=[("id", "id")]))
    return 0


def cmd_models_info(args: argparse.Namespace) -> int:
    cfg = load_config(args.base_url, args.timeout_seconds)
    api = LmStudioApi(cfg)
    obj = api.get_model_rest(args.model_id)
    print(pretty_json(obj))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    cfg = load_config(args.base_url, args.timeout_seconds)
    api = LmStudioApi(cfg)

    messages: List[Dict[str, str]] = []
    if args.system:
        messages.append({"role": "system", "content": args.system})
    messages.append({"role": "user", "content": args.prompt})

    if args.stream:
        lines = api.chat_rest(
            model=args.model,
            messages=messages,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            stream=True,
        )
        sys.stdout.write("assistant> ")
        sys.stdout.flush()
        buf: List[str] = []
        for piece in api.iter_stream_text_from_lines(lines):
            buf.append(piece)
            sys.stdout.write(piece)
            sys.stdout.flush()
        sys.stdout.write("\n")
        return 0

    resp = api.chat_rest(
        model=args.model,
        messages=messages,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        stream=False,
    )
    print(pretty_json(resp))
    return 0


def cmd_chat(args: argparse.Namespace) -> int:
    cfg = load_config(args.base_url, args.timeout_seconds)
    api = LmStudioApi(cfg)
    state = ReplState(
        model=args.model,
        system=args.system,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        stream=bool(args.stream),
    )
    return run_chat_repl(api, state)


def cmd_embeddings(args: argparse.Namespace) -> int:
    cfg = load_config(args.base_url, args.timeout_seconds)
    api = LmStudioApi(cfg)
    resp = api.embeddings_rest(model=args.model, text=args.text)
    if args.pretty:
        print(pretty_json(resp))
        return 0

    data = (resp or {}).get("data", [])
    if not data:
        print(pretty_json(resp))
        return 0
    emb = data[0].get("embedding", [])
    print(f"embedding_len={len(emb)}")
    print(f"first_8={emb[:8]}")
    return 0


def cmd_logs_ssh(args: argparse.Namespace) -> int:
    log_args = LogStreamArgs(
        source=args.source,
        stats=bool(args.stats),
        filter=args.filter,
        json=bool(args.json),
    )
    for line in stream_logs_over_ssh(args.ssh, log_args):
        print(line)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="lmstui", description="LM Studio Termux-friendly CLI/TUI")
    _add_common_flags(p)

    sub = p.add_subparsers(dest="cmd", required=True)

    sp_server = sub.add_parser("server", help="Server helpers")
    _add_common_flags(sp_server)
    sub_server = sp_server.add_subparsers(dest="server_cmd", required=True)

    sp_ping = sub_server.add_parser("ping", help="Health check (REST preferred, then OpenAI)")
    sp_ping.set_defaults(func=cmd_server_ping)

    sp_endpoints = sub_server.add_parser("endpoints", help="Print useful endpoint URLs")
    sp_endpoints.set_defaults(func=cmd_server_endpoints)

    sp_models = sub.add_parser("models", help="Model helpers")
    _add_common_flags(sp_models)
    sub_models = sp_models.add_subparsers(dest="models_cmd", required=True)

    sp_list = sub_models.add_parser("list", help="List models (REST preferred)")
    sp_list.set_defaults(func=cmd_models_list)

    sp_info = sub_models.add_parser("info", help="Show model info (REST)")
    sp_info.add_argument("-m", "--model_id", required=True, help="Model id")
    sp_info.set_defaults(func=cmd_models_info)

    sp_run = sub.add_parser("run", help="One-shot chat request")
    _add_common_flags(sp_run)
    sp_run.add_argument("-m", "--model", required=True, help="Model id")
    sp_run.add_argument("-p", "--prompt", required=True, help="User prompt")
    sp_run.add_argument("-s", "--system", default=None, help="System prompt")
    sp_run.add_argument("-T", "--temperature", default=0.7, type=float, help="Temperature")
    sp_run.add_argument("-k", "--max_tokens", default=-1, type=int, help="Max tokens (-1 = unlimited)")
    sp_run.add_argument("-S", "--stream", action="store_true", help="Stream output")
    sp_run.set_defaults(func=cmd_run)

    sp_chat = sub.add_parser("chat", help="Interactive chat REPL")
    _add_common_flags(sp_chat)
    sp_chat.add_argument("-m", "--model", required=True, help="Model id")
    sp_chat.add_argument("-s", "--system", default=None, help="System prompt")
    sp_chat.add_argument("-T", "--temperature", default=0.7, type=float, help="Temperature")
    sp_chat.add_argument("-k", "--max_tokens", default=-1, type=int, help="Max tokens (-1 = unlimited)")
    sp_chat.add_argument("-S", "--stream", action="store_true", help="Stream output (recommended)")
    sp_chat.set_defaults(func=cmd_chat)

    sp_emb = sub.add_parser("embeddings", help="Create embeddings (REST)")
    _add_common_flags(sp_emb)
    sp_emb.add_argument("-m", "--model", required=True, help="Embedding model id")
    sp_emb.add_argument("-x", "--text", required=True, help="Text to embed")
    sp_emb.add_argument("-P", "--pretty", action="store_true", help="Pretty-print full JSON response")
    sp_emb.set_defaults(func=cmd_embeddings)

    sp_logs = sub.add_parser("logs", help="Log helpers (via SSH)")
    sub_logs_sub = sp_logs.add_subparsers(dest="logs_cmd", required=True)

    sp_ssh = sub_logs_sub.add_parser("ssh", help="Stream LM Studio logs over SSH using `lms log stream`")
    sp_ssh.add_argument("-c", "--ssh", required=True, help="SSH target, e.g. user@192.168.56.1")
    sp_ssh.add_argument(
        "-s",
        "--source",
        default="model",
        choices=["model", "server"],
        help="Log source: model or server",
    )
    sp_ssh.add_argument("--stats", action="store_true", help="Include prediction stats when available")
    sp_ssh.add_argument("--json", action="store_true", help="Emit JSON logs (newline separated)")
    sp_ssh.add_argument("--filter", default=None, help="For model logs: input, output, or input,output")
    sp_ssh.set_defaults(func=cmd_logs_ssh)

    return p


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))
