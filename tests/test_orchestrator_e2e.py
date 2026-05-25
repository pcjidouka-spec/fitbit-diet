from datetime import date, datetime, timedelta

import pytest

from diet.db import (
    Config,
    Token,
    get_events_for_date,
    insert_intake_event,
    open_db,
    save_config,
    save_token_atomic,
    upsert_daily_activity,
    upsert_daily_weight,
)


@pytest.fixture
def setup_db(tmp_path):
    conn = open_db(tmp_path / "diet.db")
    save_config(
        conn,
        Config(
            birthday=date(1979, 12, 1),
            height_cm=169,
            sex="male",
            timezone="Asia/Tokyo",
            hpasaneel_path=str(tmp_path / "fake_hp"),
            hpasaneel_diet_root="content/diet",
            exercise_calorie_source="marginal",
            bootstrap_daily_kcal=2000,
        ),
    )
    save_token_atomic(conn, Token("A1", "R1", datetime(2030, 1, 1), "UID"))
    return tmp_path, conn


def test_orchestrator_complete_day_no_publish(setup_db, monkeypatch, mocker):
    tmp_path, conn = setup_db
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FITBIT_CLIENT_ID", "CID")
    monkeypatch.setenv("FITBIT_CLIENT_SECRET", "CSEC")
    target = date(2026, 5, 25)
    upsert_daily_activity(
        conn, target, steps=8234, distance_km=5.3,
        logged_activities_kcal=280, marginal_kcal=300,
    )
    upsert_daily_weight(conn, target, 71.2)
    mocker.patch("diet.cli_helpers.run_sync_async", return_value=None)
    mocker.patch("click.prompt", return_value="=2300")
    mocker.patch("click.confirm", return_value=False)
    from diet.orchestrator import run_daily_flow
    run_daily_flow(data_dir=tmp_path, target_date=target)
    events = get_events_for_date(conn, target)
    assert len(events) == 1
    assert events[0].kcal == 2300
    assert events[0].op == "override"


def test_orchestrator_skip_intake_uses_avg(setup_db, monkeypatch, mocker):
    tmp_path, conn = setup_db
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FITBIT_CLIENT_ID", "CID")
    monkeypatch.setenv("FITBIT_CLIENT_SECRET", "CSEC")
    target = date(2026, 5, 25)
    # 14 days of complete-day history with =2000
    for i in range(1, 15):
        d = target - timedelta(days=i)
        insert_intake_event(
            conn, d, datetime(d.year, d.month, d.day, 12, 0), 2000, "override"
        )
    upsert_daily_activity(
        conn, target, steps=8000, distance_km=5.0,
        logged_activities_kcal=250, marginal_kcal=300,
    )
    upsert_daily_weight(conn, target, 71.2)
    mocker.patch("diet.cli_helpers.run_sync_async", return_value=None)
    mocker.patch("click.prompt", return_value="")  # skip
    mocker.patch("click.confirm", return_value=False)
    capture = []
    mocker.patch(
        "click.echo",
        side_effect=lambda *a, **k: capture.append(" ".join(str(x) for x in a)),
    )
    from diet.orchestrator import run_daily_flow
    run_daily_flow(data_dir=tmp_path, target_date=target)
    out = "\n".join(capture)
    assert "推定" in out and "2,000" in out
    assert "N=14" in out


def test_orchestrator_offline_sync_failure_tolerated(setup_db, monkeypatch, mocker):
    """Fitbit sync が例外でも食事入力には進む"""
    tmp_path, conn = setup_db
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FITBIT_CLIENT_ID", "CID")
    monkeypatch.setenv("FITBIT_CLIENT_SECRET", "CSEC")
    target = date(2026, 5, 25)
    upsert_daily_weight(conn, target, 71.2)
    mocker.patch(
        "diet.cli_helpers.run_sync_async",
        side_effect=Exception("network down"),
    )
    mocker.patch("click.prompt", return_value="=2300")
    mocker.patch("click.confirm", return_value=False)
    from diet.orchestrator import run_daily_flow
    run_daily_flow(data_dir=tmp_path, target_date=target)
    events = get_events_for_date(conn, target)
    assert len(events) == 1
    assert events[0].kcal == 2300


def test_run_show_only_no_publish(setup_db, monkeypatch, mocker):
    """show is display-only: no intake prompt, no publish"""
    tmp_path, conn = setup_db
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    target = date(2026, 5, 25)
    upsert_daily_activity(conn, target, 8000, 5.0, 250, 300)
    upsert_daily_weight(conn, target, 71.2)
    insert_intake_event(
        conn, target, datetime(2026, 5, 25, 12, 0), 2000, "override"
    )
    prompt_spy = mocker.patch("click.prompt")
    publish_spy = mocker.patch("diet.publish.publish_to_hpasaneel")
    from diet.orchestrator import run_show_only
    run_show_only(tmp_path, target)
    prompt_spy.assert_not_called()
    publish_spy.assert_not_called()
