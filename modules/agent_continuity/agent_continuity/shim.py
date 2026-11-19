"""Fail-open hook shim for capturing Codex and AGY lifecycle events into durable spools."""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from .environment import load_or_create_environment, resolve_home_dir
from .events import append_event
from .hooks import normalized_hook_to_event_envelope
from .providers import ProviderAdapter, default_adapters

MAX_SHIM_STDIN_BYTES = 524_288


@dataclass(slots=True)
class ShimOutcome:
    """Internal diagnostic outcome for a hook shim invocation (never emitted to provider stdout)."""

    recorded: bool
    event_id: str | None
    elapsed_ms: float
    error: str | None = None


def process_hook_stdin(
    provider: str,
    *,
    raw_stdin: str,
    home_dir: Path | str | None = None,
    event_name_hint: str | None = None,
    adapters: dict[str, ProviderAdapter] | None = None,
) -> tuple[dict[str, Any], ShimOutcome]:
    """
    Normalize a bounded JSON hook payload and append it to the local event spool.

    Strictly fail-open: never raises, never executes SQLite migrations or git subprocesses,
    and always returns a provider-safe `{}` response dict.
    """
    t0 = time.perf_counter()
    adapter_map = adapters if adapters is not None else default_adapters()
    adapter = adapter_map.get(provider.strip().lower())
    if adapter is None:
        return {}, ShimOutcome(
            recorded=False,
            event_id=None,
            elapsed_ms=(time.perf_counter() - t0) * 1000.0,
            error=f"Unknown provider: {provider!r}",
        )

    try:
        if len(raw_stdin.encode("utf-8", errors="replace")) > MAX_SHIM_STDIN_BYTES:
            return adapter.safe_hook_response(), ShimOutcome(
                recorded=False,
                event_id=None,
                elapsed_ms=(time.perf_counter() - t0) * 1000.0,
                error="Hook payload exceeded MAX_SHIM_STDIN_BYTES",
            )
        if not raw_stdin.strip():
            return adapter.safe_hook_response(), ShimOutcome(
                recorded=False,
                event_id=None,
                elapsed_ms=(time.perf_counter() - t0) * 1000.0,
                error="Empty hook stdin",
            )
        payload = json.loads(raw_stdin)
        if not isinstance(payload, dict):
            return adapter.safe_hook_response(), ShimOutcome(
                recorded=False,
                event_id=None,
                elapsed_ms=(time.perf_counter() - t0) * 1000.0,
                error="Hook payload is not a JSON object",
            )

        resolved_home = resolve_home_dir(home_dir)
        env = load_or_create_environment(resolved_home, persist=True)
        normalized = adapter.normalize_hook_event(
            payload,
            environment_id=env.environment_id,
            event_name_hint=event_name_hint,
        )
        envelope = normalized_hook_to_event_envelope(normalized)
        append_event(resolved_home, envelope)
        return adapter.safe_hook_response(normalized), ShimOutcome(
            recorded=True,
            event_id=envelope.event_id,
            elapsed_ms=(time.perf_counter() - t0) * 1000.0,
        )
    except Exception as exc:  # noqa: BLE001 — fail-open boundary required by Master Plan §8.7
        return adapter.safe_hook_response(), ShimOutcome(
            recorded=False,
            event_id=None,
            elapsed_ms=(time.perf_counter() - t0) * 1000.0,
            error=str(exc),
        )


def run_hook_shim(
    provider: str,
    *,
    stdin_stream: TextIO | None = None,
    stdout_stream: TextIO | None = None,
    home_dir: Path | str | None = None,
    event_name_hint: str | None = None,
    adapters: dict[str, ProviderAdapter] | None = None,
) -> int:
    """
    CLI entry handler for `agents hook-shim`.

    Reads bounded stdin, writes `{}` to stdout, and always exits 0 (fail-open).
    """
    in_stream = stdin_stream if stdin_stream is not None else sys.stdin
    out_stream = stdout_stream if stdout_stream is not None else sys.stdout
    try:
        raw_text = in_stream.read(MAX_SHIM_STDIN_BYTES + 1)
    except Exception:  # noqa: BLE001
        raw_text = ""

    response, _outcome = process_hook_stdin(
        provider,
        raw_stdin=raw_text,
        home_dir=home_dir,
        event_name_hint=event_name_hint,
        adapters=adapters,
    )
    try:
        out_stream.write(json.dumps(response, separators=(",", ":")) + "\n")
        out_stream.flush()
    except Exception:  # noqa: BLE001
        pass
    return 0
