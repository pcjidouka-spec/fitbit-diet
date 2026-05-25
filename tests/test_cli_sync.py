from datetime import datetime, timedelta

from click.testing import CliRunner

from diet.cli import app
from diet.db import Token, open_db, save_token_atomic


def _seed_token(db_path):
    conn = open_db(db_path)
    save_token_atomic(
        conn,
        Token(
            access_token="A",
            refresh_token="R",
            expires_at=datetime.now() + timedelta(hours=1),
            user_id="U",
        ),
    )


def test_sync_without_auth_fails_cleanly(tmp_path, monkeypatch):
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    # No token in DB
    open_db(tmp_path / "diet.db")
    runner = CliRunner()
    result = runner.invoke(app, ["sync", "--days", "3"])
    assert result.exit_code != 0
    assert "Not authenticated" in result.output


def test_sync_with_auth_invokes_async_helper(tmp_path, monkeypatch, mocker):
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    _seed_token(tmp_path / "diet.db")

    async def fake_run(conn, days):
        fake_run.called_with = (conn, days)

    fake_run.called_with = None
    mocker.patch("diet.cli_helpers.run_sync_async", new=fake_run)
    runner = CliRunner()
    result = runner.invoke(app, ["sync", "--days", "5"])
    assert result.exit_code == 0, result.output
    assert "sync complete (5 days)" in result.output
    assert fake_run.called_with is not None
    assert fake_run.called_with[1] == 5


def test_sync_default_days_is_7(tmp_path, monkeypatch, mocker):
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    _seed_token(tmp_path / "diet.db")

    async def fake_run(conn, days):
        fake_run.days = days

    fake_run.days = None
    mocker.patch("diet.cli_helpers.run_sync_async", new=fake_run)
    runner = CliRunner()
    result = runner.invoke(app, ["sync"])
    assert result.exit_code == 0, result.output
    assert fake_run.days == 7
