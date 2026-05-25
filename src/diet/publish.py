"""Public publish boundary.

This module is the privacy boundary between the local diet DB (which contains
sensitive `note` strings on intake_events) and the HPasaneel public dashboard.

Two layers of allowlist defence:
1. typed DTO layer — `PublicDayRecord` holds ONLY the 5 publishable fields and
   exposes them via a hand-written `to_public_dict()` (no asdict / __dict__).
2. JSON schema layer — `validate_log_json()` enforces `additionalProperties: false`
   at both the top level and per-day level (see Task 5.2+).

Never import this module from any layer that reads `intake_events`.
"""
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class PublicDayRecord:
    """Allowlist DTO for a single day's publishable record.

    Exactly 5 fields. No `note`, no `intake_kcal`, no anything else.
    """

    date: date
    steps: int
    distance_km: float
    exercise_kcal: int
    weight_kg: float

    def to_public_dict(self) -> dict:
        """Hand-written serializer.

        NEVER use ``dataclasses.asdict()`` / ``__dict__`` / ``row._asdict()`` —
        those would silently propagate any new field added to this dataclass to
        the public log.json. The 5 keys below are the entire public schema.
        """
        return {
            "date": self.date.isoformat(),
            "steps": self.steps,
            "distance_km": self.distance_km,
            "exercise_kcal": self.exercise_kcal,
            "weight_kg": self.weight_kg,
        }
