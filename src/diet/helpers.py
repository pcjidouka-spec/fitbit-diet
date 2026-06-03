"""Cross-cutting small helpers.

Keep this module dependency-light: no DB / network / click. Anything heavier
belongs in cli_helpers.py.
"""


def resolve_exercise_kcal(activity) -> int:
    """Exercise kcal for the day = active-energy-burned (BMR-free).

    Google Health has no marginalCalories; active-energy-burned is the
    documented BMR-free successor. total_calories_kcal is diagnostic-only
    and is intentionally NOT selectable, to prevent BMR double-counting."""
    if activity is None:
        return 0
    return activity.active_energy_kcal or 0
