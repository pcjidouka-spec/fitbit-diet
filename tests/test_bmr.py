from datetime import date
from diet.bmr import age_at

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

import pytest
from diet.bmr import mifflin_st_jeor

def test_bmr_male_70kg_46y_169cm():
    # 700 + 1056.25 - 230 + 5 = 1531.25
    assert mifflin_st_jeor(weight_kg=70.0, height_cm=169, age=46, sex="male") == 1531.25

def test_bmr_height_169_constant_unfolded():
    """Regression: 6.25 * 169 = 1056.25 (NOT 836.25 — earlier spec typo)."""
    assert mifflin_st_jeor(weight_kg=0.0, height_cm=169, age=0, sex="male") == 1061.25

def test_bmr_female_offset():
    male = mifflin_st_jeor(weight_kg=70.0, height_cm=169, age=46, sex="male")
    female = mifflin_st_jeor(weight_kg=70.0, height_cm=169, age=46, sex="female")
    assert female == male - 5 + (-161)

def test_bmr_invalid_sex_raises():
    with pytest.raises(ValueError):
        mifflin_st_jeor(weight_kg=70.0, height_cm=169, age=46, sex="other")
