from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any, Dict, List, Optional

from lmstui.api import LMStudioAPI
from lmstui.config import load_config
from lmstui.defaults import (
    clear_defaults,
    get_effective_defaults,
    load_defaults,
    parse_default_val,
    set_default,
)
from lmstui.formatting import format_table, pretty_json, safe_get
from lmstui.logs import LogStreamArgs, stream_logs_over_ssh
from lmstui.repl import ReplState, run_chat_repl
from lmstui.sse import (
    extract_delta_text,
    extract_usage_from_chunk,
)


def _eprint(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _print_stats(
    usage: Optional[Dict[str, Any]],
    duration: float,
    stats: Optional[Dict[str, Any]] = None,
) -> None:
    parts = ["[stats]"]
    if usage:
        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")
        reasoning_tokens = safe_get(usage, "completion_tokens_details", "reasoning_tokens")
        if reasoning_tokens is None:
            reasoning_tokens = usage.get("reasoning_tokens")
        total_tokens = usage.get("total_tokens")

        if prompt_tokens is not None:
            parts.append(f"  Prompt tokens:     {prompt_tokens}")
        if completion_tokens is not None:
            parts.append(f"  Completion tokens: {completion_tokens}")
        if reasoning_tokens is not None:
            parts.append(f"  Reasoning tokens:  {reasoning_tokens}")
        if total_tokens is not None:
            parts.append(f"  Total tokens:      {total_tokens}")

    parts.append(f"  Duration:          {duration:.2f}s")

    tps = None
    ttft = None
    if stats:
        tps = stats.get("tokens_per_second") or stats.get("tps")
        ttft = stats.get("time_to_first_token") or stats.get("ttft")

    if tps is not None:
        parts.append(f"  Tokens/sec:        {tps:.2f}")
    elif usage and usage.get("completion_tokens") and duration > 0:
        calc_tps = usage["completion_tokens"] / duration
        parts.append(f"  Tokens/sec:        {calc_tps:.2f}")

    if ttft is not None:
        parts.append(f"  Time to first:     {ttft:.2f}s")

    _eprint("\n".join(parts))


def _handle_defaults_flags(args: argparse.Namespace) -> bool:
    """
    Handle -D/--set-default, -d/--show-defaults, -C/--clear-defaults.
    Returns True if a defaults action was performed and CLI should exit.
    """
    model_scope = getattr(args, "model", None) if getattr(args, "per_model", False) else None

    if getattr(args, "show_defaults", False):
        data = load_defaults()
        has_any = bool(data.get("global") or data.get("models"))
        if not has_any:
            print("No custom defaults configured.")
            return True

        if data.get("global"):
            print("Global Defaults:")
            for k, v in sorted(data["global"].items()):
                print(f"  {k}: {v}")
        if data.get("models"):
            print("Model-Specific Defaults:")
            for m, m_vals in sorted(data["models"].items()):
                print(f"  [{m}]")
                for k, v in sorted(m_vals.items()):
                    print(f"    {k}: {v}")
        return True

    if getattr(args, "clear_defaults", False):
        if model_scope:
            clear_defaults(model=model_scope)
            print(f"Cleared defaults for model '{model_scope}'.")
        else:
            clear_defaults()
            print("Cleared all custom defaults.")
        return True

    if getattr(args, "set_default", None):
        for item in args.set_default:
            if "=" not in item:
                _eprint(f"Error: Invalid default setting '{item}'. Expected KEY=VALUE.")
                sys.exit(1)
            k, v = item.split("=", 1)
            k = k.strip()
            val = parse_default_val(v)
            if model_scope:
                set_default(k, val, model=model_scope)
                print(f"Set default for [{model_scope}] {k} = {val}")
            else:
                set_default(k, val)
                print(f"Set global default {k} = {val}")
        return True

    return False


def _parse_kv_pairs(pairs: Optional[List[str]]) -> Optional[Dict[str, Any]]:
    if not pairs:
        return None
    out: Dict[str, Any] = {}
    for item in pairs:
        if "=" not in item:
            raise ValueError(f"Invalid extra pair '{item}'. Expected key=value.")
        k, v = item.split("=", 1)
        k = k.strip()
        v = v.strip()
        try:
            out[k] = json.loads(v)
        except Exception:
            out[k] = v
    return out


# ==============================================================================
# lmst subcommands
# ==============================================================================


def cmd_lmst_models(args: argparse.Namespace) -> int:
    api = LMStudioAPI(target=args.base_url, timeout_seconds=args.timeout, api_key=args.api_key)
    try:
        data = api.list_models()
    except Exception as e:
        _eprint(f"Error connecting to LM Studio: {e}")
        return 1

    if args.json:
        print(pretty_json(data))
        return 0

    models = data.get("data", [])
    if not isinstance(models, list) or not models:
        print("No models found.")
        return 0

    for m in models:
        if isinstance(m, dict):
            mid = m.get("id", "")
            state = m.get("state")
            extra = f" [{state}]" if state else ""
            print(f"{mid}{extra}")
    return 0


def cmd_lmst_chat(args: argparse.Namespace) -> int:
    if _handle_defaults_flags(args):
        return 0

    api = LMStudioAPI(target=args.base_url, timeout_seconds=args.timeout, api_key=args.api_key)

    # Resolve model
    try:
        model, warning, model_info = api.resolve_model(explicit_model=args.model)
    except Exception as e:
        _eprint(f"Error: {e}")
        return 1

    # Load effective defaults (global + model-specific)
    eff = get_effective_defaults(model=model)

    silent = args.silent if args.silent else bool(eff.get("silent", False))

    if warning and not silent:
        _eprint(warning)

    if not silent and model_info:
        ctx = model_info.get("max_context_length")
        m_type = model_info.get("type", "llm")
        info_str = f"type: {m_type}" + (f", max_ctx: {ctx}" if ctx else "")
        _eprint(f"[lmst] Using model: {model} ({info_str})")

    # Resolve settings with defaults fallback
    system = args.system_prompt or eff.get("system_prompt") or eff.get("system")
    temperature = args.temperature if args.temperature is not None else float(eff.get("temperature", 0.7))
    max_tokens = args.max_tokens if args.max_tokens is not None else eff.get("max_tokens")
    stream = args.stream if args.stream is not None else bool(eff.get("stream", True))
    stats = args.stats if args.stats else bool(eff.get("stats", False))
    as_json = args.json if args.json else bool(eff.get("json", False))

    # Check for prompt
    prompt = args.prompt
    if not prompt and not sys.stdin.isatty():
        prompt = sys.stdin.read().strip()

    # If no prompt provided and stdin is tty -> run interactive REPL!
    if not prompt:
        state = ReplState(
            model=model,
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=stream,
            stats=stats,
            silent=silent,
        )
        return run_chat_repl(api, state)

    # One-shot chat request
    messages: List[Dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    extra = _parse_kv_pairs(args.extra) if args.extra else None

    t0 = time.time()

    if stream and not as_json:
        buf: List[str] = []
        last_usage: Optional[Dict[str, Any]] = None
        try:
            gen = api.chat_completions(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
                extra=extra,
            )
            for chunk in gen:
                delta = extract_delta_text(chunk)
                if delta:
                    buf.append(delta)
                    sys.stdout.write(delta)
                    sys.stdout.flush()
                u = extract_usage_from_chunk(chunk)
                if u:
                    last_usage = u
        except KeyboardInterrupt:
            _eprint("\n^C (interrupted)")
            return 130
        except Exception as e:
            _eprint(f"Error during request: {e}")
            return 1

        if args.newline:
            sys.stdout.write("\n")
            sys.stdout.flush()

        t1 = time.time()
        final_text = "".join(buf)
        if args.output_file:
            with open(args.output_file, "w", encoding="utf-8") as f:
                f.write(final_text)

        if stats:
            if not final_text.endswith("\n") and not args.newline:
                _eprint("")
            _print_stats(last_usage, t1 - t0)
        return 0

    # Non-stream or JSON output
    try:
        resp = api.chat_completions(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=False,
            extra=extra,
        )
    except Exception as e:
        _eprint(f"Error: {e}")
        return 1

    t1 = time.time()
    assert isinstance(resp, dict)

    if as_json:
        print(pretty_json(resp))
        if stats:
            _print_stats(resp.get("usage"), t1 - t0, resp.get("stats"))
        return 0

    content = safe_get(resp, "choices", default=[{}])[0].get("message", {}).get("content", "")
    print(content)

    if args.output_file:
        with open(args.output_file, "w", encoding="utf-8") as f:
            f.write(content)

    if stats:
        _print_stats(resp.get("usage"), t1 - t0, resp.get("stats"))

    return 0


def cmd_lmst_responses(args: argparse.Namespace) -> int:
    if _handle_defaults_flags(args):
        return 0

    api = LMStudioAPI(target=args.base_url, timeout_seconds=args.timeout, api_key=args.api_key)

    try:
        model, warning, model_info = api.resolve_model(explicit_model=args.model)
    except Exception as e:
        _eprint(f"Error: {e}")
        return 1

    eff = get_effective_defaults(model=model)
    silent = args.silent if args.silent else bool(eff.get("silent", False))

    if warning and not silent:
        _eprint(warning)

    temperature = args.temperature if args.temperature is not None else float(eff.get("temperature", 0.7))
    max_tokens = args.max_output_tokens if args.max_output_tokens is not None else eff.get("max_tokens")
    stream = args.stream if args.stream is not None else bool(eff.get("stream", True))
    stats = args.stats if args.stats else bool(eff.get("stats", False))
    as_json = args.json if args.json else bool(eff.get("json", False))

    prompt = args.prompt
    if not prompt and not sys.stdin.isatty():
        prompt = sys.stdin.read().strip()
    if not prompt:
        _eprint("Error: No prompt provided. Use -p/--prompt or pipe text via stdin.")
        return 1

    extra = _parse_kv_pairs(args.extra) if args.extra else None
    t0 = time.time()

    if stream and not as_json:
        buf: List[str] = []
        last_usage: Optional[Dict[str, Any]] = None
        try:
            gen = api.responses(
                model=model,
                input_text=prompt,
                temperature=temperature,
                max_output_tokens=max_tokens,
                stream=True,
                extra=extra,
            )
            for chunk in gen:
                delta = extract_delta_text(chunk)
                if delta:
                    buf.append(delta)
                    sys.stdout.write(delta)
                    sys.stdout.flush()
                u = extract_usage_from_chunk(chunk)
                if u:
                    last_usage = u
        except KeyboardInterrupt:
            _eprint("\n^C (interrupted)")
            return 130
        except Exception as e:
            _eprint(f"Error during responses streaming: {e}")
            return 1

        if args.newline:
            sys.stdout.write("\n")
            sys.stdout.flush()

        t1 = time.time()
        final_text = "".join(buf)
        if args.output_file:
            with open(args.output_file, "w", encoding="utf-8") as f:
                f.write(final_text)

        if stats:
            _print_stats(last_usage, t1 - t0)
        return 0

    try:
        resp = api.responses(
            model=model,
            input_text=prompt,
            temperature=temperature,
            max_output_tokens=max_tokens,
            stream=False,
            extra=extra,
        )
    except Exception as e:
        _eprint(f"Error: {e}")
        return 1

    t1 = time.time()
    assert isinstance(resp, dict)

    if as_json:
        print(pretty_json(resp))
        if stats:
            _print_stats(resp.get("usage"), t1 - t0, resp.get("stats"))
        return 0

    text = safe_get(resp, "output", default=[{}])[0].get("content", [{}])[0].get("text", "")
    if not text:
        text = resp.get("text", "")
    print(text)

    if args.output_file:
        with open(args.output_file, "w", encoding="utf-8") as f:
            f.write(text)

    if stats:
        _print_stats(resp.get("usage"), t1 - t0, resp.get("stats"))

    return 0


# ==============================================================================
# lmstui subcommands (backward compatibility)
# ==============================================================================


def cmd_lmstui_server_ping(args: argparse.Namespace) -> int:
    cfg = load_config(getattr(args, "base_url", None), getattr(args, "timeout_seconds", None))
    api = LMStudioAPI(cfg)
    mode, detail = api.ping()
    print(f"{mode}: {detail}")
    return 0 if mode == "online" else 1


def cmd_lmstui_server_endpoints(args: argparse.Namespace) -> int:
    cfg = load_config(getattr(args, "base_url", None), getattr(args, "timeout_seconds", None))
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


def cmd_lmstui_models_list(args: argparse.Namespace) -> int:
    cfg = load_config(getattr(args, "base_url", None), getattr(args, "timeout_seconds", None))
    api = LMStudioAPI(cfg)
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


def cmd_lmstui_models_info(args: argparse.Namespace) -> int:
    cfg = load_config(getattr(args, "base_url", None), getattr(args, "timeout_seconds", None))
    api = LMStudioAPI(cfg)
    obj = api.get_model_rest(args.model_id)
    print(pretty_json(obj))
    return 0


def cmd_lmstui_run(args: argparse.Namespace) -> int:
    cfg = load_config(getattr(args, "base_url", None), getattr(args, "timeout_seconds", None))
    api = LMStudioAPI(cfg)
    model = args.model
    if not model:
        model, _, _ = api.resolve_model()
    messages: List[Dict[str, str]] = []
    if args.system:
        messages.append({"role": "system", "content": args.system})
    messages.append({"role": "user", "content": args.prompt})

    if args.stream:
        lines = api.chat_rest(
            model=model,
            messages=messages,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            stream=True,
        )
        sys.stdout.write("assistant> ")
        sys.stdout.flush()
        for piece in api.iter_stream_text_from_lines(lines):
            sys.stdout.write(piece)
            sys.stdout.flush()
        sys.stdout.write("\n")
        return 0

    resp = api.chat_rest(
        model=model,
        messages=messages,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        stream=False,
    )
    print(pretty_json(resp))
    return 0


def cmd_lmstui_chat(args: argparse.Namespace) -> int:
    cfg = load_config(getattr(args, "base_url", None), getattr(args, "timeout_seconds", None))
    api = LMStudioAPI(cfg)
    model = args.model
    if not model:
        model, _, _ = api.resolve_model()
    state = ReplState(
        model=model,
        system=args.system,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        stream=bool(args.stream),
    )
    return run_chat_repl(api, state)


def cmd_lmstui_embeddings(args: argparse.Namespace) -> int:
    cfg = load_config(getattr(args, "base_url", None), getattr(args, "timeout_seconds", None))
    api = LMStudioAPI(cfg)
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


def cmd_lmstui_logs_ssh(args: argparse.Namespace) -> int:
    log_args = LogStreamArgs(
        source=args.source,
        stats=bool(args.stats),
        filter=args.filter,
        json=bool(args.json),
    )
    for line in stream_logs_over_ssh(args.ssh, log_args):
        print(line)
    return 0


# ==============================================================================
# Parsers
# ==============================================================================


def _add_lmst_common_flags(p: argparse.ArgumentParser, is_subparser: bool = False) -> None:
    p.add_argument(
        "-b",
        "--base-url",
        default=argparse.SUPPRESS if is_subparser else "http://127.0.0.1:1234",
        help="Base URL for LM Studio (default: http://127.0.0.1:1234).",
    )
    p.add_argument(
        "-t",
        "--timeout",
        default=argparse.SUPPRESS if is_subparser else 60.0,
        type=float,
        help="HTTP request timeout in seconds (default: 60.0).",
    )
    p.add_argument(
        "-k",
        "--api-key",
        default=argparse.SUPPRESS if is_subparser else None,
        help="Optional API key / Bearer token.",
    )
    p.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        default=argparse.SUPPRESS if is_subparser else False,
        help="Enable verbose output.",
    )


def _add_lmst_defaults_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "-D",
        "--set-default",
        action="append",
        metavar="KEY=VAL",
        help="Set default configuration option (e.g. -D stream=true, -D temperature=0.5).",
    )
    p.add_argument(
        "-d",
        "--show-defaults",
        action="store_true",
        help="Print current persistent default configuration.",
    )
    p.add_argument(
        "-C",
        "--clear-defaults",
        action="store_true",
        help="Clear persistent defaults to initial factory defaults.",
    )
    p.add_argument(
        "-M",
        "--per-model",
        action="store_true",
        help="Apply -D/--set-default or -C/--clear-defaults specifically to the model set via -m/--model.",
    )


