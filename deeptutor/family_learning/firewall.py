"""Default-deny ASGI boundary covering public routes and WebSockets too."""

from http.cookies import SimpleCookie
import json
from urllib.parse import parse_qs

from .access import learner_route_allowed


class LocalLearningFirewall:
    def __init__(self, app, enabled, auth_enabled, decode_token, parent_callback=lambda: False):
        self.parent_callback = parent_callback
        self.app, self.enabled, self.auth_enabled, self.decode_token = (
            app,
            enabled,
            auth_enabled,
            decode_token,
        )

    async def __call__(self, scope, receive, send):
        if scope["type"] not in {"http", "websocket"} or not self.enabled():
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        if scope["type"] == "http" and (
            (
                self.parent_callback()
                and path == "/api/auth/openai-codex/callback"
                and scope["method"] == "GET"
            )
            or (path == "/api/auth/login" and scope["method"] == "POST")
            or (
                path in {"/api/auth/status", "/health", "/health/ready"}
                and scope["method"] == "GET"
            )
        ):
            return await self.app(scope, receive, send)
        headers = {
            key.decode("latin1").lower(): value.decode("latin1")
            for key, value in scope.get("headers", [])
        }
        token = None
        try:
            cookie = SimpleCookie()
            cookie.load(headers.get("cookie", ""))
            if "dt_token" in cookie:
                token = cookie["dt_token"].value
            authorization = headers.get("authorization", "")
            if authorization.lower().startswith("bearer "):
                token = authorization[7:].strip()
            if scope["type"] == "websocket":
                token = parse_qs(scope.get("query_string", b"").decode()).get("token", [token])[0]
            payload = self.decode_token(token) if token and self.auth_enabled() else None
        except (ValueError, UnicodeError):
            payload = None
        allowed = payload is not None and learner_route_allowed(
            local_only=True,
            auth_enabled=self.auth_enabled(),
            role=payload.role,
            path=path,
            websocket=scope["type"] == "websocket",
        )
        if allowed:
            return await self.app(scope, receive, send)
        if scope["type"] == "websocket":
            return await send({"type": "websocket.close", "code": 1008})
        raw = json.dumps({"detail": "Sign in and use assigned local lessons only"}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 403 if payload else 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(raw)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": raw})
