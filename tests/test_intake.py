from datetime import datetime
from diet.intake import IntakeEvent, recorded_sum


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
