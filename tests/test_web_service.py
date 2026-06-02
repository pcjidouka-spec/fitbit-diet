from datetime import date, datetime
from diet.db import open_db, save_config, Config, insert_intake_event, upsert_daily_activity, upsert_daily_weight, load_config
from diet.web.service import get_day_dto
from diet.web.service import (
    get_history_dto, apply_intake, record_weight, auth_status, run_publish,
)


def _seed(tmp_path):
    conn = open_db(tmp_path / "t.db")
    save_config(conn, Config(
        birthday=date(1979, 12, 1), height_cm=169, sex="male",
        timezone="Asia/Tokyo", hpasaneel_path="C:/code/HPasaneel",
        hpasaneel_diet_root="content/diet", exercise_calorie_source=None,
        bootstrap_daily_kcal=2200,
    ))
    return conn


def test_get_day_dto_full(tmp_path):
    conn = _seed(tmp_path)
    d = date(2026, 6, 3)
    upsert_daily_activity(conn, d, steps=8000, distance_km=5.5,
                          total_calories_kcal=2500, active_energy_kcal=300)
    upsert_daily_weight(conn, d, 71.2)
    insert_intake_event(conn, d, datetime(2026, 6, 3, 12, 0), 600, "append", note="昼")
    dto = get_day_dto(conn, load_config(conn), d)

    assert dto["date"] == "2026-06-03"
    assert dto["steps"] == 8000
    assert dto["distance_km"] == 5.5
    assert dto["exercise_kcal"] == 300
    assert dto["weight"]["weight_kg"] == 71.2
    assert dto["weight"]["days_ago"] == 0
    assert dto["bmr"] > 0
    assert dto["intake"]["recorded_sum"] == 600
    assert "balance" in dto


def test_get_day_dto_no_data(tmp_path):
    conn = _seed(tmp_path)
    dto = get_day_dto(conn, load_config(conn), date(2026, 6, 3))
    assert dto["steps"] is None
    assert dto["weight"] is None
    assert dto["bmr"] is None
    assert dto["balance"] is None


def test_apply_intake_appends(tmp_path):
    conn = _seed(tmp_path)
    d = date(2026, 6, 3)
    apply_intake(conn, d, "+500")
    apply_intake(conn, d, "+300")
    dto = get_day_dto(conn, load_config(conn), d)
    assert dto["intake"]["recorded_sum"] == 800


def test_apply_intake_invalid_raises_valueerror(tmp_path):
    conn = _seed(tmp_path)
    import pytest
    with pytest.raises(ValueError):
        apply_intake(conn, date(2026, 6, 3), "abc")


def test_record_weight(tmp_path):
    conn = _seed(tmp_path)
    d = date(2026, 6, 3)
    record_weight(conn, d, 70.5)
    assert get_day_dto(conn, load_config(conn), d)["weight"]["weight_kg"] == 70.5


def test_record_weight_rejects_nonpositive(tmp_path):
    conn = _seed(tmp_path)
    import pytest
    with pytest.raises(ValueError):
        record_weight(conn, date(2026, 6, 3), 0.0)


def test_record_weight_rejects_non_finite(tmp_path):
    conn = _seed(tmp_path)
    import pytest
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError):
            record_weight(conn, date(2026, 6, 3), bad)


def test_run_publish_empty_records_raises(tmp_path):
    """その日の activity/weight が無いと publish せず ValueError（空コミット防止）。"""
    conn = _seed(tmp_path)
    import pytest
    with pytest.raises(ValueError, match="no publishable data"):
        run_publish(conn, load_config(conn), date(2026, 6, 3))


def test_history_dto_shape(tmp_path):
    conn = _seed(tmp_path)
    upsert_daily_weight(conn, date(2026, 6, 1), 72.0)
    rows = get_history_dto(conn, load_config(conn), date(2026, 6, 3), days=7)
    assert isinstance(rows, list)
    assert all("date" in r for r in rows)
    # 秘匿保証: 履歴に食事 kcal 等の秘匿フィールドが混入しないこと。
    allowed = {"date", "steps", "exercise_kcal", "weight_kg"}
    for r in rows:
        assert set(r.keys()) == allowed


def test_auth_status_no_token(tmp_path):
    conn = _seed(tmp_path)
    assert auth_status(conn)["authenticated"] is False
