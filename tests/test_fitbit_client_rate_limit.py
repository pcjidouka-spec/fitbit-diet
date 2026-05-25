import pytest
import httpx
from diet.fitbit_client import FitbitClient


async def test_rate_limit_headers_tracked(httpx_mock):
    httpx_mock.add_response(
        url="https://api.fitbit.com/1/user/-/activities/date/2026-05-25.json",
        json={"summary": {}},
        headers={"Fitbit-Rate-Limit-Limit": "150", "Fitbit-Rate-Limit-Remaining": "120", "Fitbit-Rate-Limit-Reset": "1800"},
    )
    client = FitbitClient(access_token="A1")
    await client.get_activity_summary("2026-05-25")
    assert client.rate_limit.limit == 150
    assert client.rate_limit.remaining == 120
    assert client.rate_limit.reset_seconds == 1800


async def test_429_reset_seconds_in_state(httpx_mock):
    httpx_mock.add_response(
        url="https://api.fitbit.com/1/user/-/activities/date/2026-05-25.json",
        status_code=429, headers={"Fitbit-Rate-Limit-Reset": "600"}, json={},
    )
    client = FitbitClient(access_token="A1")
    with pytest.raises(httpx.HTTPStatusError):
        await client.get_activity_summary("2026-05-25")
    assert client.rate_limit.reset_seconds == 600
