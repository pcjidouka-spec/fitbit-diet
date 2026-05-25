from datetime import date

def age_at(birthday: date, target_date: date) -> int:
    age = target_date.year - birthday.year
    if (target_date.month, target_date.day) < (birthday.month, birthday.day):
        age -= 1
    return age


def mifflin_st_jeor(weight_kg: float, height_cm: int, age: int, sex: str) -> float:
    if sex == "male":
        offset = 5
    elif sex == "female":
        offset = -161
    else:
        raise ValueError(f"sex must be 'male' or 'female', got {sex!r}")
    return 10 * weight_kg + 6.25 * height_cm - 5 * age + offset
