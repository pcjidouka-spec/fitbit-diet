import sqlite3
import pytest
from datetime import date, datetime, timedelta
from pathlib import Path
from diet.db import (
    open_db,
    insert_intake_event,
    get_events_for_date,
    get_events_in_range,
    upsert_daily_activity,
    get_daily_activity,
    upsert_daily_weight,
    get_latest_weight_on_or_before,
    Config,
    save_config,
    load_config,
    Token,
    save_token_atomic,
    load_token,
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


# ---------- Task 2.3: daily_activity / daily_weight + no-time-machine ----------


def test_daily_activity_upsert(tmp_path):
    conn = open_db(tmp_path / "t.db")
    upsert_daily_activity(conn, date(2026, 5, 25), 8234, 5.3, 280, 340)
    a = get_daily_activity(conn, date(2026, 5, 25))
    assert a.steps == 8234
    upsert_daily_activity(conn, date(2026, 5, 25), 9000, 6.0, 300, 360)
    a2 = get_daily_activity(conn, date(2026, 5, 25))
    assert a2.steps == 9000


def test_latest_weight_on_or_before(tmp_path):
    conn = open_db(tmp_path / "t.db")
    upsert_daily_weight(conn, date(2026, 5, 20), 72.0)
    upsert_daily_weight(conn, date(2026, 5, 22), 71.5)
    assert get_latest_weight_on_or_before(conn, date(2026, 5, 25)).weight_kg == 71.5


def test_weight_no_time_machine(tmp_path):
    """対象日より未来の体重は使わない"""
    conn = open_db(tmp_path / "t.db")
    upsert_daily_weight(conn, date(2026, 5, 22), 71.5)
    upsert_daily_weight(conn, date(2026, 5, 26), 71.0)  # 未来
    w = get_latest_weight_on_or_before(conn, date(2026, 5, 25))
    assert w.weight_kg == 71.5


def test_get_weight_returns_none_when_empty(tmp_path):
    conn = open_db(tmp_path / "t.db")
    assert get_latest_weight_on_or_before(conn, date(2026, 5, 25)) is None


# ---------- Task 2.4: config + atomic token rotation ----------


def test_config_round_trip(tmp_path):
    conn = open_db(tmp_path / "t.db")
    cfg = Config(birthday=date(1979, 12, 1), height_cm=169, sex="male", timezone="Asia/Tokyo",
                 hpasaneel_path="C:/code/HPasaneel", hpasaneel_diet_root="content/diet",
                 exercise_calorie_source="marginal", bootstrap_daily_kcal=2000)
    save_config(conn, cfg)
    assert load_config(conn) == cfg


def test_config_update_overwrites(tmp_path):
    conn = open_db(tmp_path / "t.db")
    cfg1 = Config(date(1979, 12, 1), 169, "male", "Asia/Tokyo", None, "content/diet", None, None)
    save_config(conn, cfg1)
    cfg2 = Config(date(1979, 12, 1), 170, "male", "Asia/Tokyo", None, "content/diet", "marginal", 2200)
    save_config(conn, cfg2)
    loaded = load_config(conn)
    assert loaded.height_cm == 170
    assert loaded.exercise_calorie_source == "marginal"


def test_token_atomic_replacement(tmp_path):
    conn = open_db(tmp_path / "t.db")
    t1 = Token("A1", "R1", datetime(2026, 12, 31), "UID")
    save_token_atomic(conn, t1)
    t2 = Token("A2", "R2", datetime(2027, 1, 1), "UID")
    save_token_atomic(conn, t2)
    loaded = load_token(conn)
    assert loaded.access_token == "A2"
    assert conn.execute("SELECT COUNT(*) FROM fitbit_token").fetchone()[0] == 1
