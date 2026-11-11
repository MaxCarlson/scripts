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


def test_exact_origin_same_host_different_port_rejected(authenticated_client: Tuple[TestClient, str]) -> None:
    """Requests from differing ports on the same host are rejected as cross-origin."""
    client, csrf_token = authenticated_client

    resp = client.post(
        "/api/auth/logout",
        headers={
            "Origin": "http://127.0.0.1:3000",
            "X-CSRF-Token": csrf_token,
        },
    )
    assert resp.status_code == 403
    assert "Cross-origin" in resp.json().get("message", "")


def test_exact_origin_http_to_https_scheme_mismatch_rejected(authenticated_client: Tuple[TestClient, str]) -> None:
    """Requests with scheme mismatch (https origin to http server) are rejected."""
    client, csrf_token = authenticated_client

    resp = client.post(
        "/api/auth/logout",
        headers={
            "Origin": "https://127.0.0.1:8443",
            "X-CSRF-Token": csrf_token,
        },
    )
    assert resp.status_code == 403
    assert "Cross-origin" in resp.json().get("message", "")


def test_origin_null_rejected(authenticated_client: Tuple[TestClient, str]) -> None:
    """Origin: null is strictly rejected on state-changing requests."""
    client, csrf_token = authenticated_client

    resp = client.post(
        "/api/auth/logout",
        headers={
            "Origin": "null",
            "X-CSRF-Token": csrf_token,
        },
    )
    assert resp.status_code == 403
    assert "null" in resp.json().get("message", "").lower()


def test_sec_fetch_site_cross_site_rejected(authenticated_client: Tuple[TestClient, str]) -> None:
    """Sec-Fetch-Site: cross-site requests are rejected unconditionally."""
    client, csrf_token = authenticated_client

    resp = client.post(
        "/api/auth/logout",
        headers={
            "Sec-Fetch-Site": "cross-site",
            "X-CSRF-Token": csrf_token,
        },
    )
    assert resp.status_code == 403
    assert "Cross-site" in resp.json().get("message", "")


def test_proxy_header_trust_boundaries(authenticated_client: Tuple[TestClient, str]) -> None:
    """Untrusted client IPs cannot spoof client IP or protocol via X-Forwarded headers."""
    client, _ = authenticated_client
    from remote_control.api.dependencies import get_client_ip, get_effective_scheme
    from starlette.requests import Request

    # Create dummy scope with untrusted socket peer
    scope_untrusted = {
        "type": "http",
        "client": ("198.51.100.1", 50000),
        "headers": [
            (b"x-forwarded-for", b"203.0.113.195"),
            (b"x-forwarded-proto", b"https"),
        ],
        "app": client.app,
    }
    req_untrusted = Request(scope_untrusted)
    assert get_client_ip(req_untrusted) == "198.51.100.1"  # Not spoofed!

    # Create dummy scope with trusted proxy peer (127.0.0.1)
    scope_trusted = {
        "type": "http",
        "client": ("127.0.0.1", 50000),
        "headers": [
            (b"x-forwarded-for", b"203.0.113.195"),
            (b"x-forwarded-proto", b"https"),
        ],
        "app": client.app,
    }
    req_trusted = Request(scope_trusted)
    assert get_client_ip(req_trusted) == "203.0.113.195"  # Trusted forwarded IP!
    assert get_effective_scheme(req_trusted) == "https"


def test_production_https_cookie_enforces_host_prefix_and_secure(
    test_config,
    bootstrapped_operator: Tuple[Any, str, str],
) -> None:
    """Production mode with cookie_secure=True always issues __Host- prefixed Secure cookies."""
    import pyotp
    from remote_control.app import create_app
    from remote_control.config import RemoteControlConfig

    prod_config = RemoteControlConfig(
        host="127.0.0.1",
        port=8443,
        auth_db_path=test_config.auth_db_path,
        notifications_db_path=test_config.notifications_db_path,
        healthchecks_config_path=test_config.healthchecks_config_path,
        cookie_secure=True,  # Production mode
        allowed_hosts=["127.0.0.1", "testserver"],
    )
    prod_app = create_app(prod_config)
    with TestClient(prod_app, base_url="https://127.0.0.1:8443") as prod_client:
        op, totp_secret, password = bootstrapped_operator
        totp = pyotp.TOTP(totp_secret)

        resp = prod_client.post(
            "/api/auth/login",
            json={
                "username": op.username,
                "password": password,
                "totp_code": totp.now(),
                "device_id": "prod-device",
            },
        )
        assert resp.status_code == 200
        set_cookie = resp.headers.get("set-cookie", "")
        assert "__Host-rc_session=" in set_cookie
        assert "Secure" in set_cookie
        assert "HttpOnly" in set_cookie
        assert "samesite=strict" in set_cookie.lower()


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
