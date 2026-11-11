"""Cryptographic primitives, password hashing, and TOTP verification."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from typing import List, Optional

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# Argon2id with OWASP recommended configuration for sensitive web authentication
_HASHER = PasswordHasher(
    time_cost=3,
    memory_cost=65536,  # 64 MiB
    parallelism=4,
    hash_len=32,
)


def hash_password(password: str) -> str:
    """Hash password using Argon2id with per-password salt."""
    if not password or len(password) < 8:
        raise ValueError("Password must be at least 8 characters.")
    return _HASHER.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Verify password against Argon2id hash in constant time."""
    if not password_hash or not password:
        return False
    try:
        return _HASHER.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def generate_opaque_token(nbytes: int = 32) -> str:
    """Generate high-entropy cryptographically secure URL-safe token."""
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    """Calculate SHA-256 digest of token for secure database storage."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def constant_time_compare(val_a: str, val_b: str) -> bool:
    """Compare two string secrets in constant time."""
    return hmac.compare_digest(val_a.encode("utf-8"), val_b.encode("utf-8"))


def generate_totp_secret() -> str:
    """Generate base32 TOTP seed for operator enrollment."""
    return pyotp.random_base32()


def get_totp_provisioning_uri(secret: str, username: str) -> str:
    """Generate standard otpauth:// URI for authenticator apps."""
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=username, issuer_name="Scripts Remote Control")


def find_matching_totp_timesteps(
    secret: str,
    code: str,
    valid_window: int = 1,
    current_time: Optional[float] = None,
) -> List[int]:
    """
    Find all timesteps within [current - valid_window, current + valid_window] matching the code.
    Returns matching timesteps sorted by distance from current timestep (closest first).
    """
    if not secret or not code:
        return []
    clean_code = str(code).strip().replace(" ", "")
    if len(clean_code) != 6 or not clean_code.isdigit():
        return []

    totp = pyotp.TOTP(secret)
    now = current_time if current_time is not None else time.time()
    current_step = int(now // 30)

    candidates = list(range(current_step - valid_window, current_step + valid_window + 1))
    candidates.sort(key=lambda s: abs(s - current_step))

    matches: List[int] = []
    for step in candidates:
        expected = totp.generate_otp(step)
        if constant_time_compare(clean_code, expected):
            matches.append(step)

    return matches


def verify_totp(secret: str, code: str, valid_window: int = 1) -> bool:
    """Verify 6-digit TOTP code allowing up to +/- valid_window timestep drift."""
    return len(find_matching_totp_timesteps(secret, code, valid_window=valid_window)) > 0
