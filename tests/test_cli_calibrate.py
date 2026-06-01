from datetime import date, timedelta

from click.testing import CliRunner

from diet.cli import app
from diet.db import Config, open_db, save_config, upsert_daily_activity


def _seed_config(db_path):
    conn = open_db(db_path)
    save_config(conn, Config(
        birthday=date(1979, 12, 1), height_cm=169, sex="male", timezone="Asia/Tokyo",
        hpasaneel_path=None, hpasaneel_diet_root="content/diet",
        exercise_calorie_source=None, bootstrap_daily_kcal=2000,
    ))
    return conn


def test_calibrate_displays_recent_activity(tmp_path, monkeypatch):
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    conn = _seed_config(tmp_path / "diet.db")
    today = date.today()
    for offset in range(3):
        d = today - timedelta(days=offset)
        upsert_daily_activity(conn, d, steps=5000 + offset * 100, distance_km=3.5,
                              total_calories_kcal=1800 + offset, active_energy_kcal=300 + offset)
    runner = CliRunner()
    result = runner.invoke(app, ["calibrate", "--days", "5"])
    assert result.exit_code == 0, result.output
    assert "active_energy" in result.output
    assert "total_calories" in result.output
