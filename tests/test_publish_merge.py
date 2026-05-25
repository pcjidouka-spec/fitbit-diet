from datetime import date

from diet.publish import PublicDayRecord, build_log_json


def D(dstr: str, steps: int = 1) -> dict:
    return {
        "date": dstr,
        "steps": steps,
        "distance_km": 1.0,
        "exercise_kcal": 1,
        "weight_kg": 70.0,
    }


def test_merge_preserves_other_dates():
    """Adding a new date entry must NOT delete other existing entries.

    Critical for `git pull --rebase` flow: another machine may have published
    a different date in between, and publish must not silently overwrite it."""
    existing = {
        "updated_at": "2026-05-25T22:00:00+09:00",
        "days": [D("2026-05-24", steps=100), D("2026-05-23", steps=200)],
    }
    new = PublicDayRecord(
        date=date(2026, 5, 25),
        steps=999,
        distance_km=1.0,
        exercise_kcal=1,
        weight_kg=70.0,
    )
    out = build_log_json([new], existing)
    dates = [d["date"] for d in out["days"]]
    assert "2026-05-25" in dates
    assert "2026-05-24" in dates
    assert "2026-05-23" in dates
    assert len(dates) == 3


def test_merge_replaces_same_date():
    """Re-publishing the same date must replace, not duplicate."""
    existing = {
        "updated_at": "2026-05-25T22:00:00+09:00",
        "days": [D("2026-05-25", steps=100)],
    }
    new = PublicDayRecord(
        date=date(2026, 5, 25),
        steps=999,
        distance_km=1.0,
        exercise_kcal=1,
        weight_kg=70.0,
    )
    out = build_log_json([new], existing)
    assert len(out["days"]) == 1
    assert out["days"][0]["steps"] == 999


def test_merge_sorts_by_date_desc():
    """Output days are sorted newest-first for dashboard display."""
    existing = {
        "updated_at": "2026-05-25T22:00:00+09:00",
        "days": [D("2026-05-23"), D("2026-05-25"), D("2026-05-24")],
    }
    out = build_log_json([], existing)
    dates = [d["date"] for d in out["days"]]
    assert dates == ["2026-05-25", "2026-05-24", "2026-05-23"]
