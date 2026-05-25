from datetime import date

from click.testing import CliRunner

from diet.cli import app


def test_bare_diet_invokes_run_daily_flow_no_date(tmp_path, monkeypatch, mocker):
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    spy = mocker.patch("diet.orchestrator.run_daily_flow", return_value=None)
    runner = CliRunner()
    result = runner.invoke(app, [])
    assert result.exit_code == 0, result.output
    spy.assert_called_once()
    _, kwargs = spy.call_args
    assert kwargs.get("target_date") is None


def test_bare_diet_with_explicit_date(tmp_path, monkeypatch, mocker):
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    spy = mocker.patch("diet.orchestrator.run_daily_flow", return_value=None)
    runner = CliRunner()
    result = runner.invoke(app, ["--date", "2026-05-25"])
    assert result.exit_code == 0, result.output
    spy.assert_called_once()
    _, kwargs = spy.call_args
    assert kwargs.get("target_date") == date(2026, 5, 25)


def test_bare_diet_passes_data_dir(tmp_path, monkeypatch, mocker):
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    spy = mocker.patch("diet.orchestrator.run_daily_flow", return_value=None)
    runner = CliRunner()
    result = runner.invoke(app, [])
    assert result.exit_code == 0, result.output
    _, kwargs = spy.call_args
    assert kwargs.get("data_dir") == tmp_path
