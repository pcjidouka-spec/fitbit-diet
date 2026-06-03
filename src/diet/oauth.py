import http.server
import threading
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import httpx

from diet.db import Token

GOOGLE_AUTHZ_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
HEALTH_BASE = "https://health.googleapis.com/v4"
SCOPES = [
    "https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly",
    "https://www.googleapis.com/auth/googlehealth.health_metrics_and_measurements.readonly",
]


def build_authorization_url(client_id: str, redirect_uri: str, scopes: list[str], state: str) -> str:
    params = {
        "client_id": client_id,
        "response_type": "code",
        "scope": " ".join(scopes),
        "redirect_uri": redirect_uri,
        "state": state,
        "access_type": "offline",   # request a refresh_token
        "prompt": "consent",        # force refresh_token issuance on re-auth
    }
    return f"{GOOGLE_AUTHZ_URL}?{urllib.parse.urlencode(params)}"


@dataclass
class CallbackResult:
    code: str | None = None
    state: str | None = None
    error: str | None = None


def run_callback_server(port: int = 8765, timeout_sec: int = 600) -> CallbackResult:
    """Listen for the OAuth redirect over plain HTTP until /callback arrives,
    then shut down. Google exempts http://localhost from the HTTPS-only redirect
    rule, so no TLS certificate is needed.

    timeout_sec is 600s (10 min): the first-time consent involves the
    "unverified app" warning screen which a user can spend several minutes
    reading. A shorter window silently times out, closes the listener, and the
    eventual redirect hits a dead port ("connection refused"). Non-/callback
    requests (favicon etc.) return 404 without ending the wait, so the listener
    stays up for the whole window."""
    result = CallbackResult()
    finished = threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != "/callback":
                self.send_response(404); self.end_headers(); return
            qs = urllib.parse.parse_qs(parsed.query)
            result.code = (qs.get("code") or [None])[0]
            result.state = (qs.get("state") or [None])[0]
            result.error = (qs.get("error") or [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<h1>Authorization received</h1><p>You can close this tab.</p>")
            finished.set()
        def log_message(self, fmt, *args): pass

    httpd = http.server.HTTPServer(("localhost", port), Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    finished.wait(timeout=timeout_sec)
    httpd.shutdown()
    return result


async def _post_token(data: dict) -> dict:
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    async with httpx.AsyncClient() as client:
        r = await client.post(GOOGLE_TOKEN_URL, data=data, headers=headers, timeout=30.0)
        r.raise_for_status()
        return r.json()


async def fetch_user_id(access_token: str) -> str:
    """Resolve the user id via GET /users/me/identity. Falls back to "me" on
    any failure or unexpected shape (the response schema is unverified)."""
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{HEALTH_BASE}/users/me/identity",
                headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
                timeout=30.0,
            )
            r.raise_for_status()
            body = r.json()
        return body.get("healthUserId") or body.get("legacyUserId") or "me"
    except Exception:  # noqa: BLE001 — identity is best-effort
        return "me"


async def exchange_code_for_token(client_id: str, client_secret: str, code: str, redirect_uri: str) -> Token:
    body = await _post_token({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "client_secret": client_secret,
    })
    user_id = await fetch_user_id(body["access_token"])
    return Token(
        access_token=body["access_token"],
        refresh_token=body["refresh_token"],
        expires_at=datetime.now() + timedelta(seconds=int(body["expires_in"])),
        user_id=user_id,
    )


async def refresh_access_token(client_id: str, client_secret: str, refresh_token: str, user_id: str = "me") -> Token:
    body = await _post_token({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
    })
    return Token(
        access_token=body["access_token"],
        refresh_token=body.get("refresh_token", refresh_token),  # Google omits it ⇒ carry forward
        expires_at=datetime.now() + timedelta(seconds=int(body["expires_in"])),
        user_id=user_id,
    )


def run_init_flow(data_dir: Path, port: int, conn) -> None:
    """Build URL, open browser, run loopback callback, exchange, save token."""
    import asyncio
    import os
    import secrets
    import webbrowser

    from diet.db import save_token_atomic

    client_id = os.environ["GOOGLE_CLIENT_ID"]
    client_secret = os.environ["GOOGLE_CLIENT_SECRET"]
    redirect = os.environ.get("GOOGLE_REDIRECT_URI", f"http://localhost:{port}/callback")
    # The loopback listener must bind the SAME port the redirect advertises, so
    # a custom GOOGLE_REDIRECT_URI with a non-default port cannot diverge from --port.
    listen_port = urllib.parse.urlparse(redirect).port or port
    state = secrets.token_urlsafe(16)
    url = build_authorization_url(client_id, redirect, SCOPES, state)
    print(f"ブラウザを開いて以下の URL にアクセスし、Google アカウントで認可してください:\n{url}")
    webbrowser.open(url)
    cb = run_callback_server(port=listen_port)
    if cb.error or not cb.code or cb.state != state:
        raise RuntimeError(f"OAuth failed: error={cb.error}, state mismatch?")
    tok = asyncio.run(exchange_code_for_token(client_id, client_secret, cb.code, redirect))
    save_token_atomic(conn, tok)
    print("Google Health OAuth 成功、token 保存完了。")
