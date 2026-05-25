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
