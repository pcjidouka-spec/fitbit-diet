from datetime import date
import pytest
from diet.bmr import age_at, mifflin_st_jeor

BIRTHDAY = date(1979, 12, 1)

def test_age_at_day_before_birthday():
    assert age_at(BIRTHDAY, date(2026, 11, 30)) == 46

def test_age_at_birthday():
    assert age_at(BIRTHDAY, date(2026, 12, 1)) == 47

def test_age_at_day_after_birthday():
    assert age_at(BIRTHDAY, date(2026, 12, 2)) == 47

def test_age_at_birth_date():
    assert age_at(BIRTHDAY, date(1979, 12, 1)) == 0

def test_age_at_future_year_pre_birthday():
    assert age_at(BIRTHDAY, date(2030, 11, 30)) == 50

def test_age_at_future_year_post_birthday():
    assert age_at(BIRTHDAY, date(2030, 12, 1)) == 51

def test_bmr_male_70kg_46y_169cm():
    # 700 + 1056.25 - 230 + 5 = 1531.25
    assert mifflin_st_jeor(weight_kg=70.0, height_cm=169, age=46, sex="male") == 1531.25

def test_bmr_height_coefficient_is_6_25():
    """Regression: height coefficient must be 6.25, not e.g. 5 (which would have made
    a 71kg/169cm/46y male's BMR 256 kcal lower)."""
    # Isolate the height coefficient: weight=0, age=0, sex=female (offset -161).
    # Expected = 6.25 * 100 + (-161) = 625 - 161 = 464.0
    result = mifflin_st_jeor(weight_kg=0.0, height_cm=100, age=0, sex="female")
    assert result == 464.0

def test_bmr_female_offset():
    male = mifflin_st_jeor(weight_kg=70.0, height_cm=169, age=46, sex="male")
    female = mifflin_st_jeor(weight_kg=70.0, height_cm=169, age=46, sex="female")
    assert female == male - 5 + (-161)

def test_bmr_invalid_sex_raises():
    with pytest.raises(ValueError):
        mifflin_st_jeor(weight_kg=70.0, height_cm=169, age=46, sex="other")
