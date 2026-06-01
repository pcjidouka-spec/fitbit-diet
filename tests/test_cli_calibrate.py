from datetime import date, timedelta

import pytest
from click.testing import CliRunner

from diet.cli import app
from diet.db import Config, load_config, open_db, save_config, upsert_daily_activity


def _seed_config(db_path, source=None):
    conn = open_db(db_path)
    save_config(
        conn,
        Config(
            birthday=date(1979, 12, 1),
            height_cm=169,
            sex="male",
            timezone="Asia/Tokyo",
            hpasaneel_path=None,
            hpasaneel_diet_root="content/diet",
            exercise_calorie_source=source,
            bootstrap_daily_kcal=2000,
        ),
    )
    return conn


@pytest.mark.skip(reason="rewritten in Task 4")
def test_calibrate_displays_recent_calories(tmp_path, monkeypatch):
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    conn = _seed_config(tmp_path / "diet.db")
    today = date.today()
    for offset in range(3):
        d = today - timedelta(days=offset)
        upsert_daily_activity(
            conn,
            d,
            steps=5000 + offset * 100,
            distance_km=3.5 + offset * 0.1,
            logged_activities_kcal=200 + offset * 10,
            marginal_kcal=300 + offset * 10,
        )
    runner = CliRunner()
    # Choose marginal
    result = runner.invoke(app, ["calibrate", "--days", "5"], input="marginal\n")
    assert result.exit_code == 0, result.output
    assert "logged_activities" in result.output
    assert "marginal" in result.output
    cfg2 = load_config(open_db(tmp_path / "diet.db"))
    assert cfg2.exercise_calorie_source == "marginal"


@pytest.mark.skip(reason="rewritten in Task 4")
def test_calibrate_decide_later_keeps_source_none(tmp_path, monkeypatch):
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    _seed_config(tmp_path / "diet.db", source=None)
    runner = CliRunner()
    result = runner.invoke(app, ["calibrate", "--days", "3"], input="decide_later\n")
    assert result.exit_code == 0, result.output
    assert "未確定" in result.output
    cfg2 = load_config(open_db(tmp_path / "diet.db"))
    assert cfg2.exercise_calorie_source is None
