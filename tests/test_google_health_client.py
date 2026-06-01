import datetime as dt
import re

import pytest

from diet.google_health_client import GoogleHealthClient, BASE

D = dt.date(2026, 5, 25)


async def test_daily_steps_rollup(httpx_mock):
    httpx_mock.add_response(
        url=f"{BASE}/users/me/dataTypes/steps/dataPoints:dailyRollUp", method="POST",
        json={"rollupDataPoints": [{"value": {"countSum": 8123}}]},
        match_headers={"Authorization": "Bearer A1"},
    )
    client = GoogleHealthClient(access_token="A1")
    assert await client.get_daily_steps(D) == 8123


async def test_daily_active_energy_rollup(httpx_mock):
    httpx_mock.add_response(
        url=f"{BASE}/users/me/dataTypes/active-energy-burned/dataPoints:dailyRollUp", method="POST",
        json={"rollupDataPoints": [{"value": {"kcalSum": 412.7}}]},
    )
    client = GoogleHealthClient(access_token="A1")
    assert await client.get_daily_active_energy_kcal(D) == 413  # rounded


async def test_daily_distance_km_converts_meters(httpx_mock):
    httpx_mock.add_response(
        url=f"{BASE}/users/me/dataTypes/distance/dataPoints:dailyRollUp", method="POST",
        json={"rollupDataPoints": [{"value": {"meterSum": 5230}}]},
    )
    client = GoogleHealthClient(access_token="A1")
    assert await client.get_daily_distance_km(D) == 5.23


async def test_empty_rollup_returns_zero(httpx_mock):
    httpx_mock.add_response(
        url=f"{BASE}/users/me/dataTypes/steps/dataPoints:dailyRollUp", method="POST",
        json={"rollupDataPoints": []},
    )
    client = GoogleHealthClient(access_token="A1")
    assert await client.get_daily_steps(D) == 0


async def test_weight_log_grams_to_kg_and_local_date(httpx_mock):
    httpx_mock.add_response(
        url=re.compile(r".*/users/me/dataTypes/weight/dataPoints.*"), method="GET",
        json={"dataPoints": [{"weight": {
            "weightGrams": 71200,
            "sampleTime": {"civilTime": {"date": {"year": 2026, "month": 5, "day": 25}},
                           "physicalTime": "2026-05-25T07:30:00+09:00"},
        }}]},
    )
    client = GoogleHealthClient(access_token="A1")
    out = await client.get_weight_log(D)
    assert out == [{"date": "2026-05-25", "weight_kg": 71.2}]


async def test_401_triggers_one_refresh(httpx_mock):
    url = f"{BASE}/users/me/dataTypes/steps/dataPoints:dailyRollUp"
    httpx_mock.add_response(url=url, method="POST", status_code=401, json={})
    httpx_mock.add_response(url=url, method="POST", json={"rollupDataPoints": [{"value": {"countSum": 10}}]})
    calls = {"n": 0}
    async def refresh():
        calls["n"] += 1
        return "A2"
    client = GoogleHealthClient(access_token="A1", on_unauthorized=refresh)
    assert await client.get_daily_steps(D) == 10
    assert calls["n"] == 1 and client.access_token == "A2"


async def test_401_twice_raises(httpx_mock):
    url = f"{BASE}/users/me/dataTypes/steps/dataPoints:dailyRollUp"
    httpx_mock.add_response(url=url, method="POST", status_code=401, json={})
    httpx_mock.add_response(url=url, method="POST", status_code=401, json={})
    async def refresh():
        return "A2"
    client = GoogleHealthClient(access_token="A1", on_unauthorized=refresh)
    import httpx
    with pytest.raises(httpx.HTTPStatusError):
        await client.get_daily_steps(D)


async def test_429_raises(httpx_mock):
    httpx_mock.add_response(
        url=f"{BASE}/users/me/dataTypes/steps/dataPoints:dailyRollUp", method="POST",
        status_code=429, json={"error": {"code": 429, "status": "RESOURCE_EXHAUSTED"}},
    )
    import httpx
    client = GoogleHealthClient(access_token="A1")
    with pytest.raises(httpx.HTTPStatusError):
        await client.get_daily_steps(D)
