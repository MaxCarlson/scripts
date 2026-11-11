"""Authentication and session management package."""

from remote_control.auth.crypto import (
    constant_time_compare,
    generate_opaque_token,
    generate_totp_secret,
    get_totp_provisioning_uri,
    hash_password,
    hash_token,
    verify_password,
    verify_totp,
)
from remote_control.auth.service import (
    AuthenticationError,
    AuthService,
    RateLimitError,
)
from remote_control.auth.storage import AuthStorage

__all__ = [
    "AuthService",
    "AuthStorage",
    "AuthenticationError",
    "RateLimitError",
    "constant_time_compare",
    "generate_opaque_token",
    "generate_totp_secret",
    "get_totp_provisioning_uri",
    "hash_password",
    "hash_token",
    "verify_password",
    "verify_totp",
]
