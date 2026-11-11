"""High-level authentication lifecycle, session issuance, rate limiting, and audit logging."""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import pyotp

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
from remote_control.auth.storage import AuthStorage
from remote_control.config import RemoteControlConfig
from remote_control.models import AuditEvent, DeviceModel, OperatorModel, SessionModel

logger = logging.getLogger(__name__)


class AuthenticationError(Exception):
    """Raised when authentication credentials or tokens are invalid."""


class RateLimitError(Exception):
    """Raised when request rate limits or lockout thresholds are exceeded."""


class AuthService:
    """Coordinates authentication, credentials, devices, sessions, and audit records."""

    def __init__(self, storage: AuthStorage, config: Optional[RemoteControlConfig] = None) -> None:
        self.storage = storage
        self.config = config or RemoteControlConfig()

    def is_bootstrapped(self) -> bool:
        """Returns True if the single operator account has been created."""
        return self.storage.get_operator() is not None

    def bootstrap(
        self,
        username: str,
        password: str,
        totp_secret: Optional[str] = None,
        ip_address: str = "127.0.0.1",
    ) -> Tuple[OperatorModel, str, str]:
        """
        Bootstrap the single operator identity via local console.
        Returns: (OperatorModel, totp_secret, provisioning_uri)
        """
        if self.is_bootstrapped():
            raise AuthenticationError("Operator identity already bootstrapped. Use password/totp reset instead.")

        clean_user = username.strip()
        if not clean_user:
            raise ValueError("Username cannot be empty.")

        p_hash = hash_password(password)
        secret = totp_secret or generate_totp_secret()
        operator_id = f"op_{uuid.uuid4().hex[:12]}"

        op = self.storage.create_operator(
            operator_id=operator_id,
            username=clean_user,
            password_hash=p_hash,
            totp_secret=secret,
        )

        uri = get_totp_provisioning_uri(secret, clean_user)

        self.storage.record_audit_event(
            AuditEvent(
                timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                actor_id=operator_id,
                action="bootstrap",
                decision="allow",
                ip_address=ip_address,
                details=f"Operator '{clean_user}' bootstrapped successfully.",
            )
        )

        return op, secret, uri

    def authenticate_login(
        self,
        username: str,
        password: str,
        totp_code: str,
        device_id: Optional[str] = None,
        device_name: str = "Mobile Browser",
        ip_address: str = "",
        user_agent: str = "",
    ) -> Tuple[SessionModel, str]:
        """
        Authenticate credentials + TOTP, enforce rate limiting, issue session + raw cookie token.
        Returns: (SessionModel, raw_session_token)
        """
        now_ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        # 1. Rate limiting check
        failed_count = self.storage.get_recent_failed_attempts(
            ip_address, window_seconds=self.config.lockout_duration_seconds
        )
        if failed_count >= self.config.max_login_attempts:
            self.storage.record_audit_event(
                AuditEvent(
                    timestamp=now_ts,
                    actor_id=username or "unknown",
                    action="login",
                    decision="deny",
                    ip_address=ip_address,
                    details=f"Rate limit exceeded ({failed_count} failed attempts in lockout window).",
                )
            )
            raise RateLimitError(
                f"Too many failed login attempts. Account locked for {self.config.lockout_duration_seconds // 60} minutes."
            )

        # 2. Check operator existence
        raw_op = self.storage.get_operator()
        if not raw_op:
            self.storage.record_login_attempt(ip_address, success=False)
            raise AuthenticationError("Remote control service is not bootstrapped.")

        # 3. Verify username and password
        user_match = constant_time_compare(raw_op["username"].lower(), username.strip().lower())
        pwd_match = verify_password(raw_op["password_hash"], password)

        if not user_match or not pwd_match:
            self.storage.record_login_attempt(ip_address, success=False)
            self.storage.record_audit_event(
                AuditEvent(
                    timestamp=now_ts,
                    actor_id=username or "unknown",
                    action="login",
                    decision="deny",
                    ip_address=ip_address,
                    details="Invalid username or password.",
                )
            )
            raise AuthenticationError("Invalid username or password.")

        # 4. Verify TOTP with replay protection
        secret = raw_op["totp_secret"]
        totp_obj = pyotp.TOTP(secret)
        current_timestep = int(time.time() // 30)

        # Reject code reuse within the active timestep window
        if self.storage.is_totp_timestep_used(raw_op["operator_id"], current_timestep):
            self.storage.record_login_attempt(ip_address, success=False)
            self.storage.record_audit_event(
                AuditEvent(
                    timestamp=now_ts,
                    actor_id=raw_op["operator_id"],
                    action="login",
                    decision="deny",
                    ip_address=ip_address,
                    details="Rejected duplicate/replayed TOTP code.",
                )
            )
            raise AuthenticationError("TOTP code has already been used. Please wait for the next code.")

        totp_valid = verify_totp(secret, totp_code, valid_window=1)
        if not totp_valid:
            self.storage.record_login_attempt(ip_address, success=False)
            self.storage.record_audit_event(
                AuditEvent(
                    timestamp=now_ts,
                    actor_id=raw_op["operator_id"],
                    action="login",
                    decision="deny",
                    ip_address=ip_address,
                    details="Invalid TOTP two-factor verification code.",
                )
            )
            raise AuthenticationError("Invalid two-factor verification code.")

        # Mark timestep as consumed to prevent replay
        self.storage.mark_totp_timestep_used(raw_op["operator_id"], current_timestep)

        # 5. Device registration & validation
        eff_device_id = device_id or f"dev_{uuid.uuid4().hex[:12]}"
        device = self.storage.get_device(eff_device_id)
        if device and device.is_revoked:
            self.storage.record_audit_event(
                AuditEvent(
                    timestamp=now_ts,
                    actor_id=raw_op["operator_id"],
                    device_id=eff_device_id,
                    action="login",
                    decision="deny",
                    ip_address=ip_address,
                    details=f"Device '{eff_device_id}' has been permanently revoked.",
                )
            )
            raise AuthenticationError("This device has been revoked by the operator.")

        dev = self.storage.register_or_touch_device(eff_device_id, raw_op["operator_id"], device_name)

        # 6. Session Rotation: Revoke existing sessions for this device
        self.storage.revoke_all_sessions_for_device(dev.device_id)

        # 7. Issue session token and CSRF token
        raw_token = generate_opaque_token(32)
        token_hash = hash_token(raw_token)
        csrf_token = generate_opaque_token(32)
        session_id = f"sess_{uuid.uuid4().hex[:16]}"
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=self.config.session_max_age_seconds)
        ).isoformat().replace("+00:00", "Z")

        session = self.storage.create_session(
            session_id=session_id,
            session_id_hash=token_hash,
            operator_id=raw_op["operator_id"],
            device_id=dev.device_id,
            csrf_token=csrf_token,
            expires_at=expires_at,
            user_agent=user_agent,
            ip_address=ip_address,
        )

        # Record success
        self.storage.record_login_attempt(ip_address, success=True)
        self.storage.record_audit_event(
            AuditEvent(
                timestamp=now_ts,
                actor_id=raw_op["operator_id"],
                device_id=dev.device_id,
                action="login",
                decision="allow",
                ip_address=ip_address,
                details=f"Successful login for device '{dev.device_name}' ({dev.device_id}).",
            )
        )

        return session, raw_token

    def validate_session(self, raw_token: Optional[str], ip_address: str = "") -> Optional[SessionModel]:
        """Validate session token from cookie, checking revocation, expiry, and device status."""
        if not raw_token:
            return None

        token_hash = hash_token(raw_token)
        session = self.storage.get_session_by_hash(token_hash)
        if not session:
            return None

        if not session.is_active:
            return None

        # Check device revocation
        device = self.storage.get_device(session.device_id)
        if not device or device.is_revoked:
            self.storage.revoke_session(session.session_id)
            return None

        # Sliding window touch: update last_seen_at
        now_utc = datetime.now(timezone.utc)
        now_iso = now_utc.isoformat().replace("+00:00", "Z")
        # Check idle timeout
        try:
            last_seen = datetime.fromisoformat(session.last_seen_at.replace("Z", "+00:00"))
            if (now_utc - last_seen).total_seconds() > self.config.session_idle_timeout_seconds:
                self.storage.revoke_session(session.session_id)
                return None
        except Exception:
            pass

        self.storage.touch_session(session.session_id, session.expires_at, ip_address=ip_address)
        return session

    def revoke_session(self, session_id: str, actor_id: str, ip_address: str = "") -> bool:
        """Revoke a single active session."""
        success = self.storage.revoke_session(session_id)
        now_ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        self.storage.record_audit_event(
            AuditEvent(
                timestamp=now_ts,
                actor_id=actor_id,
                action="session_revoke",
                decision="allow" if success else "deny",
                ip_address=ip_address,
                details=f"Session '{session_id}' revoked.",
            )
        )
        return success

    def revoke_device(self, device_id: str, actor_id: str, ip_address: str = "") -> bool:
        """Permanently revoke a device and all its active sessions."""
        success = self.storage.revoke_device(device_id)
        now_ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        self.storage.record_audit_event(
            AuditEvent(
                timestamp=now_ts,
                actor_id=actor_id,
                device_id=device_id,
                action="device_revoke",
                decision="allow" if success else "deny",
                ip_address=ip_address,
                details=f"Device '{device_id}' revoked and sessions terminated.",
            )
        )
        return success

    def reset_password(self, new_password: str, actor_id: str = "console", ip_address: str = "127.0.0.1") -> bool:
        """Reset operator password from local authenticated console."""
        raw_op = self.storage.get_operator()
        if not raw_op:
            raise AuthenticationError("Operator not bootstrapped.")

        p_hash = hash_password(new_password)
        success = self.storage.update_operator_password(raw_op["operator_id"], p_hash)
        # Invalidate all existing sessions on password change
        self.storage.revoke_all_sessions_for_operator(raw_op["operator_id"])

        now_ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        self.storage.record_audit_event(
            AuditEvent(
                timestamp=now_ts,
                actor_id=actor_id,
                action="password_reset",
                decision="allow" if success else "deny",
                ip_address=ip_address,
                details="Operator password reset via local CLI; all active sessions invalidated.",
            )
        )
        return success

    def reset_totp(self, actor_id: str = "console", ip_address: str = "127.0.0.1") -> Tuple[str, str]:
        """Regenerate operator TOTP seed from local authenticated console."""
        raw_op = self.storage.get_operator()
        if not raw_op:
            raise AuthenticationError("Operator not bootstrapped.")

        secret = generate_totp_secret()
        self.storage.update_operator_totp(raw_op["operator_id"], secret)
        uri = get_totp_provisioning_uri(secret, raw_op["username"])

        now_ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        self.storage.record_audit_event(
            AuditEvent(
                timestamp=now_ts,
                actor_id=actor_id,
                action="totp_reset",
                decision="allow",
                ip_address=ip_address,
                details="Operator TOTP seed regenerated via local CLI.",
            )
        )
        return secret, uri
