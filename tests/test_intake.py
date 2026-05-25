from datetime import date, datetime, timedelta
from diet.intake import (
    IntakeEvent, recorded_sum, is_complete_day,
    DailyEvents, past_avg, SAMPLE_FLOOR,
)


def E(kcal, op, ts="2026-05-25T12:00:00", id=0):
    return IntakeEvent(id=id, timestamp=datetime.fromisoformat(ts), kcal=kcal, op=op)


def test_recorded_sum_empty():
    assert recorded_sum([]) is None


def test_recorded_sum_append_only():
    assert recorded_sum([E(500, "append"), E(300, "append")]) == 800


def test_recorded_sum_override_only():
    assert recorded_sum([E(2000, "override")]) == 2000


def test_recorded_sum_override_then_append():
    events = [
        E(500, "append"),
        E(2000, "override", ts="2026-05-25T13:00:00"),
        E(200, "append", ts="2026-05-25T14:00:00"),
    ]
    assert recorded_sum(events) == 2200


def test_recorded_sum_multiple_overrides_last_wins():
    events = [
        E(2000, "override", ts="2026-05-25T12:00:00"),
        E(1500, "override", ts="2026-05-25T13:00:00"),
    ]
    assert recorded_sum(events) == 1500


def test_recorded_sum_zero_fasting():
    assert recorded_sum([E(0, "override")]) == 0


def test_recorded_sum_same_ts_id_asc_tiebreak():
    ts = "2026-05-25T12:00:00"
    events = [E(2000, "override", ts=ts, id=2), E(1500, "override", ts=ts, id=1)]
    # id 1 -> 2 の順 → 後の id=2 (2000) が勝つ
    assert recorded_sum(events) == 2000


def test_complete_with_override():
    assert is_complete_day([E(2000, "override")]) is True


def test_complete_append_only_false():
    assert is_complete_day([E(500, "append")]) is False


def test_complete_empty_false():
    assert is_complete_day([]) is False


def test_complete_mixed_with_override_true():
    assert is_complete_day([E(500, "append"), E(2000, "override")]) is True


def D(events):
    return DailyEvents(events=events)


def Ed(kcal, op, day):
    return IntakeEvent(id=0, timestamp=datetime(day.year, day.month, day.day, 12, 0), kcal=kcal, op=op)


def test_sample_floor_is_three():
    assert SAMPLE_FLOOR == 3


def test_past_avg_empty_history():
    assert past_avg({}, target_date=date(2026, 5, 25)) == (None, 0)


def test_past_avg_below_floor_returns_none():
    history = {
        date(2026, 5, 24): D([Ed(2000, "override", date(2026, 5, 24))]),
        date(2026, 5, 23): D([Ed(1800, "override", date(2026, 5, 23))]),
    }
    avg, n = past_avg(history, target_date=date(2026, 5, 25))
    assert avg is None
    assert n == 2


def test_past_avg_at_floor():
    history = {
        date(2026, 5, 24): D([Ed(2000, "override", date(2026, 5, 24))]),
        date(2026, 5, 23): D([Ed(1800, "override", date(2026, 5, 23))]),
        date(2026, 5, 22): D([Ed(2200, "override", date(2026, 5, 22))]),
    }
    avg, n = past_avg(history, target_date=date(2026, 5, 25))
    assert avg == 2000.0
    assert n == 3


def test_past_avg_excludes_partial_days():
    history = {
        date(2026, 5, 24): D([Ed(2000, "override", date(2026, 5, 24))]),
        date(2026, 5, 23): D([Ed(1800, "override", date(2026, 5, 23))]),
        date(2026, 5, 22): D([Ed(2200, "override", date(2026, 5, 22))]),
        date(2026, 5, 21): D([Ed(500, "append", date(2026, 5, 21))]),
        date(2026, 5, 20): D([Ed(300, "append", date(2026, 5, 20))]),
    }
    avg, n = past_avg(history, target_date=date(2026, 5, 25))
    assert avg == 2000.0
    assert n == 3


def test_past_avg_half_open_excludes_target_date():
    history = {
        date(2026, 5, 25): D([Ed(9999, "override", date(2026, 5, 25))]),
        date(2026, 5, 24): D([Ed(2000, "override", date(2026, 5, 24))]),
        date(2026, 5, 23): D([Ed(1800, "override", date(2026, 5, 23))]),
        date(2026, 5, 22): D([Ed(2200, "override", date(2026, 5, 22))]),
    }
    avg, n = past_avg(history, target_date=date(2026, 5, 25))
    assert n == 3


def test_past_avg_includes_target_minus_14():
    target = date(2026, 5, 25)
    history = {
        target - timedelta(days=14): D([Ed(2000, "override", target - timedelta(days=14))]),
        target - timedelta(days=13): D([Ed(1800, "override", target - timedelta(days=13))]),
        target - timedelta(days=12): D([Ed(2200, "override", target - timedelta(days=12))]),
    }
    avg, n = past_avg(history, target_date=target)
    assert n == 3
    assert avg == 2000.0


def test_past_avg_excludes_target_minus_15():
    target = date(2026, 5, 25)
    history = {
        target - timedelta(days=15): D([Ed(9999, "override", target - timedelta(days=15))]),
        target - timedelta(days=14): D([Ed(2000, "override", target - timedelta(days=14))]),
        target - timedelta(days=13): D([Ed(1800, "override", target - timedelta(days=13))]),
        target - timedelta(days=12): D([Ed(2200, "override", target - timedelta(days=12))]),
    }
    avg, n = past_avg(history, target_date=target)
    assert n == 3
    assert avg == 2000.0
