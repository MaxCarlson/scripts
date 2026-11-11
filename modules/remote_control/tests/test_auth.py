"""Tests for remote_control authentication, sessions, TOTP, and lockout mechanisms."""

from __future__ import annotations

import time
from typing import Any, Tuple

import pyotp
import pytest
from fastapi.testclient import TestClient

from remote_control.auth.crypto import (
    generate_opaque_token,
    hash_password,
    hash_token,
    verify_password,
    verify_totp,
)
from remote_control.auth.service import AuthService, AuthenticationError, RateLimitError


def test_crypto_password_hashing() -> None:
    """Argon2id produces non-reversible hash and correctly verifies valid passwords."""
    pwd = "CorrectHorseBatteryStaple123!"
    p_hash = hash_password(pwd)
    assert p_hash.startswith("$argon2id$")
    assert verify_password(p_hash, pwd) is True
    assert verify_password(p_hash, "WrongPassword123!") is False
    assert verify_password(p_hash, "") is False


def test_crypto_totp_verification() -> None:
    """TOTP verification adheres to RFC 6238 with 1-step window tolerance."""
    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)

    now_ts = int(time.time())
    code_now = totp.at(now_ts)

    # Current step verifies
    valid = verify_totp(secret, code_now, valid_window=1)
    assert valid is True

    # Invalid code fails
    assert verify_totp(secret, "000000", valid_window=1) is False

    # Older than tolerance window fails
    old_code = totp.at(now_ts - 90)
    assert verify_totp(secret, old_code, valid_window=1) is False


def test_bootstrap_single_operator_enforcement(auth_service: AuthService) -> None:
    """Exactly one operator identity can be bootstrapped; subsequent attempts fail."""
    assert auth_service.is_bootstrapped() is False

    op, secret, uri = auth_service.bootstrap(username="admin", password="ValidPassword123!")
    assert op.username == "admin"
    assert len(secret) == 32
    assert "otpauth://totp/" in uri
    assert auth_service.is_bootstrapped() is True

    # Second bootstrap must fail
    with pytest.raises(AuthenticationError, match="already bootstrapped"):
        auth_service.bootstrap(username="admin2", password="AnotherPassword123!")


def test_auth_service_totp_replay_prevention(auth_service: AuthService) -> None:
    """Replaying the exact same TOTP code in the same timestep window is rejected."""
    op, secret, uri = auth_service.bootstrap(username="admin", password="ValidPassword123!")
    totp = pyotp.TOTP(secret)
    code = totp.now()

    # First login attempt succeeds
    session, token = auth_service.authenticate_login(
        username="admin",
        password="ValidPassword123!",
        totp_code=code,
        device_id="dev-1",
        device_name="Phone",
        ip_address="127.0.0.1",
        user_agent="TestAgent",
    )
    assert session is not None
    assert token is not None

    # Immediate second login attempt with the same code is rejected (replay prevention)
    with pytest.raises(AuthenticationError, match="already been used"):
        auth_service.authenticate_login(
            username="admin",
            password="ValidPassword123!",
            totp_code=code,
            device_id="dev-1",
            device_name="Phone",
            ip_address="127.0.0.1",
            user_agent="TestAgent",
        )


