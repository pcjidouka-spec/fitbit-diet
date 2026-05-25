"""Cross-cutting small helpers.

Keep this module dependency-light: no DB / network / click. Anything heavier
belongs in cli_helpers.py.
"""


def resolve_exercise_kcal(activity, source: str | None) -> int:
    """Pick exercise_kcal from a DailyActivityRow per the configured source.

    ``source`` is ``"logged_activities"`` to use ``logged_activities_kcal``,
    anything else (``"marginal"`` / ``None`` / ``"decide_later"``) falls back to
    ``marginal_kcal``. Mirrors ``publish.build_records_from_db``'s default so
    today's on-screen exercise number matches what will be published.
    """
    if activity is None:
        return 0
    if source == "logged_activities":
        return activity.logged_activities_kcal or 0
    return activity.marginal_kcal or 0
