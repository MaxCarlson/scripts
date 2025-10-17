
from datetime import datetime

from pydantic import ValidationError
import pytest

from syncmux.models import Host, Session

def test_host_model():
    host = Host(
        alias="test",
        hostname="localhost",
        user="testuser",
        auth_method="agent",
    )
    assert host.alias == "test"
    assert host.port == 22

    with pytest.raises(ValidationError):
        Host(
            alias="test",
            hostname="localhost",
            user="testuser",
            auth_method="invalid",
        )

def test_session_model():
    now = datetime.now()
    session = Session(
        id="$1",
        name="test-session",
        windows=1,
        attached=0,
        created_at=now,
    )
    assert session.name == "test-session"
    assert session.created_at == now

    with pytest.raises(ValidationError):
        Session(
            id="$1",
            name="test-session",
            windows="invalid",
            attached=0,
            created_at=now,
        )
