from click.testing import CliRunner

from diet.cli import app


def test_init_writes_config_and_runs_oauth_and_sync(tmp_path, monkeypatch, mocker):
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "CID")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "CSEC")
    oauth_spy = mocker.patch("diet.oauth.run_init_flow", return_value=None)
    sync_spy = mocker.patch("diet.cli._run_initial_sync", return_value=None)
    runner = CliRunner()
    inputs = "1979-12-01\n169\nmale\n\nC:/code/HPasaneel\ncontent/diet\n2000\n"
    result = runner.invoke(app, ["init"], input=inputs)
    assert result.exit_code == 0, result.output
    db = tmp_path / "diet.db"
    assert db.exists()
    from diet.db import load_config, open_db

    cfg = load_config(open_db(db))
    assert cfg.height_cm == 169
    assert cfg.bootstrap_daily_kcal == 2000
    oauth_spy.assert_called_once()
    sync_spy.assert_called_once()
    args, kwargs = sync_spy.call_args
    assert kwargs.get("days") == 30 or (len(args) >= 2 and args[1] == 30)


def test_init_baseline_skip_with_enter(tmp_path, monkeypatch, mocker):
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "CID")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "CSEC")
    mocker.patch("diet.oauth.run_init_flow", return_value=None)
    mocker.patch("diet.cli._run_initial_sync", return_value=None)
    runner = CliRunner()
    inputs = "1979-12-01\n169\nmale\n\nC:/code/HPasaneel\ncontent/diet\n\n"
    result = runner.invoke(app, ["init"], input=inputs)
    assert result.exit_code == 0, result.output
    from diet.db import load_config, open_db

    cfg = load_config(open_db(tmp_path / "diet.db"))
    assert cfg.bootstrap_daily_kcal is None
