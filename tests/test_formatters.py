import pytest

from diet.formatters import format_balance, format_intake_display
from diet.intake import IntakeDecision


def test_format_recorded_authoritative():
    d = IntakeDecision(intake_kcal=1800, label="recorded_authoritative", n_samples=10)
    s = format_intake_display(d)
    assert "1,800" in s
    assert "記録" in s


def test_format_recorded_partial_high():
    d = IntakeDecision(intake_kcal=2400, label="recorded_partial_high", n_samples=11)
    s = format_intake_display(d)
    assert "2,400" in s
    assert "部分入力" in s


def test_format_estimated_avg_supplement():
    d = IntakeDecision(
        intake_kcal=2100,
        label="estimated_avg_supplement",
        recorded_part=500,
        supplement_part=1600,
        n_samples=11,
    )
    s = format_intake_display(d)
    assert "推定" in s
    assert "2,100" in s
    assert "500" in s
    assert "1,600" in s
    assert "N=11" in s


def test_format_estimated_baseline_supplement():
    d = IntakeDecision(
        intake_kcal=2000,
        label="estimated_baseline_supplement",
        recorded_part=500,
        supplement_part=1500,
        n_samples=2,
    )
    s = format_intake_display(d)
    assert "2,000" in s
    assert "baseline" in s.lower()


def test_format_recorded_no_baseline():
    d = IntakeDecision(intake_kcal=500, label="recorded_no_baseline", n_samples=0)
    s = format_intake_display(d)
    assert "500" in s
    assert "cold" in s.lower() or "未設定" in s


def test_format_estimated_avg():
    d = IntakeDecision(intake_kcal=1980, label="estimated_avg", n_samples=8)
    s = format_intake_display(d)
    assert "1,980" in s
    assert "推定" in s
    assert "N=8" in s


def test_format_estimated_baseline():
    d = IntakeDecision(intake_kcal=2000, label="estimated_baseline", n_samples=2)
    s = format_intake_display(d)
    assert "2,000" in s
    assert "baseline" in s.lower() or "推定" in s


def test_format_unconfirmed():
    d = IntakeDecision(intake_kcal=None, label="unconfirmed", n_samples=0)
    s = format_intake_display(d)
    assert "未確定" in s


def test_format_unknown_label_raises():
    d = IntakeDecision(intake_kcal=100, label="nonsense", n_samples=0)
    with pytest.raises(ValueError):
        format_intake_display(d)


def test_format_balance_red():
    s = format_balance(
        intake_kcal=2300,
        bmr=1543.0,
        exercise_kcal=280,
        steps=8234,
        distance_km=5.3,
        weight_kg=71.2,
    )
    assert "2,300" in s
    assert "1,543" in s
    assert "280" in s
    # burn = 1543 + 280 = 1823; balance = 1823 - 2300 = -477 (赤字)
    assert "-477" in s
    assert "赤字" in s


def test_format_balance_black():
    s = format_balance(
        intake_kcal=1500,
        bmr=1543.0,
        exercise_kcal=280,
        steps=8234,
        distance_km=5.3,
        weight_kg=71.2,
    )
    # burn = 1823, balance = 1823 - 1500 = +323 (黒字)
    assert "+323" in s
    assert "黒字" in s


def test_format_balance_intake_none():
    s = format_balance(
        intake_kcal=None,
        bmr=1543.0,
        exercise_kcal=280,
        steps=8234,
        distance_km=5.3,
        weight_kg=71.2,
    )
    assert "未確定" in s or "算出不可" in s