def build_parser_lmst() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="lmst",
        description="LM Studio direct console client (models, one-shot chat, interactive REPL).",
    )
    _add_lmst_common_flags(p, is_subparser=False)

    sub = p.add_subparsers(dest="command")

    # models
    pm = sub.add_parser("models", help="List available LM Studio models.")
    _add_lmst_common_flags(pm, is_subparser=True)
    pm.add_argument("-j", "--json", action="store_true", help="Print raw JSON output.")
    pm.set_defaults(func=cmd_lmst_models)

    # chat
    pc = sub.add_parser("chat", help="Chat with loaded model (interactive or one-shot).")
    _add_lmst_common_flags(pc, is_subparser=True)
    _add_lmst_defaults_flags(pc)
    pc.add_argument("-m", "--model", default=None, help="Model ID (auto-selects loaded model if omitted).")
    pc.add_argument("-p", "--prompt", default=None, help="User prompt. If omitted, reads stdin or starts REPL.")
    pc.add_argument("-s", "--system-prompt", default=None, help="System prompt.")
    pc.add_argument("-T", "--temperature", type=float, default=None, help="Sampling temperature.")
    pc.add_argument("-n", "--max-tokens", type=int, default=None, help="Maximum completion tokens.")
    pc.add_argument("-r", "--stream", dest="stream", action="store_true", default=None, help="Stream tokens live.")
    pc.add_argument("-N", "--no-stream", dest="stream", action="store_false", help="Disable streaming output.")
    pc.add_argument("-S", "--silent", action="store_true", help="Suppress model info and warning notices on stderr.")
    pc.add_argument("-a", "--stats", action="store_true", help="Print token counts, reasoning tokens, and speed to stderr.")
    pc.add_argument("-j", "--json", action="store_true", help="Output full API response as JSON to stdout.")
    pc.add_argument("-o", "--output-file", default=None, help="Save final text response to file.")
    pc.add_argument("-l", "--newline", action="store_true", help="Print trailing newline after streaming.")
    pc.add_argument(
        "-x",
        "--extra",
        nargs="*",
        default=None,
        metavar="K=V",
        help="Extra JSON key=value pairs for API payload.",
    )
    pc.set_defaults(func=cmd_lmst_chat)

    # responses
    pr = sub.add_parser("responses", help="OpenAI-compatible responses endpoint (/v1/responses).")
    _add_lmst_common_flags(pr, is_subparser=True)
    _add_lmst_defaults_flags(pr)
    pr.add_argument("-m", "--model", default=None, help="Model ID (auto-selects loaded model if omitted).")
    pr.add_argument("-p", "--prompt", default=None, help="Input prompt text. If omitted, reads stdin.")
    pr.add_argument("-T", "--temperature", type=float, default=None, help="Sampling temperature.")
    pr.add_argument("-n", "--max-output-tokens", type=int, default=None, help="Maximum output tokens.")
    pr.add_argument("-r", "--stream", dest="stream", action="store_true", default=None, help="Stream tokens live.")
    pr.add_argument("-N", "--no-stream", dest="stream", action="store_false", help="Disable streaming output.")
    pr.add_argument("-S", "--silent", action="store_true", help="Suppress model info and warning notices on stderr.")
    pr.add_argument("-a", "--stats", action="store_true", help="Print token counts and speed to stderr.")
    pr.add_argument("-j", "--json", action="store_true", help="Output full API response as JSON.")
    pr.add_argument("-o", "--output-file", default=None, help="Save response text to file.")
    pr.add_argument("-l", "--newline", action="store_true", help="Print trailing newline after streaming.")
    pr.add_argument(
        "-x",
        "--extra",
        nargs="*",
        default=None,
        metavar="K=V",
        help="Extra JSON key=value pairs for API payload.",
    )
    pr.set_defaults(func=cmd_lmst_responses)

    return p


