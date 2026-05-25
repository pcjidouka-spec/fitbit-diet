import base64
import http.server
import ssl
import threading
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from diet.db import Token

FITBIT_AUTHZ_URL = "https://www.fitbit.com/oauth2/authorize"
FITBIT_TOKEN_URL = "https://api.fitbit.com/oauth2/token"


def generate_self_signed_cert(
    cert_path: Path, key_path: Path, hostname: str = "localhost", days_valid: int = 3650,
) -> None:
    """Create self-signed TLS cert + key (PEM). No-op if both files already exist."""
    if cert_path.exists() and key_path.exists():
        return
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=days_valid))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_path.parent.mkdir(parents=True, exist_ok=True)
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ))


def build_authorization_url(
    client_id: str, redirect_uri: str, scopes: list[str], state: str,
) -> str:
    params = {
        "client_id": client_id,
        "response_type": "code",
        "scope": " ".join(scopes),
        "redirect_uri": redirect_uri,
        "state": state,
    }
    return f"{FITBIT_AUTHZ_URL}?{urllib.parse.urlencode(params)}"


@dataclass
class CallbackResult:
    code: str | None = None
    state: str | None = None
    error: str | None = None


def run_callback_server(cert_path: Path, key_path: Path, port: int = 8765, timeout_sec: int = 300) -> CallbackResult:
    """Listen for the OAuth redirect once, then shut down. Returns parsed code/state."""
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
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)

    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    finished.wait(timeout=timeout_sec)
    httpd.shutdown()
    return result


async def exchange_code_for_token(
    client_id: str, client_secret: str, code: str, redirect_uri: str,
) -> Token:
    return await _token_request({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
    }, client_id, client_secret)


async def refresh_access_token(client_id: str, client_secret: str, refresh_token: str) -> Token:
    return await _token_request({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }, client_id, client_secret)


def run_init_flow(data_dir: Path, port: int, conn) -> None:
    """Generate cert, build URL, open browser, run callback, save token."""
    import asyncio
    import os
    import secrets
    import webbrowser

    from diet.db import save_token_atomic

    cert = data_dir / "oauth_cert.pem"
    key = data_dir / "oauth_key.pem"
    generate_self_signed_cert(cert, key, "localhost", 3650)
    client_id = os.environ["FITBIT_CLIENT_ID"]
    client_secret = os.environ["FITBIT_CLIENT_SECRET"]
    redirect = f"https://localhost:{port}/callback"
    state = secrets.token_urlsafe(16)
    url = build_authorization_url(client_id, redirect, ["activity", "weight"], state)
    print(f"ブラウザを開いて以下の URL にアクセスしてください:\n{url}")
    print("（初回は証明書警告 → Advanced → Proceed to localhost (unsafe)）")
    webbrowser.open(url)
    cb = run_callback_server(cert, key, port=port)
    if cb.error or not cb.code or cb.state != state:
        raise RuntimeError(f"OAuth failed: error={cb.error}, state mismatch?")
    tok = asyncio.run(
        exchange_code_for_token(client_id, client_secret, cb.code, redirect)
    )
    save_token_atomic(conn, tok)
    print("Fitbit OAuth 成功、token 保存完了。")


async def _token_request(data: dict, client_id: str, client_secret: str) -> Token:
    auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    headers = {
        "Authorization": f"Basic {auth}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    async with httpx.AsyncClient() as client:
        r = await client.post(FITBIT_TOKEN_URL, data=data, headers=headers, timeout=30.0)
        r.raise_for_status()
        body = r.json()
    return Token(
        access_token=body["access_token"],
        refresh_token=body["refresh_token"],
        expires_at=datetime.now() + timedelta(seconds=int(body["expires_in"])),
        user_id=body["user_id"],
    )
