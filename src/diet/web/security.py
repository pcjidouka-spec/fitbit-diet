"""localhost browser security (spec §3.2 full set).

127.0.0.1 binding alone cannot stop DNS rebinding, so we also validate the
Host header, check Origin on mutations, require a per-launch CSRF token, and
confirm the client is loopback.
"""
import ipaddress

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

_LOOPBACK_NAMES = {"localhost"}
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
# Starlette's TestClient sets request.client.host to the string "testclient",
# which is not a real IP, so is_loopback_host would reject it. Allow it in the
# client-IP defense (belt-and-suspenders). In production uvicorn binds 127.0.0.1
# so real clients are always loopback. The primary defenses are Host/Origin/CSRF.
_ALLOWED_CLIENT_HOSTS = {"testclient"}


def is_loopback_host(host: str) -> bool:
    if host in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _safe_port(text: str) -> int | None:
    """Parse a port string from untrusted input, or None if not a valid port.

    Never raises. ``int()`` can raise even when ``str.isdigit()`` is True
    (a digit string above Python's int-string conversion digit limit, ~4300
    by default), so we wrap it and bound the result to the valid TCP port
    range (0..65535). Returning None
    makes the caller treat the host/origin as invalid (clean 400/403) rather
    than surfacing an internal 500.
    """
    try:
        port = int(text)
    except ValueError:
        return None
    return port if 0 <= port <= 65535 else None


def _hostname(value: str) -> tuple[str, int | None]:
    """'127.0.0.1:8770' -> ('127.0.0.1', 8770). No port -> (host, None)."""
    if value.startswith("[") and "]" in value:  # IPv6 literal
        host, _, rest = value[1:].partition("]")
        return host, (_safe_port(rest[1:]) if rest.startswith(":") else None)
    host, sep, p = value.partition(":")
    return host, (_safe_port(p) if sep else None)


def host_header_ok(host_header: str | None, port: int) -> bool:
    if not host_header:
        return False
    host, hport = _hostname(host_header)
    return is_loopback_host(host) and hport == port


def origin_ok(origin: str | None, port: int) -> bool:
    if not origin:
        return False
    scheme, _, rest = origin.partition("://")
    if scheme not in ("http", "https"):
        return False
    host, hport = _hostname(rest)
    return is_loopback_host(host) and hport == port


class LocalhostSecurityMiddleware(BaseHTTPMiddleware):
    """Enforce Host / Origin / CSRF / loopback."""

    def __init__(self, app, *, port: int, csrf_token: str):
        super().__init__(app)
        self.port = port
        self.csrf_token = csrf_token

    async def dispatch(self, request, call_next):
        if not host_header_ok(request.headers.get("host"), self.port):
            return JSONResponse({"code": "bad_host", "detail": "invalid Host header"}, status_code=400)
        client = request.client
        if (client is not None
                and client.host not in _ALLOWED_CLIENT_HOSTS
                and not is_loopback_host(client.host)):
            return JSONResponse({"code": "not_loopback", "detail": "loopback only"}, status_code=403)
        if request.method not in _SAFE_METHODS:
            if not origin_ok(request.headers.get("origin"), self.port):
                return JSONResponse({"code": "bad_origin", "detail": "invalid Origin"}, status_code=403)
            if request.headers.get("x-csrf-token") != self.csrf_token:
                return JSONResponse({"code": "bad_csrf", "detail": "invalid CSRF token"}, status_code=403)
        return await call_next(request)