def _add_lmstui_common_flags(p: argparse.ArgumentParser, is_subparser: bool = False) -> None:
    p.add_argument(
        "-b",
        "--base-url",
        default=argparse.SUPPRESS if is_subparser else None,
        help="LM Studio root base URL (e.g. http://127.0.0.1:1234).",
    )
    p.add_argument(
        "-t",
        "--timeout-seconds",
        default=argparse.SUPPRESS if is_subparser else None,
        type=float,
        help="HTTP timeout seconds (default: 60).",
    )


def build_parser_lmstui() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="lmstui",
        description="LM Studio Termux-friendly CLI/TUI (backward-compatible interface).",
    )
    _add_lmstui_common_flags(p)

    sub = p.add_subparsers(dest="cmd", required=True)

    sp_server = sub.add_parser("server", help="Server helpers")
    _add_lmstui_common_flags(sp_server, is_subparser=True)
    sub_server = sp_server.add_subparsers(dest="server_cmd", required=True)

    sp_ping = sub_server.add_parser("ping", help="Health check (REST preferred, then OpenAI)")
    _add_lmstui_common_flags(sp_ping, is_subparser=True)
    sp_ping.set_defaults(func=cmd_lmstui_server_ping)

    sp_endpoints = sub_server.add_parser("endpoints", help="Print useful endpoint URLs")
    _add_lmstui_common_flags(sp_endpoints, is_subparser=True)
    sp_endpoints.set_defaults(func=cmd_lmstui_server_endpoints)

    sp_models = sub.add_parser("models", help="Model helpers")
    _add_lmstui_common_flags(sp_models, is_subparser=True)
    sub_models = sp_models.add_subparsers(dest="models_cmd", required=True)

    sp_list = sub_models.add_parser("list", help="List models (REST preferred)")
    _add_lmstui_common_flags(sp_list, is_subparser=True)
    sp_list.set_defaults(func=cmd_lmstui_models_list)

    sp_info = sub_models.add_parser("info", help="Show model info (REST)")
    _add_lmstui_common_flags(sp_info, is_subparser=True)
    sp_info.add_argument("-m", "--model-id", required=True, help="Model id")
    sp_info.set_defaults(func=cmd_lmstui_models_info)

    sp_run = sub.add_parser("run", help="One-shot chat request")
    _add_lmstui_common_flags(sp_run, is_subparser=True)
    sp_run.add_argument("-m", "--model", default=None, help="Model id (auto-selects loaded model if omitted)")
    sp_run.add_argument("-p", "--prompt", required=True, help="User prompt")
    sp_run.add_argument("-s", "--system", default=None, help="System prompt")
    sp_run.add_argument("-T", "--temperature", default=0.7, type=float, help="Temperature")
    sp_run.add_argument("-n", "--max-tokens", default=-1, type=int, help="Max tokens (-1 = unlimited)")
    sp_run.add_argument("-S", "--stream", action="store_true", help="Stream output")
    sp_run.set_defaults(func=cmd_lmstui_run)

    sp_chat = sub.add_parser("chat", help="Interactive chat REPL")
    _add_lmstui_common_flags(sp_chat, is_subparser=True)
    sp_chat.add_argument("-m", "--model", default=None, help="Model id (auto-selects loaded model if omitted)")
    sp_chat.add_argument("-s", "--system", default=None, help="System prompt")
    sp_chat.add_argument("-T", "--temperature", default=0.7, type=float, help="Temperature")
    sp_chat.add_argument("-n", "--max-tokens", default=-1, type=int, help="Max tokens (-1 = unlimited)")
    sp_chat.add_argument("-S", "--stream", action="store_true", help="Stream output (recommended)")
    sp_chat.set_defaults(func=cmd_lmstui_chat)

    sp_emb = sub.add_parser("embeddings", help="Create embeddings (REST)")
    _add_lmstui_common_flags(sp_emb, is_subparser=True)
    sp_emb.add_argument("-m", "--model", required=True, help="Embedding model id")
    sp_emb.add_argument("-x", "--text", required=True, help="Text to embed")
    sp_emb.add_argument("-P", "--pretty", action="store_true", help="Pretty-print full JSON response")
    sp_emb.set_defaults(func=cmd_lmstui_embeddings)

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
    sp_ssh.add_argument("-a", "--stats", action="store_true", help="Include prediction stats when available")
    sp_ssh.add_argument("-j", "--json", action="store_true", help="Emit JSON logs (newline separated)")
    sp_ssh.add_argument("-f", "--filter", default=None, help="For model logs: input, output, or input,output")
    sp_ssh.set_defaults(func=cmd_lmstui_logs_ssh)

    return p


