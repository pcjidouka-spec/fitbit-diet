import sqlite3
import pytest
from pathlib import Path
from diet.db import open_db


def test_creates_all_tables(tmp_path):
    conn = open_db(tmp_path / "t.db")
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    names = {r[0] for r in rows}
    expected = {"config", "intake_events", "daily_activity", "daily_weight", "fitbit_token", "_meta"}
    assert expected.issubset(names)


def test_idempotent(tmp_path):
    p = tmp_path / "t.db"
    open_db(p).close()
    open_db(p).close()  # no error


def test_config_single_row(tmp_path):
    conn = open_db(tmp_path / "t.db")
    conn.execute("INSERT INTO config (id, birthday, height_cm, sex, timezone) VALUES (1, '1979-12-01', 169, 'male', 'Asia/Tokyo')")
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO config (id, birthday, height_cm, sex, timezone) VALUES (2, '2000-01-01', 170, 'male', 'Asia/Tokyo')")


def test_fitbit_token_single_row(tmp_path):
    conn = open_db(tmp_path / "t.db")
    conn.execute("INSERT INTO fitbit_token (id, access_token, refresh_token, expires_at, user_id, rotated_at) VALUES (1, 'A', 'R', '2026-12-31', 'U', '2026-01-01')")
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO fitbit_token (id, access_token, refresh_token, expires_at, user_id, rotated_at) VALUES (2, 'A2', 'R2', '2026-12-31', 'U', '2026-01-01')")
