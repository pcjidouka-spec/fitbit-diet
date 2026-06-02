from datetime import date, datetime
from diet.db import open_db, save_config, Config, insert_intake_event, upsert_daily_activity, upsert_daily_weight, load_config
from diet.web.service import get_day_dto


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
