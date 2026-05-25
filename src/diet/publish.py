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
from datetime import date, datetime, timezone

import jsonschema


LOG_JSON_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "additionalProperties": False,
    "required": ["updated_at", "days"],
    "properties": {
        "updated_at": {"type": "string", "format": "date-time"},
        "days": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "date",
                    "steps",
                    "distance_km",
                    "exercise_kcal",
                    "weight_kg",
                ],
                "properties": {
                    "date": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
                    "steps": {"type": "integer", "minimum": 0},
                    "distance_km": {"type": "number", "minimum": 0},
                    "exercise_kcal": {"type": "integer", "minimum": 0},
                    "weight_kg": {"type": "number", "minimum": 0},
                },
            },
        },
    },
}


def validate_log_json(doc: dict) -> None:
    """Validate a log.json document against the public schema.

    Raises ``jsonschema.ValidationError`` (a subclass of ``Exception``) on any
    additional / missing / mistyped field. This MUST be called at both the
    raw-load and final-write boundaries (see ``build_log_json``).
    """
    jsonschema.validate(doc, LOG_JSON_SCHEMA)


def _assemble_final_dict(
    records: list[PublicDayRecord], existing_doc: dict | None
) -> dict:
    """Pure function: merge ``records`` into ``existing_doc['days']``, sort
    descending by date, and attach an ``updated_at`` timestamp.

    Exposed as an internal seam so the final-write reject test can poison the
    output and still observe that ``build_log_json`` rejects it at stage 2.
    """
    if existing_doc is not None:
        existing_by_date = {d["date"]: d for d in existing_doc["days"]}
    else:
        existing_by_date = {}
    for r in records:
        existing_by_date[r.date.isoformat()] = r.to_public_dict()
    return {
        "updated_at": datetime.now(timezone.utc)
        .astimezone()
        .isoformat(timespec="seconds"),
        "days": sorted(
            existing_by_date.values(), key=lambda d: d["date"], reverse=True
        ),
    }


def build_log_json(
    records: list[PublicDayRecord], existing_doc: dict | None
) -> dict:
    """Build the final log.json dict from new records + optional existing doc.

    Enforces 2-stage validation:
      1. raw load — reject if existing_doc has any forbidden field
      2. final write — reject if the assembled dict is non-compliant
    """
    if existing_doc is not None:
        validate_log_json(existing_doc)  # stage 1: raw load
    final = _assemble_final_dict(records, existing_doc)
    validate_log_json(final)  # stage 2: final write
    return final


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
