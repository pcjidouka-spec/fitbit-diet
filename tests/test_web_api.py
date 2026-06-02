from datetime import date
from fastapi.testclient import TestClient
from diet.db import open_db, save_config, Config
from diet.web.app import create_app

PORT = 8770
HOST_HEADERS = {"host": f"127.0.0.1:{PORT}"}


def _seed_dir(tmp_path):
    conn = open_db(tmp_path / "diet.db")
    save_config(conn, Config(
        birthday=date(1979, 12, 1), height_cm=169, sex="male",
        timezone="Asia/Tokyo", hpasaneel_path=str(tmp_path / "hp"),
        hpasaneel_diet_root="content/diet", exercise_calorie_source=None,
        bootstrap_daily_kcal=2200,
    ))
    conn.close()
    return tmp_path


def _client(tmp_path):
    app = create_app(data_dir=_seed_dir(tmp_path), port=PORT)
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}")


def test_index_served_with_csrf(tmp_path):
    r = _client(tmp_path).get("/", headers=HOST_HEADERS)
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    # CSRF プレースホルダが実トークンに置換されていること（置換忘れ回帰防止）。
    assert "{csrf_token}" not in r.text
    assert 'name="csrf-token"' in r.text


def test_api_day(tmp_path):
    r = _client(tmp_path).get("/api/day", headers=HOST_HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert "date" in body and "intake" in body


def test_api_history(tmp_path):
    r = _client(tmp_path).get("/api/history?days=7", headers=HOST_HEADERS)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_api_auth_status(tmp_path):
    r = _client(tmp_path).get("/api/auth/status", headers=HOST_HEADERS)
    assert r.status_code == 200
    assert r.json()["authenticated"] is False


def test_create_app_rejects_out_of_range_ports(tmp_path):
    import pytest
    for bad in (80, 443, 70000):
        with pytest.raises(ValueError):
            create_app(data_dir=_seed_dir(tmp_path), port=bad)


def test_api_day_malformed_date_is_422(tmp_path):
    """不正な date クエリは FastAPI ネイティブ検証で 422（500 ではない）。"""
    c = _client(tmp_path)
    assert c.get("/api/day?date=abc", headers=HOST_HEADERS).status_code == 422
    assert c.get("/api/day?date=2026-02-30", headers=HOST_HEADERS).status_code == 422


def test_api_day_valid_date_ok(tmp_path):
    r = _client(tmp_path).get("/api/day?date=2026-06-03", headers=HOST_HEADERS)
    assert r.status_code == 200
    assert r.json()["date"] == "2026-06-03"
