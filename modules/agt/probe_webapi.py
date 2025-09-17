#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Minimal connectivity probe for a WebAI-to-API server.

Checks:
  1) GET  /v1/models
  2) GET  /v1/providers
  3) POST /v1/chat/completions  (sends 'ping')

Exit code: 0 if any check succeeds, 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any, Dict, Optional

import requests


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Probe a WebAI-to-API server")
    p.add_argument("-u", "--url", default="http://192.168.50.100:6969", help="Base URL of server")
    p.add_argument("-m", "--model", default="gemini-2.0-flash", help="Model to use for chat")
    p.add_argument("-p", "--provider", default=None, help="Provider name (if server expects it)")
    p.add_argument("-t", "--timeout", type=int, default=15, help="HTTP timeout (seconds)")
    p.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    return p.parse_args()


def get_json(url: str, timeout: int, verbose: bool) -> Optional[Dict[str, Any]]:
    try:
        if verbose:
            print(f"[debug] GET {url}")
        r = requests.get(url, timeout=timeout)
        if verbose:
            print(f"[debug] -> status {r.status_code}")
        r.raise_for_status()
        return r.json()
    except Exception as e:
        if verbose:
            print(f"[debug] GET failed: {type(e).__name__}: {e}")
        return None


def post_json(url: str, payload: Dict[str, Any], timeout: int, verbose: bool) -> Optional[Dict[str, Any]]:
    try:
        if verbose:
            print(f"[debug] POST {url}")
            print(f"[debug] payload: {json.dumps(payload)[:400]}")
        r = requests.post(url, json=payload, timeout=timeout)
        if verbose:
            print(f"[debug] -> status {r.status_code}")
        r.raise_for_status()
        return r.json()
    except Exception as e:
        if verbose:
            print(f"[debug] POST failed: {type(e).__name__}: {e}")
        return None


def main() -> int:
    args = parse_args()
    base = args.url.rstrip("/")

    ok_any = False

    models = get_json(f"{base}/v1/models", args.timeout, args.verbose)
    print("[models] OK" if models is not None else "[models] DOWN")
    ok_any = ok_any or (models is not None)

    prov = get_json(f"{base}/v1/providers", args.timeout, args.verbose)
    print("[providers] OK" if prov is not None else "[providers] DOWN")
    ok_any = ok_any or (prov is not None)

    payload: Dict[str, Any] = {"model": args.model, "messages": [{"role": "user", "content": "ping"}]}
    if args.provider:
        payload["provider"] = args.provider

    t0 = time.perf_counter()
    resp = post_json(f"{base}/v1/chat/completions", payload, args.timeout, args.verbose)
    dt = time.perf_counter() - t0
    if resp is not None:
        try:
            msg = resp.get("choices", [{}])[0].get("message", {}).get("content", "")
            snippet = (msg or "")[:160].replace("\n", " ")
            print(f"[chat] OK ({dt:.2f}s) → {snippet!r}")
        except Exception:
            print(f"[chat] OK ({dt:.2f}s) → (unexpected response)")
        ok_any = True
    else:
        print("[chat] DOWN")

    return 0 if ok_any else 1


if __name__ == "__main__":
    raise SystemExit(main())

