import re
from datetime import date

from fastapi.testclient import TestClient

from diet.db import Config, open_db, save_config
from diet.web.app import create_app
from diet.web.security import is_loopback_host, host_header_ok, origin_ok

PORT = 8771


def _client(tmp_path):
    conn = open_db(tmp_path / "diet.db")
    save_config(conn, Config(
        birthday=date(1979, 12, 1), height_cm=169, sex="male",
        timezone="Asia/Tokyo", hpasaneel_path=str(tmp_path / "hp"),
        hpasaneel_diet_root="content/diet", exercise_calorie_source=None,
        bootstrap_daily_kcal=2200,
    ))
    conn.close()
    app = create_app(data_dir=tmp_path, port=PORT)
    return TestClient(app, base_url=f"http://127.0.0.1:{PORT}")


def test_is_loopback_host():
    assert is_loopback_host("127.0.0.1")
    assert is_loopback_host("::1")
    assert is_loopback_host("localhost")
    assert not is_loopback_host("192.168.1.5")
    assert not is_loopback_host("0.0.0.0")


def test_host_header_ok():
    assert host_header_ok("127.0.0.1:8770", 8770)
    assert host_header_ok("localhost:8770", 8770)
    assert not host_header_ok("evil.com:8770", 8770)
    assert not host_header_ok("127.0.0.1:9999", 8770)  # wrong port


def test_origin_ok():
    assert origin_ok("http://127.0.0.1:8770", 8770)
    assert origin_ok("http://localhost:8770", 8770)
    assert not origin_ok("http://evil.com", 8770)
    assert not origin_ok(None, 8770)  # missing Origin on mutation -> reject


def test_malformed_ipv6_port_does_not_raise():
    """`[::1]:abc` のような不正ポートは例外でなく拒否（500 でなく 400/403 経路）。"""
    assert not host_header_ok("[::1]:abc", 8770)
    assert not origin_ok("http://[::1]:abc", 8770)
    # 正当な IPv6 + ポートは通る。
    assert host_header_ok("[::1]:8770", 8770)


def test_oversized_and_out_of_range_ports_rejected():
    """isdigit() を通る巨大/範囲外ポートでも int() 例外を出さず拒否する。"""
    huge = "1" * 5000  # int() の文字列変換上限を超える数字列
    assert not host_header_ok(f"127.0.0.1:{huge}", 8770)
    assert not origin_ok(f"http://127.0.0.1:{huge}", 8770)
    assert not host_header_ok("127.0.0.1:99999", 8770)  # 範囲外 (>65535)


# ---------------------------------------------------------------------------
# Integration tests — drive create_app() via TestClient
# ---------------------------------------------------------------------------

def test_bad_host_rejected(tmp_path):
    r = _client(tmp_path).get("/api/day", headers={"host": "evil.com"})
    assert r.status_code == 400
    assert r.json()["code"] == "bad_host"


def test_mutation_without_origin_rejected(tmp_path):
    """Origin チェック単独の回帰防御: 有効 CSRF トークン付きでも Origin が無ければ
    bad_origin で弾く（CSRF が先に通ることで Origin 防御の喪失を見逃さない）。"""
    client = _client(tmp_path)
    host_h = {"host": f"127.0.0.1:{PORT}"}
    token = re.search(r'name="csrf-token" content="([^"]+)"',
                      client.get("/", headers=host_h).text).group(1)
    r = client.post("/api/intake", json={"raw": "+1"},
                    headers={**host_h, "x-csrf-token": token})  # Origin 欠落
    assert r.status_code == 403
    assert r.json()["code"] == "bad_origin"


def test_mutation_bad_origin_rejected(tmp_path):
    r = _client(tmp_path).post("/api/intake", json={"raw": "+1"},
                               headers={"host": f"127.0.0.1:{PORT}",
                                        "origin": "http://evil.com"})
    assert r.status_code == 403
    assert r.json()["code"] == "bad_origin"


def test_mutation_missing_csrf_rejected(tmp_path):
    r = _client(tmp_path).post("/api/intake", json={"raw": "+1"},
                               headers={"host": f"127.0.0.1:{PORT}",
                                        "origin": f"http://127.0.0.1:{PORT}"})
    assert r.status_code == 403
    assert r.json()["code"] == "bad_csrf"


def test_safe_method_with_valid_host_allowed(tmp_path):
    """正当な Host の GET はミドルウェアを通過しハンドラに到達する。"""
    r = _client(tmp_path).get("/api/day", headers={"host": f"127.0.0.1:{PORT}"})
    assert r.status_code == 200


def test_mutation_with_valid_origin_and_csrf_allowed(tmp_path):
    """正当な Host+Origin+CSRF の POST は通過する（全防御を満たせば許可）。"""
    client = _client(tmp_path)
    host_h = {"host": f"127.0.0.1:{PORT}"}
    token = re.search(r'name="csrf-token" content="([^"]+)"',
                      client.get("/", headers=host_h).text).group(1)
    r = client.post("/api/intake", json={"raw": "+500"},
                    headers={**host_h, "origin": f"http://127.0.0.1:{PORT}",
                             "x-csrf-token": token})
    assert r.status_code == 200
