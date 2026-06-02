"""FastAPI non-dependent pure Python service layer.

Composes existing modules (db / bmr / intake / formatters / helpers) to
build a current-day state DTO. No HTTP knowledge here (exceptions are
plain ValueError etc.).
"""
import asyncio
import math
from datetime import date as _date, datetime, timedelta

from diet.bmr import age_at, mifflin_st_jeor
from diet.db import (
    Config,
    get_daily_activity,
    get_events_for_date,
    get_events_in_range,
    get_latest_weight_on_or_before,
    insert_intake_event,
    load_token,
    upsert_daily_weight,
)
from diet.formatters import format_balance, format_intake_display
from diet.helpers import resolve_exercise_kcal
from diet.intake import decide_intake_kcal, parse_kcal, past_avg, recorded_sum


def get_day_dto(conn, cfg: Config, target: _date) -> dict:
    """Current-day state DTO. Returns activity, weight, BMR, intake and balance in one dict.

    NOTE: This response is returned ONLY to the localhost browser (food kcal/balance included).
    NEVER pass to publish paths (use build_records_from_db for that).
    """
    activity = get_daily_activity(conn, target)
    weight = get_latest_weight_on_or_before(conn, target)

    bmr = None
    weight_dto = None
    if weight is not None:
        days_ago = (target - weight.date).days
        weight_dto = {
            "weight_kg": weight.weight_kg,
            "measured_date": weight.date.isoformat(),
            "days_ago": days_ago,
        }
        age = age_at(cfg.birthday, target)
        bmr = mifflin_st_jeor(weight.weight_kg, cfg.height_cm, age, cfg.sex)

    history = get_events_in_range(conn, target - timedelta(days=14), target)
    avg, n = past_avg(history, target)
    today_events = get_events_for_date(conn, target)
    decision = decide_intake_kcal(today_events, avg, n, cfg.bootstrap_daily_kcal)
    exercise = resolve_exercise_kcal(activity)

    balance = None
    if bmr is not None and weight is not None and activity is not None:
        balance = format_balance(
            decision.intake_kcal, bmr, exercise,
            activity.steps, activity.distance_km, weight.weight_kg,
        )

    return {
        "date": target.isoformat(),
        "steps": activity.steps if activity else None,
        "distance_km": activity.distance_km if activity else None,
        "exercise_kcal": exercise if activity else None,
        "weight": weight_dto,
        "bmr": int(bmr) if bmr is not None else None,
        "intake": {
            "recorded_sum": recorded_sum(today_events),
            "decision_kcal": decision.intake_kcal,
            "label": decision.label,
            "display": format_intake_display(decision),
        },
        "balance": balance,
    }


def apply_intake(conn, target: _date, raw: str) -> None:
    """Save one meal-intake entry. Raises ValueError on bad input (caller translates to 400)."""
    parsed = parse_kcal(raw)  # ValueError on bad input
    if parsed is None:
        return
    insert_intake_event(conn, target, datetime.now(), parsed.kcal, parsed.op)


def record_weight(conn, target: _date, kg: float) -> None:
    """Save manual body-weight entry. Raises ValueError for non-positive or
    non-finite values (NaN/inf would otherwise persist and break JSON/publish)."""
    if not math.isfinite(kg) or kg <= 0:
        raise ValueError("weight must be a positive finite number")
    upsert_daily_weight(conn, target, kg)


def get_history_dto(conn, cfg: Config, target: _date, days: int) -> list[dict]:
    """Return graph-ready history (steps / exercise / weight) for the past `days` days.

    Intentionally excludes meal kcal — non-secret fields only.
    """
    rows = []
    for offset in range(days - 1, -1, -1):
        d = target - timedelta(days=offset)
        a = get_daily_activity(conn, d)
        w = get_latest_weight_on_or_before(conn, d)
        rows.append({
            "date": d.isoformat(),
            "steps": a.steps if a else None,
            "exercise_kcal": resolve_exercise_kcal(a) if a else None,
            "weight_kg": w.weight_kg if w else None,
        })
    return rows


def auth_status(conn) -> dict:
    """Return OAuth token presence (auth itself remains CLI-side in v1)."""
    return {"authenticated": load_token(conn) is not None}


def run_sync(conn, days: int) -> None:
    """Pass-through to run_sync_async.

    asyncio.run() is safe here because FastAPI sync-def routes execute in a
    worker thread with no running event loop.
    """
    from diet.cli_helpers import run_sync_async
    asyncio.run(run_sync_async(conn, days=days))


def run_publish(conn, cfg: Config, target: _date) -> None:
    """Publish to HPasaneel. Privacy boundary is enforced by build_records_from_db (5-field allowlist).

    Web-path guards (vs the CLI flow):
      - empty record set → ValueError instead of a no-op git commit (the CLI
        skips explicitly when activity/weight are missing).
      - preflight for uncommitted manual edits to log.json → ValueError, because
        publish_to_hpasaneel would otherwise call click.confirm and block on a
        non-existent stdin in a browser-initiated request.
    """
    import subprocess
    from pathlib import Path
    from diet.publish import build_records_from_db, publish_to_hpasaneel

    if cfg.hpasaneel_path is None:
        raise ValueError("hpasaneel_path not configured")
    records = build_records_from_db(conn, [target])
    if not records:
        raise ValueError(
            f"no publishable data for {target.isoformat()} "
            "(activity or weight missing)"
        )
    repo = Path(cfg.hpasaneel_path)
    rel_log = f"{cfg.hpasaneel_diet_root}/log.json"
    status = subprocess.run(
        ["git", "status", "--porcelain", rel_log],
        cwd=repo, capture_output=True, text=True, check=True,
    )
    if status.stdout.strip():
        raise ValueError(
            f"{rel_log} に未コミットの手動変更があります。"
            "CLI（diet）で解決してから再実行してください。"
        )
    publish_to_hpasaneel(
        repo, cfg.hpasaneel_diet_root, records, do_push=True,
    )
