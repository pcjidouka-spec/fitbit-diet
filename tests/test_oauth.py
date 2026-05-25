from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from diet.oauth import (
    FITBIT_AUTHZ_URL,
    build_authorization_url,
    exchange_code_for_token,
    generate_self_signed_cert,
    refresh_access_token,
)


def test_generate_cert_creates_files(tmp_path: Path):
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    generate_self_signed_cert(cert_path=cert, key_path=key, hostname="localhost", days_valid=3650)
    assert cert.exists()
    assert key.exists()
    assert cert.read_bytes().startswith(b"-----BEGIN CERTIFICATE-----")
    assert key.read_bytes().startswith(b"-----BEGIN PRIVATE KEY-----")


def test_generate_cert_idempotent_if_files_exist(tmp_path):
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    generate_self_signed_cert(cert, key, "localhost", 3650)
    original_cert = cert.read_bytes()
    generate_self_signed_cert(cert, key, "localhost", 3650)  # no-op
    assert cert.read_bytes() == original_cert


def test_cert_validity_period(tmp_path):
    """Verify not_valid_after matches days_valid"""
    from cryptography import x509
    from datetime import datetime, timezone, timedelta
    cert_path = tmp_path / "c.pem"
    key_path = tmp_path / "k.pem"
    generate_self_signed_cert(cert_path, key_path, "localhost", days_valid=3650)
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    expected = datetime.now(timezone.utc) + timedelta(days=3650)
    # cryptography 42+ uses not_valid_after_utc; older API uses not_valid_after
    actual = getattr(cert, "not_valid_after_utc", None) or cert.not_valid_after.replace(tzinfo=timezone.utc)
    delta = abs((actual - expected).total_seconds())
    assert delta < 60  # within 60s of expected


def test_build_authz_url_params():
    url = build_authorization_url("CID", "https://localhost:8765/callback", ["activity", "weight"], "state123")
    assert url.startswith(FITBIT_AUTHZ_URL)
    qs = parse_qs(urlparse(url).query)
    assert qs["client_id"] == ["CID"]
    assert qs["response_type"] == ["code"]
    assert qs["redirect_uri"] == ["https://localhost:8765/callback"]
    assert qs["scope"] == ["activity weight"]
    assert qs["state"] == ["state123"]


async def test_exchange_success(httpx_mock):
    httpx_mock.add_response(
        url="https://api.fitbit.com/oauth2/token", method="POST",
        json={"access_token": "A1", "refresh_token": "R1", "expires_in": 28800, "user_id": "UID", "scope": "activity weight"},
    )
    tok = await exchange_code_for_token("CID", "CSEC", "C1", "https://localhost:8765/callback")
    assert tok.access_token == "A1"
    assert tok.user_id == "UID"


async def test_refresh_returns_new_pair(httpx_mock):
    httpx_mock.add_response(
        url="https://api.fitbit.com/oauth2/token", method="POST",
        json={"access_token": "A2", "refresh_token": "R2", "expires_in": 28800, "user_id": "UID", "scope": "activity weight"},
    )
    tok = await refresh_access_token("CID", "CSEC", "R1")
    assert tok.access_token == "A2"
    assert tok.refresh_token == "R2"


async def test_exchange_4xx_raises(httpx_mock):
    httpx_mock.add_response(
        url="https://api.fitbit.com/oauth2/token", method="POST",
        status_code=400, json={"errors": [{"message": "invalid_grant"}]},
    )
    import httpx
    with pytest.raises(httpx.HTTPStatusError):
        await exchange_code_for_token("CID", "CSEC", "BAD", "https://localhost:8765/callback")
