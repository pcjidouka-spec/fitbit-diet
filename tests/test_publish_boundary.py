import json
from datetime import date, datetime

from diet.publish import PublicDayRecord


def test_public_day_record_to_public_dict_has_only_allowed_fields():
    """DTO must expose ONLY the 5 allowlisted fields when serialised."""
    rec = PublicDayRecord(
        date=date(2026, 5, 25),
        steps=8234,
        distance_km=5.3,
        exercise_kcal=280,
        weight_kg=71.2,
    )
    d = rec.to_public_dict()
    assert set(d.keys()) == {"date", "steps", "distance_km", "exercise_kcal", "weight_kg"}
    assert d["date"] == "2026-05-25"
    assert d["steps"] == 8234
    assert d["distance_km"] == 5.3
    assert d["exercise_kcal"] == 280
    assert d["weight_kg"] == 71.2


def test_public_day_record_is_frozen():
    """Frozen dataclass prevents accidental mutation in the publish pipeline."""
    import dataclasses
    rec = PublicDayRecord(
        date=date(2026, 5, 25),
        steps=1,
        distance_km=1.0,
        exercise_kcal=1,
        weight_kg=70.0,
    )
    with __import__("pytest").raises(dataclasses.FrozenInstanceError):
        rec.steps = 999  # type: ignore[misc]


# --- Task 5.5: end-to-end boundary (DB → publish) ------------------------
# These tests are LOAD-BEARING for the entire project's privacy guarantee.


def test_intake_notes_never_reach_log_json(tmp_path):
    """★最重要: 食事 note を DB に入れて publish フロー全体を通したとき、
    log.json 文字列に note の痕跡が一切残らないことを検証。"""
    from diet.db import (
        insert_intake_event,
        open_db,
        upsert_daily_activity,
        upsert_daily_weight,
    )
    from diet.publish import build_log_json, build_records_from_db

    conn = open_db(tmp_path / "t.db")
    target = date(2026, 5, 25)
    insert_intake_event(
        conn,
        target,
        datetime(2026, 5, 25, 12, 0),
        600,
        "append",
        note="ラーメン特盛 ホルモン定食",
    )
    insert_intake_event(
        conn,
        target,
        datetime(2026, 5, 25, 19, 0),
        1200,
        "override",
        note="焼肉食べ放題 ビール 5杯",
    )
    upsert_daily_activity(
        conn,
        target,
        steps=8234,
        distance_km=5.3,
        logged_activities_kcal=280,
        marginal_kcal=340,
    )
    upsert_daily_weight(conn, target, 71.2)

    records = build_records_from_db(
        conn, target_dates=[target], exercise_calorie_source="marginal"
    )
    out = build_log_json(records, existing_doc=None)
    serialized = json.dumps(out, ensure_ascii=False)

    # 直接の文字列禁忌
    for forbidden in ["ラーメン", "焼肉", "ホルモン", "ビール", "特盛", "食べ放題"]:
        assert forbidden not in serialized, f"leaked: {forbidden}"
    # フィールド名禁忌
    for forbidden_field in ["note", "intake_kcal", "intake", "kcal_intake", "menu"]:
        assert forbidden_field not in serialized, f"leaked field: {forbidden_field}"


def test_publish_function_does_not_select_intake_events(tmp_path):
    """build_records_from_db が intake_events テーブルを参照しないこと。

    sqlite3.Connection.execute は C-level read-only 属性で patch できないため、
    set_trace_callback を使って実 SQL をキャプチャする。"""
    from diet.db import open_db, upsert_daily_activity, upsert_daily_weight
    from diet.publish import build_records_from_db

    conn = open_db(tmp_path / "t.db")
    target = date(2026, 5, 25)
    upsert_daily_activity(
        conn,
        target,
        steps=1,
        distance_km=1.0,
        logged_activities_kcal=1,
        marginal_kcal=1,
    )
    upsert_daily_weight(conn, target, 70.0)

    captured_sql: list[str] = []
    conn.set_trace_callback(captured_sql.append)
    build_records_from_db(
        conn, target_dates=[target], exercise_calorie_source="marginal"
    )
    conn.set_trace_callback(None)

    intake_sqls = [s for s in captured_sql if "intake_events" in s.lower()]
    assert intake_sqls == [], f"publish path touched intake_events: {intake_sqls}"


def test_publish_function_only_selects_allowed_tables(tmp_path):
    """publish 関数が触ってよいテーブルは daily_activity と daily_weight のみ。
    JOIN intake_events のような巧妙な漏洩経路も検出する。"""
    from diet.db import open_db, upsert_daily_activity, upsert_daily_weight
    from diet.publish import build_records_from_db

    conn = open_db(tmp_path / "t.db")
    target = date(2026, 5, 25)
    upsert_daily_activity(conn, target, 1, 1.0, 1, 1)
    upsert_daily_weight(conn, target, 70.0)

    captured: list[str] = []
    conn.set_trace_callback(captured.append)
    build_records_from_db(
        conn, target_dates=[target], exercise_calorie_source="marginal"
    )
    conn.set_trace_callback(None)

    forbidden_tables = ["intake_events", "config", "fitbit_token"]
    for sql in captured:
        for t in forbidden_tables:
            assert t not in sql.lower(), f"publish touched forbidden table {t}: {sql}"
