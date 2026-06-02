"""FastAPI non-dependent pure Python service layer.

Composes existing modules (db / bmr / intake / formatters / helpers) to
build a current-day state DTO. No HTTP knowledge here (exceptions are
plain ValueError etc.).
"""
from datetime import date as _date, timedelta

from diet.bmr import age_at, mifflin_st_jeor
from diet.db import (
    Config,
    get_daily_activity,
    get_events_for_date,
    get_events_in_range,
    get_latest_weight_on_or_before,
)
from diet.formatters import format_balance, format_intake_display
from diet.helpers import resolve_exercise_kcal
from diet.intake import decide_intake_kcal, past_avg, recorded_sum


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
