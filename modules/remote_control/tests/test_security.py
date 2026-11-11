"""Tests for remote_control security boundaries, CSRF, CSP, host checks, and redaction."""

from __future__ import annotations

from typing import Any, Tuple
import pytest
from fastapi.testclient import TestClient


def test_security_headers_present(client: TestClient) -> None:
    """Security headers (CSP, X-Frame-Options, nosniff) are enforced on responses."""
    resp = client.get("/")
    assert resp.status_code == 200
    headers = resp.headers

    assert "content-security-policy" in headers
    csp = headers["content-security-policy"]
    assert "default-src 'self'" in csp
    assert "'unsafe-eval'" not in csp

    assert headers.get("x-frame-options") == "DENY"
    assert headers.get("x-content-type-options") == "nosniff"
    assert headers.get("referrer-policy") == "strict-origin-when-cross-origin"


def test_api_cache_control_headers(authenticated_client: Tuple[TestClient, str]) -> None:
    """All /api/* responses must enforce no-store cache control."""
    client, csrf_token = authenticated_client
    resp = client.get("/api/summary")
    assert resp.status_code == 200
    assert "no-store" in resp.headers.get("cache-control", "").lower()


def test_host_header_validation(authenticated_client: Tuple[TestClient, str]) -> None:
    """Requests with spoofed or untrusted Host headers are rejected."""
    client, _ = authenticated_client

    # Disallowed host
    resp = client.get("/api/summary", headers={"Host": "attacker.com"})
    assert resp.status_code == 400
    assert "attacker.com" in resp.json().get("message", "")

    # Allowed host
    resp_ok = client.get("/api/summary", headers={"Host": "127.0.0.1:8443"})
    assert resp_ok.status_code == 200


def test_origin_header_validation(authenticated_client: Tuple[TestClient, str]) -> None:
    """Cross-origin POST requests with foreign Origin headers are rejected."""
    client, csrf_token = authenticated_client

    resp = client.post(
        "/api/auth/logout",
        headers={
            "Origin": "https://malicious-website.com",
            "X-CSRF-Token": csrf_token,
        },
    )
    assert resp.status_code == 403
    assert "Cross-origin" in resp.json().get("message", "")


def test_csrf_token_enforcement_on_mutations(authenticated_client: Tuple[TestClient, str]) -> None:
    """State-changing requests without or with mismatched CSRF token are rejected."""
    client, csrf_token = authenticated_client

    # 1. Missing CSRF token
    resp_missing = client.post("/api/auth/devices/dev-fake/revoke")
    assert resp_missing.status_code == 403
    assert resp_missing.json().get("error") == "csrf_validation_failed"

    # 2. Invalid CSRF token
    resp_bad = client.post(
        "/api/auth/devices/dev-fake/revoke",
        headers={"X-CSRF-Token": "invalid-csrf-token-1234"},
    )
    assert resp_bad.status_code == 403
    assert resp_bad.json().get("error") == "csrf_validation_failed"

    # 3. Valid CSRF token proceeds (returns 404 for non-existent device)
    resp_valid = client.post(
        "/api/auth/devices/dev-fake/revoke",
        headers={"X-CSRF-Token": csrf_token},
    )
    assert resp_valid.status_code == 404
    assert resp_valid.json().get("error") == "device_not_found"


def test_cookie_security_attributes(
    client: TestClient,
    bootstrapped_operator: Tuple[Any, str, str],
) -> None:
    """Authentication session cookies enforce HttpOnly, SameSite, and Path=/."""
    import pyotp

    op, totp_secret, password = bootstrapped_operator
    totp = pyotp.TOTP(totp_secret)

    resp = client.post(
        "/api/auth/login",
        json={
            "username": op.username,
            "password": password,
            "totp_code": totp.now(),
            "device_id": "test-sec-dev",
        },
    )
    assert resp.status_code == 200
    set_cookie = resp.headers.get("set-cookie", "")
    assert "rc_session=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=" in set_cookie
    assert "Path=/" in set_cookie


def test_no_secret_leaks_in_responses(authenticated_client: Tuple[TestClient, str]) -> None:
    """Password hash, TOTP seed, and full ping URLs are never leaked in API output."""
    client, _ = authenticated_client

    # Check session endpoint
    resp_sess = client.get("/api/auth/session")
    assert resp_sess.status_code == 200
    text_sess = resp_sess.text
    assert "$argon2id$" not in text_sess
    assert "totp_secret" not in text_sess
    assert "password" not in text_sess

    # Check heartbeat endpoint
    resp_hb = client.get("/api/heartbeat")
    assert resp_hb.status_code == 200
    hb_data = resp_hb.json()["heartbeat"]
    ping_url = hb_data.get("ping_url_redacted", "")
    if ping_url:
        assert "[REDACTED]" in ping_url