# Compatibility alias
build_parser = build_parser_lmstui


def main_lmst(argv: Optional[List[str]] = None) -> int:
    parser = build_parser_lmst()
    args = parser.parse_args(argv)

    if not args.command:
        # Bare lmst invocation:
        # If piped stdin or interactive: attempt to run chat subcommand
        if not sys.stdin.isatty():
            return cmd_lmst_chat(
                argparse.Namespace(
                    base_url=args.base_url,
                    timeout=args.timeout,
                    api_key=args.api_key,
                    verbose=args.verbose,
                    model=None,
                    prompt=None,
                    system_prompt=None,
                    temperature=None,
                    max_tokens=None,
                    stream=None,
                    silent=False,
                    stats=False,
                    json=False,
                    output_file=None,
                    newline=False,
                    extra=None,
                    set_default=None,
                    show_defaults=False,
                    clear_defaults=False,
                    per_model=False,
                )
            )
        # Try to resolve model for interactive chat
        try:
            api = LMStudioAPI(target=args.base_url, timeout_seconds=args.timeout, api_key=args.api_key)
            model, _, _ = api.resolve_model()
            return cmd_lmst_chat(
                argparse.Namespace(
                    base_url=args.base_url,
                    timeout=args.timeout,
                    api_key=args.api_key,
                    verbose=args.verbose,
                    model=model,
                    prompt=None,
                    system_prompt=None,
                    temperature=None,
                    max_tokens=None,
                    stream=None,
                    silent=False,
                    stats=False,
                    json=False,
                    output_file=None,
                    newline=False,
                    extra=None,
                    set_default=None,
                    show_defaults=False,
                    clear_defaults=False,
                    per_model=False,
                )
            )
        except Exception:
            parser.print_help()
            return 0

    return int(args.func(args))


