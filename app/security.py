"""Security-related helpers (built-in auth).

Currently provides optional HTTP Basic auth protection for the UI and API.
"""

from __future__ import annotations

import base64
import binascii
import secrets
from dataclasses import dataclass

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


@dataclass(frozen=True)
class BasicAuthCredentials:
    username: str
    password: str


def _parse_basic_auth_header(header_value: str) -> BasicAuthCredentials | None:
    """Parse an Authorization header containing HTTP Basic auth."""
    if not header_value:
        return None

    scheme, _, param = header_value.partition(" ")
    if scheme.lower() != "basic" or not param:
        return None

    try:
        decoded = base64.b64decode(param, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return None

    username, sep, password = decoded.partition(":")
    if sep != ":":
        return None

    return BasicAuthCredentials(username=username, password=password)


class BasicAuthMiddleware(BaseHTTPMiddleware):
    """Protect routes via HTTP Basic auth.

    If enabled, we protect all paths except an allowlist (currently /health).
    """

    def __init__(
        self,
        app,
        *,
        username: str,
        password: str,
        allow_paths: set[str] | None = None,
        realm: str = "IssueBridge",
    ):
        super().__init__(app)
        self._username = username
        self._password = password
        self._allow_paths = allow_paths or {"/health"}
        self._realm = realm

    def _unauthorized(self) -> Response:
        return Response(
            content="Unauthorized",
            status_code=401,
            headers={"WWW-Authenticate": f'Basic realm="{self._realm}", charset="UTF-8"'},
        )

    async def dispatch(self, request: Request, call_next):
        if request.url.path in self._allow_paths:
            return await call_next(request)

        creds = _parse_basic_auth_header(request.headers.get("Authorization", ""))
        if creds is None:
            return self._unauthorized()

        ok_user = secrets.compare_digest(creds.username, self._username)
        ok_pass = secrets.compare_digest(creds.password, self._password)
        if not (ok_user and ok_pass):
            return self._unauthorized()

        return await call_next(request)
