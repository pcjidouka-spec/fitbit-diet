from urllib.parse import parse_qs, urlparse

import pytest

from diet.oauth import (
    GOOGLE_AUTHZ_URL,
    GOOGLE_TOKEN_URL,
    SCOPES,
    build_authorization_url,
    exchange_code_for_token,
    refresh_access_token,
)


def test_build_authz_url_params():
    url = build_authorization_url("CID", "http://localhost:8765/callback", SCOPES, "state123")
    assert url.startswith(GOOGLE_AUTHZ_URL)
    qs = parse_qs(urlparse(url).query)
    assert qs["client_id"] == ["CID"]
    assert qs["response_type"] == ["code"]
    assert qs["redirect_uri"] == ["http://localhost:8765/callback"]
    assert qs["access_type"] == ["offline"]
    assert qs["prompt"] == ["consent"]
    assert "googlehealth.activity_and_fitness.readonly" in qs["scope"][0]
    assert "googlehealth.health_metrics_and_measurements.readonly" in qs["scope"][0]
    assert qs["state"] == ["state123"]


async def test_exchange_success_populates_user_id_from_identity(httpx_mock):
    httpx_mock.add_response(
        url=GOOGLE_TOKEN_URL, method="POST",
        json={"access_token": "A1", "refresh_token": "R1", "expires_in": 3599, "scope": "x", "token_type": "Bearer"},
    )
    httpx_mock.add_response(
        url="https://health.googleapis.com/v4/users/me/identity",
        json={"healthUserId": "HUID", "legacyUserId": "LUID"},
    )
    tok = await exchange_code_for_token("CID", "CSEC", "C1", "http://localhost:8765/callback")
    assert tok.access_token == "A1"
    assert tok.refresh_token == "R1"
    assert tok.user_id == "HUID"


async def test_exchange_identity_failure_falls_back_to_me(httpx_mock):
    httpx_mock.add_response(
        url=GOOGLE_TOKEN_URL, method="POST",
        json={"access_token": "A1", "refresh_token": "R1", "expires_in": 3599},
    )
    httpx_mock.add_response(
        url="https://health.googleapis.com/v4/users/me/identity", status_code=500, json={}
    )
    tok = await exchange_code_for_token("CID", "CSEC", "C1", "http://localhost:8765/callback")
    assert tok.user_id == "me"  # graceful fallback


async def test_refresh_without_new_refresh_token_carries_forward(httpx_mock):
    """Google omits refresh_token on refresh — must carry the old one forward."""
    httpx_mock.add_response(
        url=GOOGLE_TOKEN_URL, method="POST",
        json={"access_token": "A2", "expires_in": 3599, "scope": "x", "token_type": "Bearer"},
    )
    tok = await refresh_access_token("CID", "CSEC", "R1", user_id="HUID")
    assert tok.access_token == "A2"
    assert tok.refresh_token == "R1"   # carried forward
    assert tok.user_id == "HUID"       # carried forward


async def test_refresh_with_new_refresh_token_uses_it(httpx_mock):
    httpx_mock.add_response(
        url=GOOGLE_TOKEN_URL, method="POST",
        json={"access_token": "A2", "refresh_token": "R2", "expires_in": 3599},
    )
    tok = await refresh_access_token("CID", "CSEC", "R1", user_id="HUID")
    assert tok.refresh_token == "R2"


async def test_exchange_4xx_raises(httpx_mock):
    httpx_mock.add_response(
        url=GOOGLE_TOKEN_URL, method="POST", status_code=400, json={"error": "invalid_grant"},
    )
    import httpx
    with pytest.raises(httpx.HTTPStatusError):
        await exchange_code_for_token("CID", "CSEC", "BAD", "http://localhost:8765/callback")
