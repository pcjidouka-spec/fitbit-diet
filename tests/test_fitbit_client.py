import pytest
from diet.fitbit_client import FitbitClient


async def test_authorization_header(httpx_mock):
    httpx_mock.add_response(
        url="https://api.fitbit.com/1/user/-/activities/date/2026-05-25.json",
        json={"summary": {"steps": 100, "marginalCalories": 80, "distances": [{"activity": "total", "distance": 1.5}]}, "activities": []},
        match_headers={"Authorization": "Bearer A1"},
    )
    client = FitbitClient(access_token="A1")
    data = await client.get_activity_summary("2026-05-25")
    assert data["summary"]["steps"] == 100


async def test_get_weight_log(httpx_mock):
    httpx_mock.add_response(
        url="https://api.fitbit.com/1/user/-/body/log/weight/date/2026-05-25.json",
        json={"weight": [{"date": "2026-05-25", "weight": 71.2, "time": "07:30:00"}]},
    )
    client = FitbitClient(access_token="A1")
    weights = await client.get_weight_log("2026-05-25")
    assert weights[0]["weight"] == 71.2
