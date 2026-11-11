"""Tests for Mobile PWA dashboard UI, static assets, and DOM-safe action rendering."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from remote_control.app import create_app
from remote_control.config import RemoteControlConfig


@pytest.fixture
def pwa_client(tmp_path: Path):
    cfg = RemoteControlConfig(
        auth_db_path=tmp_path / "auth.db",
        notifications_db_path=tmp_path / "notif.db",
        healthchecks_config_path=tmp_path / "hc.json",
        allowed_hosts=["127.0.0.1", "localhost", "testserver"],
        allowed_origins=["http://testserver"],
    )
    app = create_app(cfg)
    return TestClient(app, base_url="http://testserver")


def test_static_pwa_shell_assets_served(pwa_client: TestClient):
    """PWA static assets (index, manifest, sw, app.js) are properly served with security headers."""
    # 1. Root index
    res_index = pwa_client.get("/")
    assert res_index.status_code == 200
    assert "Remote Control" in res_index.text
    assert "data-tab=\"actions\"" in res_index.text
    assert "tab-actions" in res_index.text
    assert "action-modal" in res_index.text
    assert res_index.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'self'" in res_index.headers["Content-Security-Policy"]

    # 2. Manifest
    res_manifest = pwa_client.get("/manifest.json")
    assert res_manifest.status_code == 200
    assert res_manifest.headers["content-type"] == "application/manifest+json"

    # 3. Service Worker
    res_sw = pwa_client.get("/sw.js")
    assert res_sw.status_code == 200
    assert "no-cache" in res_sw.headers["cache-control"]

    # 4. App JavaScript
    res_js = pwa_client.get("/static/app.js")
    assert res_js.status_code == 200
    assert "loadActions" in res_js.text
    assert "promptActionExecution" in res_js.text
    assert "promptAcknowledgeIncident" in res_js.text


def test_app_js_strict_dom_safety():
    """Verify app.js does not contain innerHTML or dangerous DOM insertion vectors."""
    app_js_path = (
        Path(__file__).resolve().parent.parent
        / "remote_control"
        / "static"
        / "app.js"
    )
    assert app_js_path.is_file()
    content = app_js_path.read_text(encoding="utf-8")

    # Strict check: zero innerHTML occurrences
    assert "innerHTML" not in content
    assert "outerHTML" not in content
    assert "document.write" not in content
