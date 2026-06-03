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


def test_auth_runs_oauth_flow(tmp_path, monkeypatch, mocker):
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    _seed_config(tmp_path / "diet.db")
    spy = mocker.patch("diet.oauth.run_init_flow", return_value=None)
    runner = CliRunner()
    result = runner.invoke(app, ["auth"])
    assert result.exit_code == 0, result.output
    spy.assert_called_once()
    _, kwargs = spy.call_args
    assert kwargs.get("port") == 8765


def test_auth_custom_port(tmp_path, monkeypatch, mocker):
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    _seed_config(tmp_path / "diet.db")
    spy = mocker.patch("diet.oauth.run_init_flow", return_value=None)
    runner = CliRunner()
    result = runner.invoke(app, ["auth", "--port", "9999"])
    assert result.exit_code == 0, result.output
    _, kwargs = spy.call_args
    assert kwargs.get("port") == 9999


def test_auth_without_config_fails_cleanly(tmp_path, monkeypatch):
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    runner = CliRunner()
    result = runner.invoke(app, ["auth"])
    assert result.exit_code != 0
    assert "config" in result.output
