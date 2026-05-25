from datetime import date

from click.testing import CliRunner

from diet.cli import app
from diet.db import Config, load_config, open_db, save_config


def _seed_config(db_path, baseline=2000):
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
            bootstrap_daily_kcal=baseline,
        ),
    )


def test_baseline_updates_bootstrap(tmp_path, monkeypatch):
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    _seed_config(tmp_path / "diet.db", baseline=2000)
    runner = CliRunner()
    result = runner.invoke(app, ["baseline", "2200"])
    assert result.exit_code == 0, result.output
    assert "2200" in result.output
    cfg2 = load_config(open_db(tmp_path / "diet.db"))
    assert cfg2.bootstrap_daily_kcal == 2200


def test_baseline_rejects_non_positive(tmp_path, monkeypatch):
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    _seed_config(tmp_path / "diet.db")
    runner = CliRunner()
    result = runner.invoke(app, ["baseline", "0"])
    assert result.exit_code != 0


def test_baseline_without_config_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    open_db(tmp_path / "diet.db")
    runner = CliRunner()
    result = runner.invoke(app, ["baseline", "2100"])
    assert result.exit_code != 0
    assert "config" in result.output
