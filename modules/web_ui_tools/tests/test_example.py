from secrets import token_urlsafe

from fastapi.testclient import TestClient

from web_ui_tools.examples.hello_app import create_hello_app


def test_standalone_application_route_uses_shared_web_service(monkeypatch) -> None:
    import sys

    monkeypatch.setitem(sys.modules, "runmux", None)
    login_code = token_urlsafe(32)
    app = create_hello_app(login_code=login_code)

    with TestClient(app, base_url="http://localhost") as client:
        login = client.post("/auth/login", json={"code": login_code}, headers={"Origin": "http://localhost"})
        assert login.status_code == 204
        response = client.get("/api/hello", headers={"Origin": "http://localhost"})

    assert response.json() == {"message": "Hello from an application that does not use runmux."}
