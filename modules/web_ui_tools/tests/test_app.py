from pathlib import Path
from secrets import token_urlsafe

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from web_ui_tools.app import create_app, create_server


def make_router() -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/sample")
    def sample() -> dict[str, str]:
        return {"application": "sample", "value": "ok"}

    return router


def make_app(login_code: str) -> object:
    return create_app(
        api_router=make_router(),
        static_dir=Path(__file__).resolve().parents[1] / "src" / "web_ui_tools" / "static",
        login_code=login_code,
        allowed_hosts=["testserver"],
    )


def test_api_requires_login_and_session_cookie_is_http_only() -> None:
    login_code = token_urlsafe(32)
    with TestClient(make_app(login_code)) as client:
        assert client.get("/api/sample", headers={"Origin": "http://testserver"}).status_code == 401

        response = client.post(
            "/auth/login",
            json={"code": login_code},
            headers={"Origin": "http://testserver"},
        )
        assert response.status_code == 204
        assert response.headers["cache-control"] == "no-store"
        cookie = response.headers["set-cookie"].lower()
        assert "httponly" in cookie
        assert "samesite=strict" in cookie

        data = client.get("/api/sample", headers={"Origin": "http://testserver"})
        assert data.status_code == 200
        assert data.json() == {"application": "sample", "value": "ok"}
        assert data.headers["cache-control"] == "no-store"

        browser_get = client.get("/api/sample", headers={"Sec-Fetch-Site": "same-origin"})
        assert browser_get.status_code == 200
        assert browser_get.headers["cache-control"] == "no-store"


def test_login_rejects_wrong_code_and_cross_origin_requests() -> None:
    login_code = token_urlsafe(32)
    with TestClient(make_app(login_code)) as client:
        wrong_code = client.post(
            "/auth/login",
            json={"code": token_urlsafe(32)},
            headers={"Origin": "http://testserver"},
        )
        assert wrong_code.status_code == 401

        foreign_origin = client.post(
            "/auth/login",
            json={"code": login_code},
            headers={"Origin": "http://attacker.test"},
        )
        assert foreign_origin.status_code == 403

        assert client.get("/api/sample", headers={"Origin": "http://attacker.test"}).status_code == 403
        assert client.get("/api/sample", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
        assert client.get("/api/sample").status_code == 403
        hostile_host = client.get("/api/sample", headers={"Host": "attacker.test", "Origin": "http://attacker.test"})
        assert hostile_host.status_code == 400

        client.post(
            "/auth/login",
            json={"code": login_code},
            headers={"Origin": "http://testserver"},
        )
        logged_out = client.post("/auth/logout", headers={"Origin": "http://testserver"})
        assert logged_out.status_code == 204
        assert client.get("/api/sample", headers={"Origin": "http://testserver"}).status_code == 401


def test_server_refuses_non_loopback_bind_addresses() -> None:
    with pytest.raises(ValueError, match="loopback IP address"):
        create_server(make_app(token_urlsafe(32)), host="0.0.0.0")
    with pytest.raises(ValueError, match="loopback IP address"):
        create_server(make_app(token_urlsafe(32)), host="localhost")


def test_app_rejects_application_routes_outside_protected_api() -> None:
    router = APIRouter()

    @router.get("/private")
    def private() -> dict[str, bool]:
        return {"private": True}

    try:
        create_app(
            api_router=router,
            static_dir=Path(__file__).resolve().parents[1] / "src" / "web_ui_tools" / "static",
            login_code=token_urlsafe(32),
            allowed_hosts=["testserver"],
        )
    except ValueError as error:
        assert "below /api" in str(error)
    else:
        raise AssertionError("unprotected application routes must not be mounted")


def test_app_serves_static_ui_without_importing_runmux(monkeypatch) -> None:
    import sys

    monkeypatch.setitem(sys.modules, "runmux", None)
    with TestClient(make_app(token_urlsafe(32))) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "Local Web Tools" in response.text
