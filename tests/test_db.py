import sqlite3
import pytest
from datetime import date, datetime, timedelta
from pathlib import Path
from diet.db import (
    open_db,
    insert_intake_event,
    get_events_for_date,
    get_events_in_range,
)
from diet.intake import IntakeEvent


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


# ---------- Task 2.2: intake_events CRUD ----------


def test_insert_and_get_event(tmp_path):
    conn = open_db(tmp_path / "t.db")
    insert_intake_event(conn, date(2026, 5, 25), datetime(2026, 5, 25, 12, 0), 500, "append", note="ラーメン特盛")
    events = get_events_for_date(conn, date(2026, 5, 25))
    assert len(events) == 1
    assert events[0].kcal == 500
    assert events[0].op == "append"


def test_get_events_in_range_half_open(tmp_path):
    conn = open_db(tmp_path / "t.db")
    target = date(2026, 5, 25)
    for offset in [0, 1, 14, 15]:
        d = target - timedelta(days=offset)
        insert_intake_event(conn, d, datetime(d.year, d.month, d.day, 12, 0), 100 * offset, "override")
    history = get_events_in_range(conn, start=target - timedelta(days=14), end=target)
    assert (target - timedelta(days=14)) in history
    assert (target - timedelta(days=15)) not in history
    assert target not in history


def test_get_events_for_date_ordering(tmp_path):
    """Same date events return in (timestamp ASC, id ASC) order"""
    conn = open_db(tmp_path / "t.db")
    d = date(2026, 5, 25)
    insert_intake_event(conn, d, datetime(2026, 5, 25, 13, 0), 100, "append")
    insert_intake_event(conn, d, datetime(2026, 5, 25, 12, 0), 200, "append")
    events = get_events_for_date(conn, d)
    assert events[0].kcal == 200  # earlier timestamp
    assert events[1].kcal == 100
