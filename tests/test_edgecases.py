"""Phase 9: Edge case integration tests (spec §11).

Each test exercises a single failure mode end-to-end through the orchestrator,
CLI, or publish layer. Heavy imports stay inside the test bodies so collection
remains snappy.
"""
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from click.testing import CliRunner

from diet.cli import app
from diet.publish import PublicDayRecord, publish_to_hpasaneel


def _init_repo(p: Path) -> None:
    """Initialise a real git repo with one initial commit so we have HEAD."""
    subprocess.run(["git", "init"], cwd=p, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=p, check=True
    )
    subprocess.run(["git", "config", "user.name", "test"], cwd=p, check=True)
    (p / "README.md").write_text("# t")
    subprocess.run(["git", "add", "."], cwd=p, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=p, check=True, capture_output=True
    )


# --- Task 9.1: Fitbit sync 失敗オフライン耐性 -------------------------------


def test_orchestrator_continues_when_sync_fails(tmp_path, monkeypatch, mocker):
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FITBIT_CLIENT_ID", "CID")
    monkeypatch.setenv("FITBIT_CLIENT_SECRET", "CSEC")
    from diet.db import (
        Config,
        Token,
        get_events_for_date,
        open_db,
        save_config,
        save_token_atomic,
        upsert_daily_weight,
    )

    conn = open_db(tmp_path / "diet.db")
    target = date(2026, 5, 25)
    save_config(
        conn,
        Config(
            date(1979, 12, 1),
            169,
            "male",
            "Asia/Tokyo",
            str(tmp_path / "hp"),
            "content/diet",
            "marginal",
            2000,
        ),
    )
    save_token_atomic(conn, Token("A", "R", datetime(2030, 1, 1), "UID"))
    upsert_daily_weight(conn, target, 71.2)
    mocker.patch(
        "diet.cli_helpers.run_sync_async", side_effect=Exception("network down")
    )
    mocker.patch("click.prompt", return_value="=2300")
    mocker.patch("click.confirm", return_value=False)
    from diet.orchestrator import run_daily_flow

    run_daily_flow(data_dir=tmp_path, target_date=target)
    # sync 失敗でも食事は記録された
    events = get_events_for_date(conn, target)
    assert len(events) == 1
    assert events[0].kcal == 2300


# --- Task 9.2: 体重 fallback (N 日前 + 日付表示) -----------------------------


def test_weight_fallback_displays_days_ago(tmp_path, monkeypatch, mocker, capsys):
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FITBIT_CLIENT_ID", "CID")
    monkeypatch.setenv("FITBIT_CLIENT_SECRET", "CSEC")
    from diet.db import (
        Config,
        Token,
        open_db,
        save_config,
        save_token_atomic,
        upsert_daily_activity,
        upsert_daily_weight,
    )

    conn = open_db(tmp_path / "diet.db")
    target = date(2026, 5, 25)
    save_config(
        conn,
        Config(
            date(1979, 12, 1),
            169,
            "male",
            "Asia/Tokyo",
            None,
            "content/diet",
            "marginal",
            2000,
        ),
    )
    save_token_atomic(conn, Token("A", "R", datetime(2030, 1, 1), "UID"))
    upsert_daily_activity(conn, target, 8000, 5.0, 250, 300)
    # 体重は 3 日前のみ
    upsert_daily_weight(conn, target - timedelta(days=3), 71.5)
    mocker.patch("diet.cli_helpers.run_sync_async", return_value=None)
    mocker.patch("click.prompt", return_value="=2000")
    mocker.patch("click.confirm", return_value=False)
    from diet.orchestrator import run_daily_flow

    run_daily_flow(data_dir=tmp_path, target_date=target)
    captured = capsys.readouterr()
    assert "71.5" in captured.out
    assert "2026-05-22" in captured.out  # 計測日表示
    assert "3日前" in captured.out  # fallback 警告 (N 日前)
