from datetime import date

import pytest

from diet.publish import PublicDayRecord, build_log_json, validate_log_json


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


# --- Task 5.3: 2-stage validate (raw load + final write) -----------------


def test_raw_load_rejects_poisoned_existing_doc():
    """Stage 1 — existing log.json that already contains a forbidden field
    (e.g. ``note``) must raise before any merge happens. Silent drop is
    forbidden because it would let the leak survive a round-trip."""
    poisoned = {
        "updated_at": "2026-05-25T22:00:00+09:00",
        "days": [
            {
                "date": "2026-05-24",
                "steps": 1,
                "distance_km": 1.0,
                "exercise_kcal": 1,
                "weight_kg": 1.0,
                "note": "X",
            }
        ],
    }
    with pytest.raises(Exception):
        build_log_json([], existing_doc=poisoned)


def test_final_write_rejects_poisoned_final_dict(mocker):
    """Stage 2 — even if the internal assembler is compromised and emits a
    final dict with a forbidden field, ``build_log_json`` must catch it.

    We spy on the internal seam ``_assemble_final_dict`` and inject a poisoned
    ``note`` into the final dict. The second validate call must reject."""
    import diet.publish as pub

    rec = PublicDayRecord(
        date=date(2026, 5, 25),
        steps=1,
        distance_km=1.0,
        exercise_kcal=1,
        weight_kg=1.0,
    )
    real_assemble = pub._assemble_final_dict

    def poisoning(records, existing_doc):
        d = real_assemble(records, existing_doc)
        d["days"][0]["note"] = "LEAK"
        return d

    mocker.patch.object(pub, "_assemble_final_dict", side_effect=poisoning)
    with pytest.raises(Exception):
        build_log_json([rec], existing_doc=None)


def test_validate_called_twice_when_existing(mocker):
    """Both stages run when existing_doc is provided (raw + final)."""
    import diet.publish as pub

    valid_existing = {"updated_at": "2026-05-25T22:00:00+09:00", "days": []}
    rec = PublicDayRecord(
        date=date(2026, 5, 25),
        steps=1,
        distance_km=1.0,
        exercise_kcal=1,
        weight_kg=1.0,
    )
    spy = mocker.spy(pub, "validate_log_json")
    build_log_json([rec], existing_doc=valid_existing)
    assert spy.call_count == 2  # raw load + final


def test_validate_called_once_when_no_existing(mocker):
    """Only the final stage runs when there's no pre-existing doc."""
    import diet.publish as pub

    rec = PublicDayRecord(
        date=date(2026, 5, 25),
        steps=1,
        distance_km=1.0,
        exercise_kcal=1,
        weight_kg=1.0,
    )
    spy = mocker.spy(pub, "validate_log_json")
    build_log_json([rec], existing_doc=None)
    assert spy.call_count == 1  # final only
