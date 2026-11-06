from __future__ import annotations

import os

import pytest

from resource_coordinator.core import operator_credentials as credentials


def test_missing_credential_is_created_once_and_never_printed(tmp_path, monkeypatch):
    path = tmp_path / "operator-token"
    monkeypatch.setenv("RESOURCE_COORDINATOR_TOKEN_FILE", str(path))
    monkeypatch.delenv("RESOURCE_COORDINATOR_OPERATOR_TOKEN", raising=False)
    secured = []
    monkeypatch.setattr(credentials, "_secure_path", lambda target: secured.append(target))

    first = credentials.load_or_create_token()
    second = credentials.load_or_create_token()

    assert len(first) >= 64
    assert second == first
    assert path.read_text(encoding="ascii") == first
    assert secured == [path.parent, path]


def test_environment_override_takes_precedence_without_rewriting_file(tmp_path, monkeypatch):
    path = tmp_path / "operator-token"
    path.write_text("stored-token", encoding="ascii")
    monkeypatch.setenv("RESOURCE_COORDINATOR_TOKEN_FILE", str(path))
    monkeypatch.setenv("RESOURCE_COORDINATOR_OPERATOR_TOKEN", "override-token")

    assert credentials.load_or_create_token() == "override-token"
    assert path.read_text(encoding="ascii") == "stored-token"


def test_credential_reads_do_not_rewrite_acl(tmp_path, monkeypatch):
    path = tmp_path / "operator-token"
    path.write_text("A" * 64, encoding="ascii")
    monkeypatch.setenv("RESOURCE_COORDINATOR_TOKEN_FILE", str(path))
    monkeypatch.delenv("RESOURCE_COORDINATOR_OPERATOR_TOKEN", raising=False)

    def forbidden(_target):
        raise AssertionError("read path must not mutate ACLs")

    monkeypatch.setattr(credentials, "_secure_path", forbidden)
    assert credentials.load_token() == "A" * 64


def test_corrupt_credential_fails_closed_without_regeneration(tmp_path, monkeypatch):
    path = tmp_path / "operator-token"
    path.write_text("not-a-valid-generated-token\n", encoding="ascii")
    monkeypatch.setenv("RESOURCE_COORDINATOR_TOKEN_FILE", str(path))
    monkeypatch.delenv("RESOURCE_COORDINATOR_OPERATOR_TOKEN", raising=False)

    with pytest.raises(credentials.CredentialError, match="invalid"):
        credentials.load_or_create_token()
    assert path.read_text(encoding="ascii") == "not-a-valid-generated-token\n"


def test_acl_failure_does_not_leave_usable_credential(tmp_path, monkeypatch):
    path = tmp_path / "operator-token"
    monkeypatch.setenv("RESOURCE_COORDINATOR_TOKEN_FILE", str(path))
    monkeypatch.delenv("RESOURCE_COORDINATOR_OPERATOR_TOKEN", raising=False)

    def fail_acl(_target):
        raise credentials.CredentialError("ACL could not be restricted")

    monkeypatch.setattr(credentials, "_secure_path", fail_acl)
    with pytest.raises(credentials.CredentialError, match="ACL"):
        credentials.load_or_create_token()
    assert not path.exists()


def test_reinitialize_requires_explicit_request_and_rotates_token(tmp_path, monkeypatch):
    path = tmp_path / "operator-token"
    monkeypatch.setenv("RESOURCE_COORDINATOR_TOKEN_FILE", str(path))
    monkeypatch.delenv("RESOURCE_COORDINATOR_OPERATOR_TOKEN", raising=False)
    monkeypatch.setattr(credentials, "_secure_path", lambda _target: None)
    original = credentials.load_or_create_token()

    replacement = credentials.reinitialize_token(coordinator_is_running=False)

    assert replacement != original
    assert credentials.load_or_create_token() == replacement
    with pytest.raises(credentials.CredentialError, match="(?i)stop"):
        credentials.reinitialize_token(coordinator_is_running=True)


def test_doctor_reports_environment_mismatch_without_rotating(tmp_path, monkeypatch):
    path = tmp_path / "operator-token"
    path.write_text("A" * 64, encoding="ascii")
    monkeypatch.setenv("RESOURCE_COORDINATOR_TOKEN_FILE", str(path))
    monkeypatch.setenv("RESOURCE_COORDINATOR_OPERATOR_TOKEN", "wrong-override")
    monkeypatch.setattr(credentials, "_acl_is_restricted", lambda _path: True)

    report = credentials.doctor()

    assert report["credential_file_readable"] is True
    assert report["environment_override_matches_file"] is False
    assert path.read_text(encoding="ascii") == "A" * 64


