from pathlib import Path
from secrets import token_urlsafe

import pytest
from fastapi import APIRouter, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from web_ui_tools.app import create_app, create_server


def make_router() -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/sample")
    def sample() -> dict[str, str]:
        return {"application": "sample", "value": "ok"}

    @router.websocket("/socket")
    async def socket(websocket: WebSocket) -> None:
        await websocket.accept()
        await websocket.send_text("connected")

    return router


def test_websocket_requires_same_origin_and_live_browser_session() -> None:
    login_code = token_urlsafe(32)
    app = make_app(login_code)
    with TestClient(app) as client:
        with (
            pytest.raises(WebSocketDisconnect) as unauthorized,
            client.websocket_connect("/api/socket", headers={"Origin": "http://testserver"}) as websocket,
        ):
            websocket.receive_text()
        assert unauthorized.value.code == 4401

        client.post("/auth/login", json={"code": login_code}, headers={"Origin": "http://testserver"})
        session_cookie = f"web_ui_session={client.cookies.get('web_ui_session')}"
        with client.websocket_connect(
            "/api/socket",
            headers={"Origin": "http://testserver", "Cookie": session_cookie},
        ) as websocket:
            assert websocket.receive_text() == "connected"

        with (
            pytest.raises(WebSocketDisconnect) as foreign_origin,
            client.websocket_connect(
                "/api/socket",
                headers={"Origin": "http://attacker.test", "Cookie": session_cookie},
            ) as websocket,
        ):
            websocket.receive_text()
        assert foreign_origin.value.code == 4403

        with (
            pytest.raises(WebSocketDisconnect) as untrusted_host,
            client.websocket_connect(
                "/api/socket",
                headers={
                    "Origin": "http://attacker.test",
                    "Host": "attacker.test",
                    "Cookie": session_cookie,
                },
            ) as websocket,
        ):
            websocket.receive_text()
        assert untrusted_host.value.code == 4400

        session_id = client.cookies.get("web_ui_session")
        assert session_id
        app.state.sessions[session_id] = 0
        with (
            pytest.raises(WebSocketDisconnect) as expired,
            client.websocket_connect(
                "/api/socket",
                headers={"Origin": "http://testserver", "Cookie": session_cookie},
            ) as websocket,
        ):
            websocket.receive_text()
        assert expired.value.code == 4401


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


def test_application_can_use_an_isolated_session_cookie_name() -> None:
    app = create_app(
        api_router=make_router(),
        static_dir=Path(__file__).resolve().parents[1] / "src" / "web_ui_tools" / "static",
        login_code="isolated-login",
        allowed_hosts=["testserver"],
        session_cookie_name="llm_monitor_session",
    )

    with TestClient(app) as client:
        login = client.post(
            "/auth/login",
            json={"code": "isolated-login"},
            headers={"Origin": "http://testserver"},
        )
        assert login.status_code == 204
        assert login.headers["set-cookie"].startswith("llm_monitor_session=")
        session_id = client.cookies.get("llm_monitor_session")
        assert session_id
        assert client.get("/api/sample", headers={"Origin": "http://testserver"}).status_code == 200
        with client.websocket_connect(
            "/api/socket",
            headers={"Origin": "http://testserver", "Cookie": f"llm_monitor_session={session_id}"},
        ) as websocket:
            assert websocket.receive_text() == "connected"

        logout = client.post("/auth/logout", headers={"Origin": "http://testserver"})
        assert "llm_monitor_session=\"\"" in logout.headers["set-cookie"]
        assert client.get("/api/sample", headers={"Origin": "http://testserver"}).status_code == 401


def test_application_rejects_invalid_session_cookie_names() -> None:
    with pytest.raises(ValueError, match="session_cookie_name"):
        create_app(
            api_router=make_router(),
            static_dir=Path(__file__).resolve().parents[1] / "src" / "web_ui_tools" / "static",
            login_code="test-login",
            allowed_hosts=["testserver"],
            session_cookie_name="bad name",
        )


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


def test_server_enables_websocket_transport() -> None:
    server = create_server(make_app(token_urlsafe(32)), host="127.0.0.1", port=0)
    assert server.config.ws == "wsproto"


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
        policy = response.headers["content-security-policy"]
        assert "ws://127.0.0.1:*" in policy
        assert "ws://localhost:*" in policy
        assert "style-src-attr" not in policy


def test_app_can_allow_inline_styles_without_allowing_inline_scripts() -> None:
    app = create_app(
        api_router=make_router(),
        static_dir=Path(__file__).resolve().parents[1] / "src" / "web_ui_tools" / "static",
        login_code="test-login",
        allowed_hosts=["testserver"],
        allow_inline_styles=True,
    )

    with TestClient(app) as client:
        policy = client.get("/").headers["content-security-policy"]

    assert "style-src 'self' 'unsafe-inline'" in policy
    assert "script-src 'self'" in policy
    assert "script-src 'unsafe-inline'" not in policy
