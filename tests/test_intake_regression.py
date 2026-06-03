from datetime import date, datetime, timedelta
from diet.intake import IntakeEvent, DailyEvents, past_avg, decide_intake_kcal


def Ed(kcal, op, d):
    return IntakeEvent(id=0, timestamp=datetime(d.year, d.month, d.day, 12, 0), kcal=kcal, op=op)


def test_fasting_after_normal_history():
    """過去 14 日 平均 2200 → 今日 =0 → 0 のまま"""
    target = date(2026, 5, 25)
    history = {
        target - timedelta(days=i): DailyEvents(events=[Ed(2200, "override", target - timedelta(days=i))])
        for i in range(1, 15)
    }
    today = [Ed(0, "override", target)]
    avg, n = past_avg(history, target)
    assert avg == 2200.0 and n == 14
    d = decide_intake_kcal(today, avg, n, bootstrap_baseline=2000)
    assert d.intake_kcal == 0


def test_restriction_day_stays_low():
    """=1200 制限日が 2200 平均で水増しされない"""
    target = date(2026, 5, 25)
    history = {
        target - timedelta(days=i): DailyEvents(events=[Ed(2200, "override", target - timedelta(days=i))])
        for i in range(1, 15)
    }
    today = [Ed(1200, "override", target)]
    avg, n = past_avg(history, target)
    d = decide_intake_kcal(today, avg, n, bootstrap_baseline=2000)
    assert d.intake_kcal == 1200
