from pathlib import Path
from urllib.parse import parse_qs, urlparse

from diet.oauth import (
    FITBIT_AUTHZ_URL,
    build_authorization_url,
    generate_self_signed_cert,
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
