from datetime import date

def age_at(birthday: date, target_date: date) -> int:
    age = target_date.year - birthday.year
    if (target_date.month, target_date.day) < (birthday.month, birthday.day):
        age -= 1
    return age