def test_repair_permissions_preserves_token(tmp_path, monkeypatch):
    path = tmp_path / "operator-token"
    token = "A" * 64
    path.write_text(token, encoding="ascii")
    monkeypatch.setenv("RESOURCE_COORDINATOR_TOKEN_FILE", str(path))
    secured = []
    monkeypatch.setattr(credentials, "_secure_path", lambda target: secured.append(target))

    credentials.repair_permissions()

    assert secured[0] == path.parent
    assert secured[1].name.startswith(path.name + ".repair-")
    assert path.read_text(encoding="ascii") == token


def test_repair_acl_failure_preserves_existing_token(tmp_path, monkeypatch):
    path = tmp_path / "operator-token"
    original = "A" * 64
    path.write_text(original, encoding="ascii")
    monkeypatch.setenv("RESOURCE_COORDINATOR_TOKEN_FILE", str(path))
    def fail_temp_acl(target):
        if target != path.parent:
            raise credentials.CredentialError("ACL failure")

    monkeypatch.setattr(credentials, "_secure_path", fail_temp_acl)

    with pytest.raises(credentials.CredentialError, match="ACL"):
        credentials.repair_permissions()
    assert path.read_text(encoding="ascii") == original
    assert not list(tmp_path.glob("operator-token.repair-*"))


@pytest.mark.skipif(os.name != "nt", reason="Windows ACL integration")
def test_windows_credential_acl_allows_user_and_system_only(tmp_path, monkeypatch):
    path = tmp_path / "operator-token"
    monkeypatch.setenv("RESOURCE_COORDINATOR_TOKEN_FILE", str(path))
    monkeypatch.delenv("RESOURCE_COORDINATOR_OPERATOR_TOKEN", raising=False)

    credentials.load_or_create_token()

    assert credentials._acl_is_restricted(path)


def test_gateway_instances_reuse_provisioned_token_after_service_restart(tmp_path, monkeypatch):
    from resource_coordinator.adapters.lmstudio.gateway import LMStudioGateway

    path = tmp_path / "operator-token"
    monkeypatch.setenv("RESOURCE_COORDINATOR_TOKEN_FILE", str(path))
    monkeypatch.delenv("RESOURCE_COORDINATOR_OPERATOR_TOKEN", raising=False)
    monkeypatch.setattr(credentials, "_secure_path", lambda _target: None)
    credentials.load_or_create_token()

    before_restart = LMStudioGateway(standalone=True)
    after_restart = LMStudioGateway(standalone=True)

    assert before_restart.operator_token
    assert after_restart.operator_token == before_restart.operator_token


def test_cli_discovers_file_credential_automatically(tmp_path, monkeypatch):
    from resource_coordinator import cli

    path = tmp_path / "operator-token"
    path.write_text("A" * 64, encoding="ascii")
    monkeypatch.setenv("RESOURCE_COORDINATOR_TOKEN_FILE", str(path))
    monkeypatch.delenv("RESOURCE_COORDINATOR_OPERATOR_TOKEN", raising=False)
    monkeypatch.delenv("RESOURCE_COORDINATOR_RECOVERY_TOKEN", raising=False)

    assert cli._operator_token() == "A" * 64


def test_gateway_rejects_mismatched_credential(tmp_path, monkeypatch):
    from starlette.requests import Request
    from resource_coordinator.adapters.lmstudio.gateway import LMStudioGateway

    path = tmp_path / "operator-token"
    path.write_text("A" * 64, encoding="ascii")
    monkeypatch.setenv("RESOURCE_COORDINATOR_TOKEN_FILE", str(path))
    monkeypatch.delenv("RESOURCE_COORDINATOR_OPERATOR_TOKEN", raising=False)
    monkeypatch.setattr(credentials, "_secure_path", lambda _target: None)
    gateway = LMStudioGateway(standalone=True)
    request = Request({"type": "http", "headers": [(b"authorization", b"Bearer " + b"B" * 64)]})

    assert gateway._operator_authorized(request) is False


def test_gateway_recovers_after_credential_is_provisioned_later(tmp_path, monkeypatch):
    from resource_coordinator.adapters.lmstudio.gateway import LMStudioGateway

    path = tmp_path / "operator-token"
    monkeypatch.setenv("RESOURCE_COORDINATOR_TOKEN_FILE", str(path))
    monkeypatch.delenv("RESOURCE_COORDINATOR_OPERATOR_TOKEN", raising=False)
    monkeypatch.setattr(credentials, "_secure_path", lambda _target: None)
    gateway = LMStudioGateway(standalone=True)
    assert gateway.operator_token is None

    token = credentials.load_or_create_token()

    assert gateway._current_operator_token() == token
