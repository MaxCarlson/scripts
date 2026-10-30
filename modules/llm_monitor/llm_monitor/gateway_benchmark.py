"""Opt-in, metadata-only local benchmark for direct and gateway inference requests."""

from __future__ import annotations

import argparse
import asyncio
import csv
import io
import itertools
import json
import random
import shutil
import socket
import statistics
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from contextlib import AsyncExitStack
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from .gateway import OpenAIInferenceGateway, RequestEventHub
from .live_store import LiveInferenceStore

PATHS = ("direct", "minimal", "observed")
ORDERS = tuple(itertools.permutations(PATHS))
SYNTHETIC_PROMPT = "Reply with exactly one color word: amber."
SHORT_PROMPT = "Answer with exactly the single character 4 and nothing else."
LONG_PROMPT = "Write a clear, factual description of a fictional coastal lighthouse in about forty-five words. Do not use a list."
VARIED_PROMPTS = (
    "Reply with exactly the token ALPHA.",
    "Reply with exactly the token BRAVO.",
    "Reply with exactly the token CHARLIE.",
    "Reply with exactly the token DELTA.",
    "Reply with exactly the token ECHO.",
    "Reply with exactly the token FOXTROT.",
    "Reply with exactly the token GOLF.",
    "Reply with exactly the token HOTEL.",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-live", action="store_true", help="Explicitly authorize synthetic requests to the local model")
    parser.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--capture", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--fresh-upstream", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--upstream", default="http://127.0.0.1:1234")
    parser.add_argument("--model", default="qwen38_23GB")
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--max-tokens", type=int, default=32)
    parser.add_argument("--profile", choices=("standard", "short", "long"), default="standard")
    parser.add_argument("--prompt-mode", choices=("fixed", "varied", "alternating"), default="fixed")
    parser.add_argument("--mode", choices=("both", "streaming", "nonstreaming"), default="both")
    parser.add_argument("--concurrency", type=int, choices=range(1, 5), default=1)
    parser.add_argument("--connection-mode", choices=("reused", "fresh"), default="reused")
    parser.add_argument("--sample-gpu", action="store_true", help="Sample device-wide NVIDIA utilization during the run")
    parser.add_argument("--probe-socket-disconnect", action="store_true", help="Run one live synthetic stream and close its client socket after the first text delta")
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
    upstream_limits = httpx.Limits(max_keepalive_connections=0) if args.fresh_upstream else httpx.Limits()
    upstream_client = httpx.AsyncClient(timeout=None, limits=upstream_limits, follow_redirects=False, trust_env=False)
    gateway = OpenAIInferenceGateway(
        args.upstream,
        LiveInferenceStore(),
        RequestEventHub(),
        client=upstream_client,
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
    if args.connection_mode == "fresh":
        command.append("--fresh-upstream")
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _wait_for_listener(port, process)
    return process


async def _sample(
    client: httpx.AsyncClient,
    url: str,
    body: dict[str, Any],
    *,
    fresh_connection: bool = False,
) -> dict[str, Any]:
    if fresh_connection:
        async with httpx.AsyncClient(timeout=None, trust_env=False) as fresh_client:
            return await _sample_with_client(fresh_client, url, body)
    return await _sample_with_client(client, url, body)


async def _sample_with_client(client: httpx.AsyncClient, url: str, body: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter_ns()
    started_epoch = time.time()
    headers_ms = None
    first_data_ms = None
    first_text_ms = None
    generated_tokens = None
    input_tokens = None
    reasoning_tokens = None
    provider_ttft_ms = None
    provider_generation_ms = None
    provider_tokens_per_second = None
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
                            provider = _provider_metrics(event)
                            provider_ttft_ms = provider.get("ttft_ms") or provider_ttft_ms
                            provider_generation_ms = provider.get("generation_ms") or provider_generation_ms
                            provider_tokens_per_second = provider.get("tokens_per_second") or provider_tokens_per_second
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
            provider = _provider_metrics(result)
            provider_ttft_ms = provider.get("ttft_ms")
            provider_generation_ms = provider.get("generation_ms")
            provider_tokens_per_second = provider.get("tokens_per_second")
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
        "started_unix_seconds": started_epoch,
        "completed_unix_seconds": started_epoch + completion_ms / 1000,
        "provider_generation_ms": provider_generation_ms,
        "provider_tokens_per_second": provider_tokens_per_second,
    }


async def _run_trials(args: argparse.Namespace) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    timeout = httpx.Timeout(None)
    limits = httpx.Limits(max_connections=max(4, args.concurrency), max_keepalive_connections=max(4, args.concurrency))
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
        stream_modes = (False, True) if args.mode == "both" else (args.mode == "streaming",)
        for stream in stream_modes:
            mode_name = "streaming" if stream else "nonstreaming"
            warmup = _body(args.model, args.max_tokens, stream, profile=args.profile, prompt_mode=args.prompt_mode, sample_index=1)
            for path in PATHS:
                await _sample(clients[path], urls[path], warmup, fresh_connection=args.connection_mode == "fresh")
            for sample_index in range(args.samples):
                prompt_mode, prompt_index = _prompt_case(args.prompt_mode, sample_index)
                body = _body(
                    args.model,
                    args.max_tokens,
                    stream,
                    profile=args.profile,
                    prompt_mode=prompt_mode,
                    sample_index=prompt_index,
                )
                order = ORDERS[sample_index % len(ORDERS)]
                for path in order:
                    results = await asyncio.gather(*(
                        _sample(clients[path], urls[path], body, fresh_connection=args.connection_mode == "fresh")
                        for _ in range(args.concurrency)
                    ))
                    for request_index, result in enumerate(results):
                        records.append({
                            "mode": mode_name,
                            "sample": sample_index + 1,
                            "request_index": request_index,
                            "order": list(order),
                            "path": path,
                            "profile": args.profile,
                            "prompt_mode": prompt_mode,
                            "connection_mode": args.connection_mode,
                            "concurrency": args.concurrency,
                            **result,
                        })
    summary = _summarize(records, args.samples)
    return {"summary": summary, "samples": records}


def _prompt_case(prompt_mode: str, sample_index: int) -> tuple[str, int]:
    if prompt_mode == "alternating":
        return ("fixed" if sample_index % 2 == 0 else "varied", sample_index // 2 + 1)
    return prompt_mode, sample_index + 1


def _body(
    model: str,
    max_tokens: int,
    stream: bool,
    *,
    profile: str = "standard",
    prompt_mode: str = "fixed",
    sample_index: int = 1,
) -> dict[str, Any]:
    prompt = SYNTHETIC_PROMPT
    if profile == "short":
        prompt = SHORT_PROMPT
        max_tokens = 8
    elif profile == "long":
        prompt = LONG_PROMPT
        max_tokens = 96
    if prompt_mode == "varied":
        prompt = VARIED_PROMPTS[(sample_index - 1) % len(VARIED_PROMPTS)]
    body: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0,
        "stream": stream,
    }
    if profile in {"short", "long"}:
        body["reasoning_effort"] = "none"
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


def _provider_metrics(payload: dict[str, Any]) -> dict[str, float | None]:
    timings = payload.get("timings") if isinstance(payload.get("timings"), dict) else {}
    stats = payload.get("stats") if isinstance(payload.get("stats"), dict) else {}
    combined = {**stats, **timings}
    ttft_ms = _provider_ttft_ms(combined)
    if ttft_ms is None:
        seconds = combined.get("time_to_first_token")
        if isinstance(seconds, (int, float)) and not isinstance(seconds, bool) and seconds >= 0:
            ttft_ms = float(seconds) * 1000
    generation_ms = None
    for key in ("generation_time_ms", "generation_ms", "predicted_ms"):
        value = combined.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
            generation_ms = float(value)
            break
    if generation_ms is None:
        seconds = combined.get("generation_time")
        if isinstance(seconds, (int, float)) and not isinstance(seconds, bool) and seconds >= 0:
            generation_ms = float(seconds) * 1000
    tokens_per_second = combined.get("tokens_per_second")
    if not isinstance(tokens_per_second, (int, float)) or isinstance(tokens_per_second, bool) or tokens_per_second < 0:
        tokens_per_second = None
    return {
        "ttft_ms": ttft_ms,
        "generation_ms": generation_ms,
        "tokens_per_second": float(tokens_per_second) if tokens_per_second is not None else None,
    }


def _parse_gpu_query(output: str) -> list[dict[str, Any]]:
    devices = []
    for row in csv.reader(io.StringIO(output)):
        if len(row) < 7:
            continue
        name, index, gpu_util, memory_util, used, total, power = (item.strip() for item in row[:7])
        try:
            parsed_index = int(index)
        except ValueError:
            continue
        devices.append({
            "name": name,
            "index": parsed_index,
            "gpu_utilization_percent": _number(gpu_util),
            "memory_utilization_percent": _number(memory_util),
            "memory_used_mib": _number(used),
            "memory_total_mib": _number(total),
            "power_watts": _number(power),
        })
    return devices


def _number(value: str) -> int | float | None:
    if value.upper() in {"N/A", "NA", "[NOT SUPPORTED]", ""}:
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    return int(parsed) if parsed.is_integer() else parsed


class _GpuSampler:
    """Low-rate device-wide NVIDIA telemetry; samples are metadata only."""

    def __init__(self, interval_seconds: float = 1.0) -> None:
        self.interval_seconds = interval_seconds
        self.binary = shutil.which("nvidia-smi")
        self.samples: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self.binary:
            self._thread = threading.Thread(target=self._run, name="llm-monitor-gpu-sampler", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=4)

    def report(self) -> dict[str, Any]:
        with self._lock:
            samples = list(self.samples)
        return {
            "source": "nvidia-smi",
            "sample_interval_seconds": self.interval_seconds,
            "available": bool(self.binary),
            "sample_count": len(samples),
            "samples": samples,
        }

    def _run(self) -> None:
        command = [
            self.binary or "nvidia-smi",
            "--query-gpu=name,index,utilization.gpu,utilization.memory,memory.used,memory.total,power.draw",
            "--format=csv,noheader,nounits",
        ]
        while not self._stop.is_set():
            started = time.perf_counter_ns()
            observed_at = datetime.now(timezone.utc).isoformat()
            devices = []
            try:
                result = subprocess.run(command, capture_output=True, text=True, timeout=3, check=False)
                if result.returncode == 0:
                    devices = _parse_gpu_query(result.stdout)
            except (OSError, subprocess.TimeoutExpired):
                devices = []
            duration_ms = (time.perf_counter_ns() - started) / 1_000_000
            with self._lock:
                self.samples.append({"observed_at": observed_at, "query_duration_ms": duration_ms, "devices": devices})
            self._stop.wait(max(0.0, self.interval_seconds - duration_ms / 1000))


def _runtime_snapshot(upstream: str, model: str) -> dict[str, Any]:
    try:
        response = httpx.get(f"{upstream}/api/v1/models", timeout=5, trust_env=False)
        response.raise_for_status()
        models = response.json().get("models", [])
    except (httpx.HTTPError, ValueError, AttributeError):
        return {"available": False, "selected_model_loaded": None}
    if not isinstance(models, list):
        return {"available": False, "selected_model_loaded": None}
    for item in models:
        if not isinstance(item, dict):
            continue
        instances = item.get("loaded_instances")
        if not isinstance(instances, list):
            instances = []
        selected_instances = [instance for instance in instances if isinstance(instance, dict) and instance.get("id") == model]
        if item.get("key") == model or selected_instances:
            return {
                "available": True,
                "entry_key": item.get("key"),
                "selected_model_loaded": bool(instances),
                "loaded_instance_count": len(instances),
                "selected_instance": [
                    {
                        "id": instance.get("id"),
                        "config": {
                            key: instance.get("config", {}).get(key)
                            for key in ("context_length", "parallel", "eval_batch_size", "flash_attention", "offload_kv_cache_to_gpu")
                            if isinstance(instance.get("config"), dict) and key in instance["config"]
                        },
                    }
                    for instance in selected_instances
                ],
            }
    return {"available": True, "selected_model_loaded": False, "entry_key": None, "loaded_instance_count": 0}


def _chunk_has_text_delta(chunk: bytes) -> bool:
    for line in chunk.splitlines():
        line = line.strip()
        if not line.startswith(b"data:"):
            continue
        data = line[5:].strip()
        try:
            event = json.loads(data)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        choices = event.get("choices") if isinstance(event, dict) else None
        if not isinstance(choices, list):
            continue
        for choice in choices:
            delta = choice.get("delta") if isinstance(choice, dict) else None
            if isinstance(delta, dict) and any(isinstance(delta.get(key), str) and delta[key] for key in ("content", "reasoning_content")):
                return True
    return False


async def _run_socket_disconnect_probe(upstream: str, model: str) -> dict[str, Any]:
    from fastapi import FastAPI
    import uvicorn

    from .gateway import OpenAIInferenceGateway, RequestEventHub
    from .live_store import LiveInferenceStore

    upstream_closed = asyncio.Event()
    parsed_upstream = httpx.URL(upstream)

    class TrackingStream(httpx.AsyncByteStream):
        def __init__(self, source: httpx.AsyncByteStream) -> None:
            self.source = source

        async def __aiter__(self):
            async for chunk in self.source:
                yield chunk

        async def aclose(self) -> None:
            try:
                await self.source.aclose()
            finally:
                upstream_closed.set()

    class TrackingClient(httpx.AsyncClient):
        async def send(self, request, *args, **kwargs):
            response = await super().send(request, *args, **kwargs)
            if request.url.host == parsed_upstream.host and request.url.port == parsed_upstream.port:
                response.stream = TrackingStream(response.stream)
            return response

    store = LiveInferenceStore()
    hub = RequestEventHub()
    upstream_client = TrackingClient(timeout=None, follow_redirects=False, trust_env=False)
    gateway = OpenAIInferenceGateway(upstream, store, hub, client=upstream_client)
    app = FastAPI()
    app.include_router(gateway.router())
    app.add_event_handler("shutdown", gateway.close)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", access_log=False))
    server_task = asyncio.create_task(server.serve())
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        if server_task.done():
            await server_task
            raise RuntimeError("disconnect probe server exited before listening")
        await asyncio.sleep(0.025)
    if not server.started:
        server.should_exit = True
        await server_task
        raise TimeoutError("disconnect probe server did not start")
    started_epoch = time.time()
    first_text_ms = None
    response_status = None
    response_bytes = 0
    disconnected = False
    try:
        async with httpx.AsyncClient(timeout=None, trust_env=False) as client:
            async with client.stream(
                "POST",
                f"http://127.0.0.1:{port}/v1/chat/completions",
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "Write a detailed description of a fictional lighthouse using at least ninety words."}],
                    "temperature": 0,
                    "max_tokens": 192,
                    "reasoning_effort": "none",
                    "stream": True,
                    "stream_options": {"include_usage": True},
                },
            ) as response:
                response_status = response.status_code
                if response.status_code != 200:
                    raise RuntimeError(f"disconnect probe upstream returned HTTP {response.status_code}")
                async for chunk in response.aiter_bytes():
                    response_bytes += len(chunk)
                    if _chunk_has_text_delta(chunk):
                        first_text_ms = (time.time() - started_epoch) * 1000
                        disconnected = True
                        break
    finally:
        server.should_exit = True
        await server_task
    if not disconnected:
        raise RuntimeError("disconnect probe ended before a text delta was received")
    await asyncio.wait_for(upstream_closed.wait(), timeout=10)
    rows = store.requests()
    state = rows[0].state if rows else None
    return {
        "request_id": rows[0].request_id if rows else None,
        "response_status": response_status,
        "client_socket_closed_after_text": disconnected,
        "response_bytes_before_close": response_bytes,
        "first_text_observed_ms": first_text_ms,
        "monitor_terminal_state": state,
        "upstream_response_stream_closed": upstream_closed.is_set(),
        "event_sequence": hub.sequence,
        "request_content_retained_in_memory": bool(rows and rows[0].content),
    }


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
        per_path = {path: {} for path in PATHS}
        paired: dict[str, dict[str, list[float]]] = {
            comparison: {metric: [] for metric in ("end_to_end_ms", "response_headers_ms", "first_data_ms")}
            for comparison in ("minimal_vs_direct", "observed_vs_direct", "observed_vs_minimal")
        }
        paired_trials = []
        matched_groups = 0
        request_orders: dict[str, int] = {}
        prompt_mode_counts: dict[str, int] = {}
        for sample_index in range(1, samples + 1):
            group = [item for item in records if item["mode"] == mode and item["sample"] == sample_index]
            by_path = {path: [item for item in group if item["path"] == path] for path in PATHS}
            if not any(by_path.values()):
                continue
            order = group[0].get("order", []) if group else []
            prompt_mode = group[0].get("prompt_mode", "unknown") if group else "unknown"
            prompt_mode_counts[prompt_mode] = prompt_mode_counts.get(prompt_mode, 0) + 1
            if order:
                order_key = ">".join(order)
                request_orders[order_key] = request_orders.get(order_key, 0) + 1
            path_medians = {
                path: {
                    metric: statistics.median(row[metric] for row in rows if isinstance(row.get(metric), (int, float)))
                    for metric in ("end_to_end_ms", "response_headers_ms", "first_data_ms")
                    if any(isinstance(row.get(metric), (int, float)) for row in rows)
                }
                for path, rows in by_path.items()
            }
            tokens_by_path = {
                path: sorted(row["generated_tokens"] for row in rows if isinstance(row.get("generated_tokens"), int))
                for path, rows in by_path.items()
            }
            matched = all(tokens_by_path[path] for path in PATHS) and len({tuple(tokens_by_path[path]) for path in PATHS}) == 1
            matched_groups += int(matched)
            trial = {
                "sample": sample_index,
                "order": order,
                "prompt_mode": prompt_mode,
                "matched_output_tokens": tokens_by_path if matched else None,
            }
            pairs = {
                "minimal_vs_direct": ("minimal", "direct"),
                "observed_vs_direct": ("observed", "direct"),
                "observed_vs_minimal": ("observed", "minimal"),
            }
            trial_differences = {}
            for comparison, (later, earlier) in pairs.items():
                metrics = {}
                for metric in paired[comparison]:
                    if metric in path_medians[later] and metric in path_medians[earlier]:
                        difference = path_medians[later][metric] - path_medians[earlier][metric]
                        paired[comparison][metric].append(difference)
                        metrics[metric] = difference
                trial_differences[comparison] = metrics
            trial["paired_differences_ms"] = trial_differences
            paired_trials.append(trial)
            for path, rows in by_path.items():
                slow = [row for row in rows if row["end_to_end_ms"] > 1000]
                if slow:
                    per_path[path][sample_index] = max(row["end_to_end_ms"] for row in slow)

        summary[mode]["matched_output_groups"] = matched_groups
        summary[mode]["trial_groups"] = len(paired_trials)
        summary[mode]["request_order_counts"] = request_orders
        summary[mode]["prompt_mode_counts"] = prompt_mode_counts
        summary[mode]["paired_overhead"] = {
            comparison: _paired_latency_stats(values["end_to_end_ms"])
            for comparison, values in paired.items()
        }
        summary[mode]["paired_header_delta"] = {
            comparison: _paired_latency_stats(values["response_headers_ms"])
            for comparison, values in paired.items()
        }
        summary[mode]["paired_first_data_delta"] = {
            comparison: _paired_latency_stats(values["first_data_ms"])
            for comparison, values in paired.items()
        }
        summary[mode]["path_tail"] = {
            path: {
                "over_1000ms_samples": len(per_path[path]),
                "sample_frequency": len(per_path[path]) / len(paired_trials) if paired_trials else 0.0,
                "worst_case_ms": max(per_path[path].values()) if per_path[path] else None,
                "outlier_request_orders": [
                    {"sample": index, "order": next((trial["order"] for trial in paired_trials if trial["sample"] == index), [])}
                    for index in sorted(per_path[path])
                ],
            }
            for path in PATHS
        }
        summary[mode]["paired_trials"] = paired_trials
    return summary