def main_lmstui(argv: Optional[List[str]] = None) -> int:
    parser = build_parser_lmstui()
    args = parser.parse_args(argv)
    return int(args.func(args))


def build_parser_lmc() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="lmc",
        description="Shortcut for 'lmst chat' (interactive or one-shot directly with loaded LLM).",
    )
    _add_lmst_common_flags(p, is_subparser=False)
    _add_lmst_defaults_flags(p)
    p.add_argument("-m", "--model", default=None, help="Model ID (auto-selects loaded model if omitted).")
    p.add_argument("-p", "--prompt", default=None, help="User prompt. If omitted, reads stdin or starts REPL.")
    p.add_argument("-s", "--system-prompt", default=None, help="System prompt.")
    p.add_argument("-T", "--temperature", type=float, default=None, help="Sampling temperature.")
    p.add_argument("-n", "--max-tokens", type=int, default=None, help="Maximum completion tokens.")
    p.add_argument("-r", "--stream", dest="stream", action="store_true", default=None, help="Stream tokens live.")
    p.add_argument("-N", "--no-stream", dest="stream", action="store_false", help="Disable streaming output.")
    p.add_argument("-S", "--silent", action="store_true", help="Suppress model info and warning notices on stderr.")
    p.add_argument("-a", "--stats", action="store_true", help="Print token counts, reasoning tokens, and speed to stderr.")
    p.add_argument("-j", "--json", action="store_true", help="Output full API response as JSON to stdout.")
    p.add_argument("-o", "--output-file", default=None, help="Save final text response to file.")
    p.add_argument("-l", "--newline", action="store_true", help="Print trailing newline after streaming.")
    p.add_argument(
        "-x",
        "--extra",
        nargs="*",
        default=None,
        metavar="K=V",
        help="Extra JSON key=value pairs for API payload.",
    )
    return p


def main_lmc(argv: Optional[List[str]] = None) -> int:
    parser = build_parser_lmc()
    args = parser.parse_args(argv)
    return cmd_lmst_chat(args)


def main(argv: Optional[List[str]] = None) -> int:
    # Default to lmst CLI
    return main_lmst(argv)


if __name__ == "__main__":
    sys.exit(main())
