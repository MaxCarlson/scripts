# web-ui-tools

`web-ui-tools` is a small reusable local ASGI service for application-owned browser views. It provides static asset delivery, explicit FastAPI router integration, loopback server creation, local login-code exchange, same-origin/Host checks, and non-cacheable authenticated API responses. WebSocket routes below `/api` use the same trusted-host, same-origin, and live session-cookie checks as HTTP API routes. The supplied Uvicorn server enables WebSockets with its declared `wsproto` dependency. The application owns its routes and frontend; this package does not impose a generic form or dashboard model.

```python
from fastapi import APIRouter
from web_ui_tools import create_app, run_server

router = APIRouter(prefix="/api")

@router.get("/health")
def health():
    return {"status": "ready"}

app = create_app(
    api_router=router,
    static_dir="my_app/static",
    login_code="generated-at-startup",
    session_cookie_name="my_app_session",
)
run_server(app, host="127.0.0.1", port=8787)
```

Application routes must be below `/api` so the shared service can protect them consistently. The login code is supplied by the application, accepted only from the matching browser origin, and exchanged for a random in-memory cookie marked `HttpOnly` and `SameSite=Strict`. The browser cannot read the session value from JavaScript. Requests under `/api` are not cached. Bind addresses must be loopback IPs; access logging is disabled by the supplied Uvicorn server factory.

Applications sharing a hostname can pass a distinct `session_cookie_name`; it defaults to `web_ui_session` for existing callers. Cookie names are restricted to ASCII letters, digits, underscores, and hyphens.

WebSocket API clients authenticate with that same cookie during the handshake. The middleware rejects untrusted hosts, missing or mismatched origins, and expired sessions before application routes can open a process attachment or read protected data. It applies to all `/api` WebSockets created through `create_app`.

An executable independent example is available with `python -m web_ui_tools.examples.hello_app`. It mounts an application-owned `/api/hello` route without importing Runmux.
