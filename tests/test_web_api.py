from datetime import date, datetime, timedelta
from fastapi.testclient import TestClient
from diet.db import open_db, save_config, save_token_atomic, Config, Token
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


def _seed_token(tmp_path):
    """Seed an OAuth token so /api/sync passes its token-presence gate."""
    conn = open_db(tmp_path / "diet.db")
    save_token_atomic(conn, Token(
        access_token="A", refresh_token="R",
        expires_at=datetime.now() + timedelta(hours=1), user_id="U",
    ))
    conn.close()


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


# ---------------------------------------------------------------------------
# POST endpoints
# ---------------------------------------------------------------------------

def _client_with_csrf(tmp_path):
    """index から CSRF トークンを取り出し POST 用ヘッダを組む。"""
    app = create_app(data_dir=_seed_dir(tmp_path), port=PORT)
    client = TestClient(app, base_url=f"http://127.0.0.1:{PORT}")
    html = client.get("/", headers=HOST_HEADERS).text
    import re
    token = re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)
    headers = {**HOST_HEADERS, "origin": f"http://127.0.0.1:{PORT}",
               "x-csrf-token": token}
    return client, headers


def test_post_intake_appends(tmp_path):
    client, h = _client_with_csrf(tmp_path)
    r = client.post("/api/intake", json={"raw": "+600"}, headers=h)
    assert r.status_code == 200
    day = client.get("/api/day", headers=HOST_HEADERS).json()
    assert day["intake"]["recorded_sum"] == 600


def test_post_intake_bad_input_400(tmp_path):
    client, h = _client_with_csrf(tmp_path)
    r = client.post("/api/intake", json={"raw": "abc"}, headers=h)
    assert r.status_code == 400
    assert r.json()["code"] == "bad_intake"


def test_post_weight_nonpositive_400(tmp_path):
    client, h = _client_with_csrf(tmp_path)
    r = client.post("/api/weight", json={"kg": 0}, headers=h)
    assert r.status_code == 400
    assert r.json()["code"] == "bad_weight"


def test_post_sync_failure_is_502(tmp_path, monkeypatch):
    client, h = _client_with_csrf(tmp_path)
    _seed_token(tmp_path)
    def boom(conn, days): raise RuntimeError("network down")
    monkeypatch.setattr("diet.web.service.run_sync", boom)
    r = client.post("/api/sync", json={"days": 3}, headers=h)
    assert r.status_code == 502
    assert r.json()["ok"] is False
    assert r.json()["code"] == "sync_failed"


def test_post_sync_missing_token_signals_reauth(tmp_path):
    """token 不在（migration 後など）も reauth_required（generic 502 ではない）。"""
    client, h = _client_with_csrf(tmp_path)  # config あり・token なし
    r = client.post("/api/sync", json={"days": 3}, headers=h)
    assert r.status_code == 401
    assert r.json()["code"] == "reauth_required"
    assert "diet auth" in r.json()["detail"]


def test_post_publish_conflict_409(tmp_path, monkeypatch):
    import subprocess
    client, h = _client_with_csrf(tmp_path)
    def boom(conn, cfg, target):
        raise subprocess.CalledProcessError(1, ["git", "push"])
    monkeypatch.setattr("diet.web.service.run_publish", boom)
    r = client.post("/api/publish", json={}, headers=h)
    assert r.status_code == 409
    assert "git pull --rebase" in r.json()["detail"]


def test_post_sync_revoked_token_signals_reauth(tmp_path, monkeypatch):
    """refresh token 失効は generic sync_failed でなく reauth_required を返す。"""
    from diet.cli_helpers import RefreshTokenError
    client, h = _client_with_csrf(tmp_path)
    _seed_token(tmp_path)
    def boom(conn, days):
        raise RefreshTokenError("invalid_grant")
    monkeypatch.setattr("diet.web.service.run_sync", boom)
    r = client.post("/api/sync", json={"days": 3}, headers=h)
    assert r.status_code == 401
    assert r.json()["code"] == "reauth_required"
    assert "diet auth" in r.json()["detail"]


def test_post_publish_no_data_distinct_code(tmp_path):
    """その日のデータが無い publish は publish_no_data（unconfigured ではない）。"""
    client, h = _client_with_csrf(tmp_path)
    # 実 run_publish を通す: config はあるが activity/weight 未投入 → PublishNoData。
    r = client.post("/api/publish", json={}, headers=h)
    assert r.status_code == 409
    assert r.json()["code"] == "publish_no_data"


