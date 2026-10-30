"""Opt-in, metadata-only local benchmark for direct and gateway inference requests."""

from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import shutil
import socket
import statistics
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

import httpx

from .gateway import OpenAIInferenceGateway, RequestEventHub
from .live_store import LiveInferenceStore

PATHS = ("direct", "minimal", "observed")
ORDERS = tuple(itertools.permutations(PATHS))
SYNTHETIC_PROMPT = "Reply with exactly one color word: amber."


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-live", action="store_true", help="Explicitly authorize synthetic requests to the local model")
    parser.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--capture", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--upstream", default="http://127.0.0.1:1234")
    parser.add_argument("--model", default="qwen38_23GB")
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--max-tokens", type=int, default=32)
    parser.add_argument("--minimal-port", type=int, default=8798)
    parser.add_argument("--observed-port", type=int, default=8799)
    parser.add_argument("--output", type=Path, default=Path("phase_d1_benchmark.json"))
    parser.add_argument("--timings-output", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--host", default="127.0.0.1", help=argparse.SUPPRESS)
    return parser


def _timing_file_sink(path: Path | None) -> Callable[[dict[str, Any]], None] | None:
    if path is None:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open("w", encoding="utf-8")
    lock = threading.Lock()

    def write(item: dict[str, Any]) -> None:
        with lock:
            stream.write(json.dumps(item, separators=(",", ":")) + "\n")
            stream.flush()

    write.close = stream.close  # type: ignore[attr-defined]
    return write


def _serve(args: argparse.Namespace) -> int:
    from fastapi import FastAPI
    import uvicorn

    timing_sink = _timing_file_sink(args.timings_output) if args.capture else None
    gateway = OpenAIInferenceGateway(
        args.upstream,
        LiveInferenceStore(),
        RequestEventHub(),
        timing_sink=timing_sink,
        capture_enabled=args.capture,
    )
    app = FastAPI()
    app.include_router(gateway.router())
    app.add_event_handler("shutdown", gateway.close)
    config = uvicorn.Config(app, host=args.host, port=args.minimal_port if not args.capture else args.observed_port, log_level="error", access_log=False)
    try:
        uvicorn.Server(config).run()
    finally:
        if timing_sink is not None:
            timing_sink.close()  # type: ignore[attr-defined]
    return 0


def _wait_for_listener(port: int, process: subprocess.Popen[Any], timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"benchmark gateway exited early with code {process.returncode}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                return
        except OSError:
            time.sleep(0.1)
    raise TimeoutError(f"benchmark gateway did not listen on 127.0.0.1:{port}")


def _start_server(args: argparse.Namespace, *, capture: bool, timings: Path) -> subprocess.Popen[Any]:
    port = args.observed_port if capture else args.minimal_port
    command = [
        sys.executable,
        "-m",
        "llm_monitor.gateway_benchmark",
        "--serve",
        "--upstream",
        args.upstream,
        "--host",
        "127.0.0.1",
        "--minimal-port",
        str(args.minimal_port),
        "--observed-port",
        str(args.observed_port),
    ]
    if capture:
        command.extend(("--capture", "--timings-output", str(timings)))
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _wait_for_listener(port, process)
    return process


async def _sample(client: httpx.AsyncClient, url: str, body: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter_ns()
    headers_ms = None
    first_data_ms = None
    first_text_ms = None
    generated_tokens = None
    input_tokens = None
    reasoning_tokens = None
    provider_ttft_ms = None
    finish_reason = None
    status_code = None
    buffer = bytearray()
    async with client.stream("POST", url, json=body) as response:
        status_code = response.status_code
        headers_ms = (time.perf_counter_ns() - started) / 1_000_000
        async for chunk in response.aiter_bytes():
            if first_data_ms is None and chunk:
                first_data_ms = (time.perf_counter_ns() - started) / 1_000_000
            if body.get("stream"):
                buffer.extend(chunk)
                while b"\n" in buffer:
                    line, _, remainder = buffer.partition(b"\n")
                    buffer = bytearray(remainder)
                    if line.startswith(b"data:"):
                        data = line[5:].strip()
                        if data == b"[DONE]":
                            continue
                        try:
                            event = json.loads(data)
                        except (UnicodeDecodeError, json.JSONDecodeError):
                            continue
                        usage = event.get("usage") if isinstance(event, dict) else None
                        if isinstance(usage, dict):
                            generated_tokens = _integer(usage.get("completion_tokens"))
                            input_tokens = _integer(usage.get("prompt_tokens"))
                            details = usage.get("completion_tokens_details")
                            reasoning_tokens = _integer(details.get("reasoning_tokens")) if isinstance(details, dict) else None
                        if isinstance(event, dict):
                            provider_ttft_ms = _provider_ttft_ms(event.get("timings")) or provider_ttft_ms
                        choices = event.get("choices") if isinstance(event, dict) else None
                        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
                            delta = choices[0].get("delta")
                            if first_text_ms is None and isinstance(delta, dict) and any(
                                isinstance(delta.get(field), str) and delta[field]
                                for field in ("content", "reasoning_content")
                            ):
                                first_text_ms = (time.perf_counter_ns() - started) / 1_000_000
                            finish_reason = choices[0].get("finish_reason") or finish_reason
            else:
                buffer.extend(chunk)
    completion_ms = (time.perf_counter_ns() - started) / 1_000_000
    if not body.get("stream"):
        try:
            result = json.loads(buffer)
        except (UnicodeDecodeError, json.JSONDecodeError):
            result = {}
        usage = result.get("usage") if isinstance(result, dict) else None
        if isinstance(usage, dict):
            generated_tokens = _integer(usage.get("completion_tokens"))
            input_tokens = _integer(usage.get("prompt_tokens"))
            details = usage.get("completion_tokens_details")
            reasoning_tokens = _integer(details.get("reasoning_tokens")) if isinstance(details, dict) else None
        if isinstance(result, dict):
            provider_ttft_ms = _provider_ttft_ms(result.get("timings"))
        choices = result.get("choices") if isinstance(result, dict) else None
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            finish_reason = choices[0].get("finish_reason")
    if status_code is None or status_code >= 400:
        raise RuntimeError(f"inference sample failed with HTTP status {status_code}")
    elapsed_from_first = (completion_ms - first_text_ms) if body.get("stream") and first_text_ms is not None else None
    return {
        "status_code": status_code,
        "end_to_end_ms": completion_ms,
        "response_headers_ms": headers_ms,
        "first_data_ms": first_data_ms,
        "first_text_ms": first_text_ms,
        "completion_ms": completion_ms,
        "provider_ttft_ms": provider_ttft_ms,
        "input_tokens": input_tokens,
        "generated_tokens": generated_tokens,
        "reasoning_tokens": reasoning_tokens,
        "finish_reason": finish_reason,
        "estimated_tps_after_first_text": generated_tokens / (elapsed_from_first / 1000) if generated_tokens and elapsed_from_first and elapsed_from_first > 0 else None,
    }


async def _run_trials(args: argparse.Namespace) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    timeout = httpx.Timeout(None)
    limits = httpx.Limits(max_connections=4, max_keepalive_connections=4)
    async with AsyncExitStack() as stack:
        clients = {
            "direct": await stack.enter_async_context(httpx.AsyncClient(timeout=timeout, limits=limits, trust_env=False)),
            "minimal": await stack.enter_async_context(httpx.AsyncClient(timeout=timeout, limits=limits, trust_env=False)),
            "observed": await stack.enter_async_context(httpx.AsyncClient(timeout=timeout, limits=limits, trust_env=False)),
        }
        urls = {
            "direct": f"{args.upstream}/v1/chat/completions",
            "minimal": f"http://127.0.0.1:{args.minimal_port}/v1/chat/completions",
            "observed": f"http://127.0.0.1:{args.observed_port}/v1/chat/completions",
        }
        for stream in (False, True):
            mode_name = "streaming" if stream else "nonstreaming"
            warmup = _body(args.model, args.max_tokens, stream)
            for path in PATHS:
                await _sample(clients[path], urls[path], warmup)
            for sample_index in range(args.samples):
                body = _body(args.model, args.max_tokens, stream)
                order = ORDERS[sample_index % len(ORDERS)]
                for path in order:
                    result = await _sample(clients[path], urls[path], body)
                    records.append({"mode": mode_name, "sample": sample_index + 1, "order": list(order), "path": path, **result})
    summary = _summarize(records, args.samples)
    return {"summary": summary, "samples": records}


def _body(model: str, max_tokens: int, stream: bool) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": SYNTHETIC_PROMPT}],
        "max_tokens": max_tokens,
        "temperature": 0,
        "stream": stream,
    }
    if stream:
        body["stream_options"] = {"include_usage": True}
    return body


def _integer(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _provider_ttft_ms(value: Any) -> float | None:
    if not isinstance(value, dict):
        return None
    for key in ("ttft_ms", "time_to_first_token_ms"):
        item = value.get(key)
        if isinstance(item, (int, float)) and not isinstance(item, bool) and item >= 0:
            return float(item)
    return None


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = round((len(ordered) - 1) * percentile)
    return ordered[index]


def _summarize(records: list[dict[str, Any]], samples: int) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for mode in ("nonstreaming", "streaming"):
        summary[mode] = {}
        for path in PATHS:
            subset = [item for item in records if item["mode"] == mode and item["path"] == path]
            latency = [item["end_to_end_ms"] for item in subset]
            first_data = [item["first_data_ms"] for item in subset if item["first_data_ms"] is not None]
            tps = [item["estimated_tps_after_first_text"] for item in subset if item["estimated_tps_after_first_text"] is not None]
            headers = [item["response_headers_ms"] for item in subset if item["response_headers_ms"] is not None]
            summary[mode][path] = {
                "samples": len(subset),
                "median_end_to_end_ms": statistics.median(latency) if latency else None,
                "p95_end_to_end_ms": _percentile(latency, 0.95),
                "stdev_end_to_end_ms": statistics.pstdev(latency) if len(latency) > 1 else 0.0 if latency else None,
                "median_headers_ms": statistics.median(headers) if headers else None,
                "median_first_data_ms": statistics.median(first_data) if first_data else None,
                "median_first_text_ms": statistics.median(item["first_text_ms"] for item in subset if item["first_text_ms"] is not None) if any(item["first_text_ms"] is not None for item in subset) else None,
                "median_estimated_tps_after_first_text": statistics.median(tps) if tps else None,
                "median_generated_tokens": statistics.median(item["generated_tokens"] for item in subset if item["generated_tokens"] is not None) if any(item["generated_tokens"] is not None for item in subset) else None,
                "usable_samples": len(subset),
            }
        groups = []
        for index in range(samples):
            group = [item for item in records if item["mode"] == mode and item["sample"] == index + 1]
            counts = [item["generated_tokens"] for item in group]
            groups.append(bool(len(counts) == 3 and counts[0] is not None and counts.count(counts[0]) == 3))
        summary[mode]["matched_output_groups"] = sum(groups)
        summary[mode]["trial_groups"] = len(groups)
    return summary


def _summarize_timings(path: Path) -> dict[str, Any]:
    try:
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, json.JSONDecodeError):
        return {"samples": 0, "error": "timing_file_unavailable_or_invalid"}
    fields = (
        "request_received_ms", "body_read_ms", "normalization_ms", "upstream_dispatch_ms",
        "upstream_headers_ms", "first_upstream_byte_ms", "first_downstream_byte_ms",
        "body_complete_ms", "event_publication_ms", "content_store_update_ms", "finalization_ms",
        "gateway_process_cpu_ms", "gateway_process_rss_bytes",
    )
    return {
        "samples": len(records),
        "median_ms": {
            field: statistics.median(values)
            for field in fields
            if (values := [record[field] for record in records if isinstance(record.get(field), (int, float))])
        },
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.serve:
        return _serve(args)
    if not args.run_live:
        print("Refusing live inference without --run-live.", file=sys.stderr)
        return 2
    if args.samples < 20 or args.max_tokens < 1:
        print("--samples must be at least 20 and --max-tokens must be positive.", file=sys.stderr)
        return 2
    if args.minimal_port == args.observed_port:
        print("Benchmark listener ports must be different.", file=sys.stderr)
        return 2
    if not args.upstream.startswith("http://127.0.0.1:"):
        print("The benchmark only accepts an explicit IPv4 loopback upstream.", file=sys.stderr)
        return 2
    timing_path = args.output.with_name(args.output.stem + "_gateway_timings.jsonl")
    processes: list[subprocess.Popen[Any]] = []
    started = time.time()
    try:
        minimal = _start_server(args, capture=False, timings=timing_path)
        processes.append(minimal)
        observed = _start_server(args, capture=True, timings=timing_path)
        processes.append(observed)
        trial_result = asyncio.run(_run_trials(args))
    except Exception as error:
        print(f"Benchmark failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    finally:
        for process in reversed(processes):
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    try:
        import httpx as httpx_module

        version = httpx_module.__version__
    except Exception:
        version = None
    try:
        inventory = httpx.get(f"{args.upstream}/v1/models", timeout=5.0, trust_env=False).json()
        model_ids = [item.get("id") for item in inventory.get("data", []) if isinstance(item, dict) and isinstance(item.get("id"), str)]
        model_loaded = args.model in model_ids
    except (httpx.HTTPError, ValueError, AttributeError):
        model_ids = []
        model_loaded = False
    lms_version = None
    lms_cli = shutil.which("lms")
    if lms_cli:
        try:
            version_result = subprocess.run([lms_cli, "--version"], capture_output=True, text=True, timeout=5, check=False)
            lms_version = (version_result.stdout or version_result.stderr).strip()[:200] or None
        except (OSError, subprocess.TimeoutExpired):
            lms_version = None
    summary = trial_result["summary"]
    overhead = {}
    for mode in ("nonstreaming", "streaming"):
        direct_median = summary[mode]["direct"]["median_end_to_end_ms"]
        minimal_median = summary[mode]["minimal"]["median_end_to_end_ms"]
        observed_median = summary[mode]["observed"]["median_end_to_end_ms"]
        overhead[mode] = {
            "minimal_gateway_vs_direct_ms": minimal_median - direct_median if minimal_median is not None and direct_median is not None else None,
            "observation_processing_vs_minimal_ms": observed_median - minimal_median if observed_median is not None and minimal_median is not None else None,
            "observed_gateway_vs_direct_ms": observed_median - direct_median if observed_median is not None and direct_median is not None else None,
        }
    report = {
        "schema_version": 1,
        "started_unix_seconds": started,
        "duration_seconds": time.time() - started,
        "upstream": args.upstream,
        "model": args.model,
        "lm_studio_version": lms_version,
        "available_models": model_ids,
        "selected_model_listed": model_loaded,
        "request": {"prompt_class": "fixed_synthetic_single_message", "max_tokens": args.max_tokens, "temperature": 0, "seed": None},
        "samples_per_path_and_mode": args.samples,
        "ordering": "counterbalanced three-path Latin cycle, warmed connections, same request body per triplet",
        "httpx_version": version,
        "gateway_timing_file": str(timing_path),
        "process_metrics_note": "Observed gateway process CPU (platform-resolution-limited) and RSS are sampled in-process in the metadata-only timing file; external Windows child-process counters are excluded",
        "summary": summary,
        "median_overhead_breakdown": overhead,
        "gateway_stage_timing_summary": _summarize_timings(timing_path),
        "samples": trial_result["samples"],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "gateway_timing_file": str(timing_path), "summary": summary}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
