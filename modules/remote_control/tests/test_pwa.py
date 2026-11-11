"""Tests for remote_control PWA assets, Service Worker, and Manifest."""

from __future__ import annotations

import json
from fastapi.testclient import TestClient


def test_index_shell_served(client: TestClient) -> None:
    """The root route / serves index.html."""
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    assert "<!DOCTYPE html>" in resp.text
    assert "Remote Control" in resp.text


def test_web_app_manifest_served_and_valid(client: TestClient) -> None:
    """The /manifest.json route serves valid PWA configuration."""
    resp = client.get("/manifest.json")
    assert resp.status_code == 200
    manifest = resp.json()

    assert manifest["name"] == "Scripts Remote Control"
    assert manifest["short_name"] in ("RemoteControl", "RemoteCtrl")
    assert manifest["display"] == "standalone"
    assert manifest["start_url"] == "/"
    assert len(manifest["icons"]) >= 1


def test_service_worker_served_and_bypasses_api(client: TestClient) -> None:
    """The /sw.js service worker explicitly excludes /api/ from offline caching."""
    resp = client.get("/sw.js")
    assert resp.status_code == 200
    js = resp.text

    # Must contain service worker lifecycle events
    assert 'addEventListener("install"' in js or "addEventListener('install'" in js
    assert 'addEventListener("fetch"' in js or "addEventListener('fetch'" in js

    # Must specifically bypass /api/
    assert 'url.pathname.startsWith("/api/")' in js or "url.pathname.startsWith('/api/')" in js
    assert "remote-control-shell" in js


def test_static_assets_served(client: TestClient) -> None:
    """Static assets like CSS, JS, and SVG icons are accessible."""
    for path in ["/static/style.css", "/static/app.js", "/static/icon.svg"]:
        resp = client.get(path)
        assert resp.status_code == 200, f"Failed fetching {path}"