def test_totp_drift_windows_consumed_and_no_cross_window_replay(auth_service: AuthService) -> None:
    """Matches in previous and next drift windows consume the exact matched timestep."""
    op, secret, uri = auth_service.bootstrap(username="admin", password="ValidPassword123!")
    totp = pyotp.TOTP(secret)

    now = time.time()
    prev_step = int(now // 30) - 1
    prev_code = totp.generate_otp(prev_step)

    # Login with previous window code
    sess1, tok1 = auth_service.authenticate_login(
        username="admin",
        password="ValidPassword123!",
        totp_code=prev_code,
        device_id="dev-prev",
        device_name="Phone",
        ip_address="127.0.0.1",
        user_agent="TestAgent",
    )
    assert sess1 is not None

    # Replay of prev_code is rejected
    with pytest.raises(AuthenticationError, match="already been used"):
        auth_service.authenticate_login(
            username="admin",
            password="ValidPassword123!",
            totp_code=prev_code,
            device_id="dev-prev-replay",
            device_name="Phone",
            ip_address="127.0.0.1",
            user_agent="TestAgent",
        )

    # Next window code can be consumed
    next_step = int(now // 30) + 1
    next_code = totp.generate_otp(next_step)
    sess2, tok2 = auth_service.authenticate_login(
        username="admin",
        password="ValidPassword123!",
        totp_code=next_code,
        device_id="dev-next",
        device_name="Phone",
        ip_address="127.0.0.1",
        user_agent="TestAgent",
    )
    assert sess2 is not None

    # Replay of next_code is rejected
    with pytest.raises(AuthenticationError, match="already been used"):
        auth_service.authenticate_login(
            username="admin",
            password="ValidPassword123!",
            totp_code=next_code,
            device_id="dev-next-replay",
            device_name="Phone",
            ip_address="127.0.0.1",
            user_agent="TestAgent",
        )


def test_totp_concurrent_consumption_atomicity(auth_service: AuthService) -> None:
    """Concurrent login attempts with the same OTP allow exactly one winner."""
    import concurrent.futures

    op, secret, uri = auth_service.bootstrap(username="admin", password="ValidPassword123!")
    totp = pyotp.TOTP(secret)
    code = totp.now()

    results = []
    errors = []

    def attempt_login(worker_id: int):
        try:
            sess, tok = auth_service.authenticate_login(
                username="admin",
                password="ValidPassword123!",
                totp_code=code,
                device_id=f"dev-concurrent-{worker_id}",
                device_name="Concurrent Worker",
                ip_address=f"127.0.0.{worker_id}",
                user_agent="ConcurrentAgent",
            )
            return True, None
        except Exception as exc:
            return False, exc

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(attempt_login, i) for i in range(1, 5)]
        for f in concurrent.futures.as_completed(futures):
            success, err = f.result()
            if success:
                results.append(True)
            else:
                errors.append(err)

    # Exactly one concurrent worker must succeed
    assert len(results) == 1
    # Remaining 3 workers must be rejected with replay error
    assert len(errors) == 3
    assert all("already been used" in str(e) for e in errors)


def test_auth_service_brute_force_lockout(auth_service: AuthService) -> None:
    """Repeated failed attempts trigger temporary rate limit lockout."""
    op, secret, uri = auth_service.bootstrap(username="admin", password="ValidPassword123!")

    # 5 failed password attempts
    for _ in range(5):
        with pytest.raises(AuthenticationError):
            auth_service.authenticate_login(
                username="admin",
                password="WrongPassword!",
                totp_code="123456",
                device_id="dev-1",
                device_name="Phone",
                ip_address="127.0.0.1",
                user_agent="TestAgent",
            )

    # 6th attempt is locked out immediately with RateLimitError
    with pytest.raises(RateLimitError, match="locked"):
        auth_service.authenticate_login(
            username="admin",
            password="ValidPassword123!",
            totp_code="123456",
            device_id="dev-1",
            device_name="Phone",
            ip_address="127.0.0.1",
            user_agent="TestAgent",
        )


def test_session_lifecycle_and_revocation(auth_service: AuthService) -> None:
    """Sessions can be validated, revoked directly, or revoked by device ID."""
    op, secret, uri = auth_service.bootstrap(username="admin", password="ValidPassword123!")
    totp = pyotp.TOTP(secret)

    session, raw_token = auth_service.authenticate_login(
        username="admin",
        password="ValidPassword123!",
        totp_code=totp.now(),
        device_id="dev-phone",
        device_name="Phone",
        ip_address="127.0.0.1",
        user_agent="TestAgent",
    )

    # Validate active session
    validated = auth_service.validate_session(raw_token)
    assert validated is not None
    assert validated.session_id == session.session_id

    # Revoke session
    revoked = auth_service.revoke_session(session.session_id, actor_id="admin")
    assert revoked is True

    # Validating revoked session returns None
    assert auth_service.validate_session(raw_token) is None


def test_device_revocation_cascades_to_sessions(auth_service: AuthService) -> None:
    """Permanently revoking a device revokes all sessions originating from it."""
    op, secret, uri = auth_service.bootstrap(username="admin", password="ValidPassword123!")
    totp = pyotp.TOTP(secret)

    session, raw_token = auth_service.authenticate_login(
        username="admin",
        password="ValidPassword123!",
        totp_code=totp.now(),
        device_id="dev-tablet",
        device_name="Tablet",
        ip_address="127.0.0.1",
        user_agent="TestAgent",
    )
    assert auth_service.validate_session(raw_token) is not None

    # Revoke device
    auth_service.revoke_device("dev-tablet", actor_id="admin")

    # Session is now invalid
    assert auth_service.validate_session(raw_token) is None


def test_reset_password_invalidates_all_active_sessions(auth_service: AuthService) -> None:
    """Password reset immediately revokes all existing sessions."""
    op, secret, uri = auth_service.bootstrap(username="admin", password="OldPassword123!")
    totp = pyotp.TOTP(secret)

    session, raw_token = auth_service.authenticate_login(
        username="admin",
        password="OldPassword123!",
        totp_code=totp.now(),
        device_id="dev-laptop",
        device_name="Laptop",
        ip_address="127.0.0.1",
        user_agent="TestAgent",
    )
    assert auth_service.validate_session(raw_token) is not None

    # Reset password
    auth_service.reset_password("NewSecurePassword456!")

    # Previous session is invalidated
    assert auth_service.validate_session(raw_token) is None


def test_fail_closed_unbootstrapped_login(client: TestClient) -> None:
    """Login attempts against an unbootstrapped service are cleanly rejected."""
    resp = client.post(
        "/api/auth/login",
        json={
            "username": "admin",
            "password": "Password123!",
            "totp_code": "123456",
        },
    )
    assert resp.status_code == 503
    data = resp.json()
    assert data["error"] == "not_bootstrapped"
