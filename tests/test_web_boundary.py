"""Web-layer publish privacy boundary test.

★ LOAD-BEARING privacy test for the web publish path.

Proves that service.run_publish() — the web-initiated publish route — never
issues SQL that names the `intake_events` or `fitbit_token` tables. Those tables
contain secret meal notes and OAuth tokens that must never reach the public log.

Strategy:
  - Insert a real intake_event row with a secret note so the table is populated.
  - Run run_publish() with sqlite3 set_trace_callback to capture every SQL statement.
  - Assert no captured statement mentions `intake_events` or `fitbit_token`.

The test must wire up a real, clean git repo for the hpasaneel_path because
run_publish() runs `git status --porcelain` (check=True) as a preflight; without
it the subprocess raises CalledProcessError before we reach the publish step.

publish_to_hpasaneel is monkeypatched to a no-op to avoid real git push / file
I/O while still exercising the full SQL path.
"""
import subprocess
from datetime import date, datetime
from pathlib import Path

from diet.db import (
    Config,
    insert_intake_event,
    load_config,
    open_db,
    save_config,
    upsert_daily_activity,
    upsert_daily_weight,
)
from diet.web import service


def _git(repo: Path, *args):
    subprocess.run(["git", *args], cwd=repo, check=True,
                   capture_output=True, text=True)


def _make_clean_hpasaneel(repo: Path) -> None:
    """A real, clean git repo with a committed content/diet/log.json so
    run_publish's `git status --porcelain` preflight passes."""
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    log = repo / "content" / "diet" / "log.json"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text('{"updated_at": "2026-01-01T00:00:00+09:00", "days": []}',
                   encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "init")


def test_web_publish_never_touches_intake_events(tmp_path, monkeypatch):
    """Web publish path never SELECTs intake_events or fitbit_token (SQL trace)."""
    hp = tmp_path / "hp"
    _make_clean_hpasaneel(hp)

    conn = open_db(tmp_path / "t.db")
    save_config(conn, Config(
        birthday=date(1979, 12, 1), height_cm=169, sex="male",
        timezone="Asia/Tokyo", hpasaneel_path=str(hp),
        hpasaneel_diet_root="content/diet", exercise_calorie_source=None,
        bootstrap_daily_kcal=2200,
    ))
    d = date(2026, 6, 3)
    upsert_daily_activity(conn, d, steps=8000, distance_km=5.5,
                          total_calories_kcal=2500, active_energy_kcal=300)
    upsert_daily_weight(conn, d, 71.2)
    insert_intake_event(conn, d, datetime(2026, 6, 3, 12, 0), 600, "append",
                        note="secret_ramen_note")

    # publish_to_hpasaneel no-op: avoids real git push while keeping full SQL path.
    monkeypatch.setattr("diet.publish.publish_to_hpasaneel", lambda *a, **k: None)

    captured = []
    conn.set_trace_callback(captured.append)
    service.run_publish(conn, load_config(conn), d)
    conn.set_trace_callback(None)

    # Positive evidence: the boundary code (build_records_from_db) actually ran.
    # Without this, an empty `captured` (e.g. run_publish raised before any SQL)
    # would make the forbidden-table check below pass vacuously — proving nothing.
    assert any("daily_activity" in s for s in captured), \
        f"boundary code did not run as expected; captured SQL: {captured}"
    assert any("daily_weight" in s for s in captured), \
        f"boundary code did not run as expected; captured SQL: {captured}"

    forbidden = [s for s in captured
                 if any(t in s.lower() for t in ("intake_events", "fitbit_token"))]
    assert forbidden == [], f"web publish touched forbidden tables: {forbidden}"
