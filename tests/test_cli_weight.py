from datetime import date, datetime
from zoneinfo import ZoneInfo

from click.testing import CliRunner

from diet.cli import app
from diet.db import Config, get_latest_weight_on_or_before, open_db, save_config


def _seed_config(db_path):
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
            exercise_calorie_source="marginal",
            bootstrap_daily_kcal=2000,
        ),
    )
    return conn


def test_weight_records_with_explicit_date(tmp_path, monkeypatch):
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    _seed_config(tmp_path / "diet.db")
    runner = CliRunner()
    result = runner.invoke(app, ["weight", "71.2", "--date", "2026-05-25"])
    assert result.exit_code == 0, result.output
    assert "71.2" in result.output
    assert "2026-05-25" in result.output
    conn = open_db(tmp_path / "diet.db")
    row = get_latest_weight_on_or_before(conn, date(2026, 5, 25))
    assert row is not None
    assert row.weight_kg == 71.2
    assert row.date == date(2026, 5, 25)


def test_weight_defaults_to_today_in_configured_tz(tmp_path, monkeypatch):
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    _seed_config(tmp_path / "diet.db")
    runner = CliRunner()
    result = runner.invoke(app, ["weight", "70.5"])
    assert result.exit_code == 0, result.output
    today = datetime.now(ZoneInfo("Asia/Tokyo")).date()
    assert today.isoformat() in result.output
    conn = open_db(tmp_path / "diet.db")
    row = get_latest_weight_on_or_before(conn, today)
    assert row.weight_kg == 70.5


def test_weight_without_config_fails_cleanly(tmp_path, monkeypatch):
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    open_db(tmp_path / "diet.db")  # empty config
    runner = CliRunner()
    result = runner.invoke(app, ["weight", "71.0"])
    assert result.exit_code != 0
    assert "config" in result.output