def _paired_latency_stats(values: list[float]) -> dict[str, Any]:
    return {
        "n": len(values),
        "median_ms": statistics.median(values) if values else None,
        "p95_ms": _percentile(values, 0.95),
        "worst_case_ms": max(values) if values else None,
        "minimum_ms": min(values) if values else None,
        "outliers_over_100ms": sum(value > 100 for value in values),
        "outliers_over_500ms": sum(value > 500 for value in values),
        "median_95pct_ci_ms": _bootstrap_median_ci(values),
    }


def _bootstrap_median_ci(values: list[float], *, seed: int = 20261029, iterations: int = 2000) -> list[float | None]:
    if not values:
        return [None, None]
    if len(values) == 1:
        return [values[0], values[0]]
    generator = random.Random(seed)
    bootstrapped = [statistics.median(generator.choices(values, k=len(values))) for _ in range(iterations)]
    return [_percentile(bootstrapped, 0.025), _percentile(bootstrapped, 0.975)]


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
    minimum_samples = 20 if args.profile == "standard" and args.mode == "both" and args.concurrency == 1 else 5
    if args.samples < minimum_samples or args.max_tokens < 1:
        print(f"--samples must be at least {minimum_samples} for this profile and --max-tokens must be positive.", file=sys.stderr)
        return 2
    if args.minimal_port == args.observed_port:
        print("Benchmark listener ports must be different.", file=sys.stderr)
        return 2
    if not args.upstream.startswith("http://127.0.0.1:"):
        print("The benchmark only accepts an explicit IPv4 loopback upstream.", file=sys.stderr)
        return 2
    runtime_before = _runtime_snapshot(args.upstream, args.model)
    if runtime_before.get("selected_model_loaded") is not True:
        print("The selected model is not confirmed loaded; refusing to load or select a model automatically.", file=sys.stderr)
        return 1
    selected_configs = [instance.get("config", {}) for instance in runtime_before.get("selected_instance", []) if isinstance(instance, dict)]
    configured_parallel = max((config.get("parallel", 1) for config in selected_configs if isinstance(config.get("parallel"), int)), default=1)
    if args.concurrency > configured_parallel:
        print(f"Requested concurrency {args.concurrency} exceeds the selected instance's reported parallel capacity {configured_parallel}.", file=sys.stderr)
        return 2
    if args.probe_socket_disconnect:
        try:
            disconnect = asyncio.run(_run_socket_disconnect_probe(args.upstream, args.model))
        except Exception as error:
            print(f"Socket disconnect probe failed: {type(error).__name__}: {error}", file=sys.stderr)
            return 1
        report = {
            "schema_version": 1,
            "probe": "real_inference_client_tcp_disconnect_after_first_text_delta",
            "model": args.model,
            "upstream": args.upstream,
            "model_runtime_before": runtime_before,
            "model_runtime_after": _runtime_snapshot(args.upstream, args.model),
            **disconnect,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        if disconnect.get("monitor_terminal_state") != "cancelled" or not disconnect.get("upstream_response_stream_closed"):
            return 1
        return 0
    timing_path = args.output.with_name(args.output.stem + "_gateway_timings.jsonl")
    processes: list[subprocess.Popen[Any]] = []
    started = time.time()
    gpu_sampler = _GpuSampler()
    if args.sample_gpu:
        gpu_sampler.start()
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
        gpu_sampler.stop()
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
        "model_runtime_before": runtime_before,
        "model_runtime_after": _runtime_snapshot(args.upstream, args.model),
        "request": {
            "prompt_class": args.profile,
            "prompt_mode": args.prompt_mode,
            "max_tokens": args.max_tokens if args.profile == "standard" else (8 if args.profile == "short" else 96),
            "temperature": 0,
            "reasoning_effort": "none" if args.profile in {"short", "long"} else "provider_default",
            "seed": None,
        },
        "samples_per_path_and_mode": args.samples,
        "profile": args.profile,
        "mode": args.mode,
        "prompt_mode": args.prompt_mode,
        "concurrency_per_path": args.concurrency,
        "connection_mode": args.connection_mode,
        "ordering": "six-order counterbalanced three-path cycle; warmup excluded; request body held identical within each triplet",
        "httpx_version": version,
        "gateway_timing_file": str(timing_path),
        "process_metrics_note": "Observed gateway process CPU (platform-resolution-limited) and RSS are sampled in-process in the metadata-only timing file; external Windows child-process counters are excluded",
        "provider_activity_note": "LM Studio exposes loaded-instance configuration and maximum parallel prediction capacity, but no active queue/request counter was available; GPU samples are device-wide and cannot identify request ownership.",
        "gpu_sampling": gpu_sampler.report() if args.sample_gpu else {"available": False, "reason": "not_enabled"},
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
