from datetime import date

from click.testing import CliRunner

from diet.cli import app
from diet.db import Config, open_db, save_config


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


def test_show_invokes_orchestrator_with_explicit_date(tmp_path, monkeypatch, mocker):
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    _seed_config(tmp_path / "diet.db")
    spy = mocker.patch("diet.orchestrator.run_show_only", return_value=None)
    runner = CliRunner()
    result = runner.invoke(app, ["show", "--date", "2026-05-25"])
    assert result.exit_code == 0, result.output
    spy.assert_called_once()
    args, kwargs = spy.call_args
    # signature: run_show_only(data_dir, target_date)
    assert args[1] == date(2026, 5, 25)


def test_show_defaults_to_today(tmp_path, monkeypatch, mocker):
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    _seed_config(tmp_path / "diet.db")
    spy = mocker.patch("diet.orchestrator.run_show_only", return_value=None)
    runner = CliRunner()
    result = runner.invoke(app, ["show"])
    assert result.exit_code == 0, result.output
    spy.assert_called_once()
    args, _ = spy.call_args
    assert isinstance(args[1], date)


def test_show_without_config_fails_cleanly(tmp_path, monkeypatch):
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    open_db(tmp_path / "diet.db")
    runner = CliRunner()
    result = runner.invoke(app, ["show"])
    assert result.exit_code != 0
    assert "config" in result.output
