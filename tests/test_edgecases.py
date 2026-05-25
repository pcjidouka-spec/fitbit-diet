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


# --- Task 9.3: diet not initialized guard ----------------------------------


def test_diet_command_requires_init(tmp_path, monkeypatch):
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    runner = CliRunner()
    result = runner.invoke(app, [])
    assert result.exit_code != 0
    assert "init" in result.output.lower()


# --- Task 9.4: rev N suffix on same-day re-publish -------------------------


def test_same_day_republish_rev_n_suffix(tmp_path):
    repo = tmp_path / "HPasaneel"
    (repo / "content/diet").mkdir(parents=True)
    _init_repo(repo)
    rec = PublicDayRecord(
        date=date(2026, 5, 25), steps=1, distance_km=1.0, exercise_kcal=1, weight_kg=70.0
    )
    publish_to_hpasaneel(repo, "content/diet", [rec], do_push=False)
    rec2 = PublicDayRecord(
        date=date(2026, 5, 25), steps=2, distance_km=2.0, exercise_kcal=2, weight_kg=70.0
    )
    publish_to_hpasaneel(repo, "content/diet", [rec2], do_push=False)
    log = subprocess.run(
        ["git", "log", "--oneline"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    lines = log.stdout.splitlines()
    # 最新 commit (1 行目) が "rev 2" 等を含む
    assert any("rev 2" in l for l in lines[:2]) or any("(rev" in l for l in lines[:2])


def test_first_publish_has_no_rev_suffix(tmp_path):
    """First publish for a given date label must not carry any ``(rev N)``."""
    repo = tmp_path / "HPasaneel"
    (repo / "content/diet").mkdir(parents=True)
    _init_repo(repo)
    rec = PublicDayRecord(
        date=date(2026, 5, 25), steps=1, distance_km=1.0, exercise_kcal=1, weight_kg=70.0
    )
    publish_to_hpasaneel(repo, "content/diet", [rec], do_push=False)
    log = subprocess.run(
        ["git", "log", "--oneline", "-1"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "rev" not in log.stdout


def test_republish_after_multi_date_commit_still_bumps_rev(tmp_path):
    """Codex P2 regression: a single-date republish that follows a multi-date
    commit must still get a ``(rev 2)`` suffix because the same date was
    already published once — even though the labels differ exactly."""
    repo = tmp_path / "HPasaneel"
    (repo / "content/diet").mkdir(parents=True)
    _init_repo(repo)
    rec_a = PublicDayRecord(
        date=date(2026, 5, 25), steps=1, distance_km=1.0, exercise_kcal=1, weight_kg=70.0
    )
    rec_b = PublicDayRecord(
        date=date(2026, 5, 26), steps=2, distance_km=2.0, exercise_kcal=2, weight_kg=70.0
    )
    publish_to_hpasaneel(repo, "content/diet", [rec_a, rec_b], do_push=False)
    # Now republish just 2026-05-25 → should be detected as a 2nd publish
    rec_a2 = PublicDayRecord(
        date=date(2026, 5, 25), steps=9, distance_km=9.0, exercise_kcal=9, weight_kg=70.0
    )
    publish_to_hpasaneel(repo, "content/diet", [rec_a2], do_push=False)
    log = subprocess.run(
        ["git", "log", "--oneline", "-1"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "rev 2" in log.stdout


def test_multi_date_republish_does_not_inflate_rev(tmp_path):
    """Codex follow-up P2: publishing ``[A, B]`` after separate single-date
    publishes of ``A`` and ``B`` must produce ``(rev 2)`` — not ``(rev 3)``.
    Each date has only been touched once before, so the per-date max is 1,
    and the next publish is rev 2 regardless of the union total."""
    repo = tmp_path / "HPasaneel"
    (repo / "content/diet").mkdir(parents=True)
    _init_repo(repo)
    rec_a = PublicDayRecord(
        date=date(2026, 5, 25), steps=1, distance_km=1.0, exercise_kcal=1, weight_kg=70.0
    )
    rec_b = PublicDayRecord(
        date=date(2026, 5, 26), steps=2, distance_km=2.0, exercise_kcal=2, weight_kg=70.0
    )
    publish_to_hpasaneel(repo, "content/diet", [rec_a], do_push=False)
    publish_to_hpasaneel(repo, "content/diet", [rec_b], do_push=False)
    # Now publish both together with new values → should be rev 2
    # (each date's prior count is 1, so the suffix is max + 1 = 2)
    rec_a2 = PublicDayRecord(
        date=date(2026, 5, 25), steps=11, distance_km=1.1, exercise_kcal=11, weight_kg=70.1
    )
    rec_b2 = PublicDayRecord(
        date=date(2026, 5, 26), steps=22, distance_km=2.2, exercise_kcal=22, weight_kg=70.2
    )
    publish_to_hpasaneel(repo, "content/diet", [rec_a2, rec_b2], do_push=False)
    log = subprocess.run(
        ["git", "log", "--oneline", "-1"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "rev 2" in log.stdout
    assert "rev 3" not in log.stdout


def test_unrelated_commit_with_iso_date_does_not_inflate_rev(tmp_path):
    """Codex follow-up: a non-publish commit that happens to contain the date
    in its message (e.g. release notes) must not be counted toward rev N."""
    repo = tmp_path / "HPasaneel"
    (repo / "content/diet").mkdir(parents=True)
    _init_repo(repo)
    # Unrelated commit whose message mentions the same ISO date.
    (repo / "NOTES.md").write_text("release on 2026-05-25\n")
    subprocess.run(["git", "add", "NOTES.md"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "docs: release notes 2026-05-25"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    rec = PublicDayRecord(
        date=date(2026, 5, 25), steps=1, distance_km=1.0, exercise_kcal=1, weight_kg=70.0
    )
    publish_to_hpasaneel(repo, "content/diet", [rec], do_push=False)
    log = subprocess.run(
        ["git", "log", "--oneline", "-1"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    # The diet publish was the first one — must not carry a rev suffix.
    assert "rev" not in log.stdout
    assert "diet: 2026-05-25 update" in log.stdout


# --- Task 9.5: 429 rate limit reset_seconds -------------------------------


async def test_429_reset_seconds_in_state(httpx_mock):
    """Edge-case re-confirmation of 429 propagation: rate_limit.reset_seconds
    must reflect the ``Fitbit-Rate-Limit-Reset`` header even when the request
    fails. Already exercised by test_fitbit_client_rate_limit; kept here for
    the Phase 9 integration suite."""
    import httpx

    from diet.fitbit_client import FitbitClient

    httpx_mock.add_response(
        url="https://api.fitbit.com/1/user/-/activities/date/2026-05-25.json",
        status_code=429,
        headers={"Fitbit-Rate-Limit-Reset": "600"},
        json={},
    )
    client = FitbitClient(access_token="A")
    with pytest.raises(httpx.HTTPStatusError):
        await client.get_activity_summary("2026-05-25")
    assert client.rate_limit.reset_seconds == 600


# --- Task 9.6: concurrent token refresh safety ----------------------------


def test_concurrent_token_writes_dont_corrupt(tmp_path):
    """並列 2 スレッドで save_token_atomic を 10 回ずつ呼ぶ → 最終状態が壊れない."""
    import threading

    from diet.db import Token, load_token, open_db, save_token_atomic

    db_path = tmp_path / "t.db"
    open_db(db_path).close()
    errors: list[Exception] = []

    def worker(prefix: str) -> None:
        try:
            conn = open_db(db_path)
            for i in range(10):
                save_token_atomic(
                    conn,
                    Token(
                        f"{prefix}{i}",
                        f"R{prefix}{i}",
                        datetime(2030, 1, 1),
                        "U",
                    ),
                )
        except Exception as e:  # noqa: BLE001 — surface to assertion
            errors.append(e)

    t1 = threading.Thread(target=worker, args=("a",))
    t2 = threading.Thread(target=worker, args=("b",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert errors == [], f"concurrent writes corrupted: {errors}"
    conn = open_db(db_path)
    n = conn.execute("SELECT COUNT(*) FROM fitbit_token").fetchone()[0]
    assert n == 1
    tok = load_token(conn)
    assert tok is not None
    assert tok.access_token.startswith(("a", "b"))


# --- Task 9.7: cold start unconfirmed -------------------------------------


def test_cold_start_unconfirmed():
    """No today events, no past avg, no baseline → unconfirmed label / None."""
    from diet.intake import decide_intake_kcal, past_avg

    avg, n = past_avg({}, target_date=date(2026, 5, 25))
    d = decide_intake_kcal([], avg, n, bootstrap_baseline=None)
    assert d.label == "unconfirmed"
    assert d.intake_kcal is None
