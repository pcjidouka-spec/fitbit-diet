import pytest

from diet.publish import validate_log_json


def test_minimal_valid():
    validate_log_json({"updated_at": "2026-05-25T22:00:00+09:00", "days": []})


def test_rejects_top_level_extra_key():
    with pytest.raises(Exception):
        validate_log_json(
            {"updated_at": "2026-05-25T22:00:00+09:00", "days": [], "secret": "x"}
        )


def test_rejects_day_extra_key():
    """note 等が混入したら絶対 reject (★ privacy boundary)."""
    with pytest.raises(Exception):
        validate_log_json(
            {
                "updated_at": "2026-05-25T22:00:00+09:00",
                "days": [
                    {
                        "date": "2026-05-25",
                        "steps": 1,
                        "distance_km": 1.0,
                        "exercise_kcal": 1,
                        "weight_kg": 1.0,
                        "note": "ラーメン",
                    }
                ],
            }
        )


def test_rejects_missing_required():
    with pytest.raises(Exception):
        validate_log_json(
            {
                "updated_at": "2026-05-25T22:00:00+09:00",
                "days": [{"date": "2026-05-25", "steps": 1}],
            }
        )


def test_rejects_negative_numbers():
    with pytest.raises(Exception):
        validate_log_json(
            {
                "updated_at": "2026-05-25T22:00:00+09:00",
                "days": [
                    {
                        "date": "2026-05-25",
                        "steps": -1,
                        "distance_km": 1.0,
                        "exercise_kcal": 1,
                        "weight_kg": 1.0,
                    }
                ],
            }
        )


def test_rejects_invalid_date_format():
    with pytest.raises(Exception):
        validate_log_json(
            {
                "updated_at": "2026-05-25T22:00:00+09:00",
                "days": [
                    {
                        "date": "2026/5/25",
                        "steps": 1,
                        "distance_km": 1.0,
                        "exercise_kcal": 1,
                        "weight_kg": 1.0,
                    }
                ],
            }
        )
