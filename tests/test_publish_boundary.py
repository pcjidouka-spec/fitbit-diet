from datetime import date

from diet.publish import PublicDayRecord


def test_public_day_record_to_public_dict_has_only_allowed_fields():
    """DTO must expose ONLY the 5 allowlisted fields when serialised."""
    rec = PublicDayRecord(
        date=date(2026, 5, 25),
        steps=8234,
        distance_km=5.3,
        exercise_kcal=280,
        weight_kg=71.2,
    )
    d = rec.to_public_dict()
    assert set(d.keys()) == {"date", "steps", "distance_km", "exercise_kcal", "weight_kg"}
    assert d["date"] == "2026-05-25"
    assert d["steps"] == 8234
    assert d["distance_km"] == 5.3
    assert d["exercise_kcal"] == 280
    assert d["weight_kg"] == 71.2


def test_public_day_record_is_frozen():
    """Frozen dataclass prevents accidental mutation in the publish pipeline."""
    import dataclasses
    rec = PublicDayRecord(
        date=date(2026, 5, 25),
        steps=1,
        distance_km=1.0,
        exercise_kcal=1,
        weight_kg=70.0,
    )
    with __import__("pytest").raises(dataclasses.FrozenInstanceError):
        rec.steps = 999  # type: ignore[misc]