def test_post_sync_partial_warnings_ok(tmp_path, monkeypatch):
    """一部だけ失敗（synced>0）→ ok:true + warnings（鮮度をブラウザに伝える）。"""
    from diet.cli_helpers import SyncOutcome
    client, h = _client_with_csrf(tmp_path)
    _seed_token(tmp_path)
    monkeypatch.setattr("diet.web.service.run_sync",
                        lambda conn, days: SyncOutcome(
                            synced=2, days=days,
                            warnings=["sync warning (2026-06-02): boom"]))
    r = client.post("/api/sync", json={"days": 3}, headers=h)
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert len(r.json()["warnings"]) == 1


def test_post_sync_all_days_failed_is_502(tmp_path, monkeypatch):
    """activity を 1 件も書けず (synced==0) → ok:false / 502（サイレント成功を防ぐ）。"""
    from diet.cli_helpers import SyncOutcome
    client, h = _client_with_csrf(tmp_path)
    _seed_token(tmp_path)
    monkeypatch.setattr("diet.web.service.run_sync",
                        lambda conn, days: SyncOutcome(
                            synced=0, days=days,
                            warnings=[f"w{i}" for i in range(days)]))
    r = client.post("/api/sync", json={"days": 3}, headers=h)
    assert r.status_code == 502
    assert r.json()["ok"] is False
    assert r.json()["code"] == "sync_all_days_failed"


def test_post_sync_activity_ok_weight_failed_is_partial(tmp_path, monkeypatch):
    """全日 activity 成功・weight だけ失敗 (synced==days, warnings>0) → 誤って 502 にしない。"""
    from diet.cli_helpers import SyncOutcome
    client, h = _client_with_csrf(tmp_path)
    _seed_token(tmp_path)
    monkeypatch.setattr("diet.web.service.run_sync",
                        lambda conn, days: SyncOutcome(
                            synced=days, days=days,
                            warnings=[f"weight fail {i}" for i in range(days)]))
    r = client.post("/api/sync", json={"days": 3}, headers=h)
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["synced"] == 3


def test_post_sync_clean_ok(tmp_path, monkeypatch):
    from diet.cli_helpers import SyncOutcome
    client, h = _client_with_csrf(tmp_path)
    _seed_token(tmp_path)
    monkeypatch.setattr("diet.web.service.run_sync",
                        lambda conn, days: SyncOutcome(synced=days, days=days, warnings=[]))
    r = client.post("/api/sync", json={"days": 3}, headers=h)
    assert r.status_code == 200
    assert r.json() == {"ok": True, "synced": 3, "warnings": []}


def test_post_publish_schema_invalid_is_409(tmp_path, monkeypatch):
    """既存 log.json がスキーマ違反 → 500 でなく 409 publish_invalid。"""
    import jsonschema
    client, h = _client_with_csrf(tmp_path)
    def boom(conn, cfg, target):
        raise jsonschema.ValidationError("extra field not allowed")
    monkeypatch.setattr("diet.web.service.run_publish", boom)
    r = client.post("/api/publish", json={}, headers=h)
    assert r.status_code == 409
    assert r.json()["code"] == "publish_invalid"


def test_post_sync_days_zero_is_422(tmp_path):
    client, h = _client_with_csrf(tmp_path)
    r = client.post("/api/sync", json={"days": 0}, headers=h)
    assert r.status_code == 422


def test_post_sync_no_config_is_409(tmp_path):
    """config 未初期化なら sync は 409 no_config（502 ではない）。"""
    import re
    from diet.db import open_db
    open_db(tmp_path / "diet.db")  # DB は作るが config は保存しない
    app = create_app(data_dir=tmp_path, port=PORT)
    client = TestClient(app, base_url=f"http://127.0.0.1:{PORT}")
    token = re.search(r'name="csrf-token" content="([^"]+)"',
                      client.get("/", headers=HOST_HEADERS).text).group(1)
    h = {**HOST_HEADERS, "origin": f"http://127.0.0.1:{PORT}", "x-csrf-token": token}
    r = client.post("/api/sync", json={"days": 3}, headers=h)
    assert r.status_code == 409
    assert r.json()["code"] == "no_config"
