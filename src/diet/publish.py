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
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import click
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


def build_records_from_db(
    conn, target_dates: list[date], exercise_calorie_source: str
) -> list[PublicDayRecord]:
    """Read publishable records from the DB.

    ★ Privacy boundary: this function MUST only SELECT from ``daily_activity``
    and ``daily_weight``. It must never touch ``intake_events`` (which carries
    meal ``note`` strings), ``config``, or ``fitbit_token``. The boundary
    tests in ``tests/test_publish_boundary.py`` capture executed SQL via
    ``set_trace_callback`` and assert those forbidden tables are never named.
    """
    # Local import keeps the SELECT helpers narrow: only daily_activity +
    # daily_weight accessors. Do NOT add `get_events_*` here.
    from diet.db import get_daily_activity, get_latest_weight_on_or_before

    records: list[PublicDayRecord] = []
    for d in target_dates:
        a = get_daily_activity(conn, d)
        w = get_latest_weight_on_or_before(conn, d)
        if a is None or w is None:
            continue
        if exercise_calorie_source == "logged_activities":
            ex = a.logged_activities_kcal or 0
        else:
            # default to marginal (also covers the explicit "marginal" value
            # and the spec's "decide_later" fallback)
            ex = a.marginal_kcal or 0
        records.append(
            PublicDayRecord(
                date=d,
                steps=a.steps,
                distance_km=a.distance_km,
                exercise_kcal=ex,
                weight_kg=w.weight_kg,
            )
        )
    return records


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


def publish_to_hpasaneel(
    repo_path: Path,
    diet_root: str,
    records: list[PublicDayRecord],
    do_push: bool,
) -> None:
    """Write log.json into the HPasaneel repo and commit (optionally push).

    Sequence (spec §7 git 連携):
      1. (do_push only) ``git pull --rebase`` to take remote changes
      2. read existing log.json from disk (post-pull view)
      3. build new log.json (with 2-stage schema validate)
      4. write log.json atomically
      5. ``git add`` log.json ONLY — never `git add .`
      6. ``git commit -m "diet: <dates> update"``
      7. (do_push only) ``git push``
    """
    log_path = repo_path / diet_root / "log.json"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Before any git or file ops: detect manual edits to log.json that the
    # user never staged. If we silently overwrite them, weeks of hand-edits
    # disappear. Spec §7 "log.json に手動変更が無いか確認".
    rel_log = str(log_path.relative_to(repo_path)).replace("\\", "/")
    status = subprocess.run(
        ["git", "status", "--porcelain", rel_log],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    if status.stdout.strip():
        # Prompt via click.confirm so tests can patch it. Test patches the
        # symbol on the `click` module, so we resolve it lazily here.
        proceed = click.confirm(
            f"{rel_log} has uncommitted manual changes. Overwrite?",
            default=False,
        )
        if not proceed:
            click.echo("publish aborted by user.")
            sys.exit(1)
        # User confirmed overwrite. Discard the dirty working-tree version by
        # restoring the committed copy (or removing the file if it is only
        # untracked / staged-but-new) — otherwise the subsequent `json.loads`
        # below would consume the dirty content and either crash or silently
        # re-publish it.
        #
        # Porcelain status codes (first 2 chars, XY = index/worktree):
        #   "??"     untracked            → unlink only
        #   "A " / "AM" / "AD"  staged-add, never committed → unlink + git rm --cached
        #                                  (HEAD has no version to restore from)
        #   " M" / "M " / "MM"  modified tracked file → checkout HEAD restores
        first_line = status.stdout.splitlines()[0] if status.stdout else ""
        if first_line.startswith("??"):
            # Untracked dirty file: nothing in HEAD to restore. Just remove it
            # so the existing-doc load below sees no prior content.
            log_path.unlink()
        elif first_line[:1] == "A":
            # Staged but never committed (failed first-publish residue). HEAD
            # has no prior version, so `git checkout HEAD --` would fail.
            # Unstage and remove so the load sees no prior content.
            #
            # `-f` is required for AM / AD where the worktree no longer matches
            # the staged blob — without it `git rm --cached` refuses to avoid
            # losing staged content. Here the user already confirmed overwrite,
            # so dropping the staged blob is the intended behaviour.
            subprocess.run(
                ["git", "rm", "-f", "--cached", "--", rel_log],
                cwd=repo_path,
                check=True,
            )
            if log_path.exists():
                log_path.unlink()
        else:
            subprocess.run(
                ["git", "checkout", "HEAD", "--", rel_log],
                cwd=repo_path,
                check=True,
            )

    if do_push:
        subprocess.run(["git", "pull", "--rebase"], cwd=repo_path, check=True)

    existing: dict | None = None
    if log_path.exists():
        existing = json.loads(log_path.read_text(encoding="utf-8"))

    final = build_log_json(records, existing)
    log_path.write_text(
        json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Stage log.json ONLY (relative path, forward slashes for git on Windows).
    rel = str(log_path.relative_to(repo_path)).replace("\\", "/")
    subprocess.run(["git", "add", rel], cwd=repo_path, check=True)
    dates = ", ".join(r.date.isoformat() for r in records)
    rev = _next_rev(repo_path, [r.date.isoformat() for r in records])
    suffix = "" if rev == 1 else f" (rev {rev})"
    subprocess.run(
        ["git", "commit", "-m", f"diet: {dates} update{suffix}"],
        cwd=repo_path,
        check=True,
    )
    if do_push:
        subprocess.run(["git", "push"], cwd=repo_path, check=True)


def _next_rev(repo_path: Path, date_labels: list[str]) -> int:
    """Return N+1 where N = max past-publish count across the given dates.

    Counted *per date* and then reduced via ``max`` so:
      - a single-date republish that follows a multi-date commit still gets
        ``(rev 2)`` (the date itself was published once),
      - a multi-date publish whose dates each have separate prior histories
        does NOT compound (publishing ``[25, 26]`` after two separate
        single-date publishes is still ``(rev 2)`` for each, so the shared
        suffix is ``(rev 2)`` — not ``(rev 3)``).

    Failures (brand-new repo with no commits, missing git, etc.) fall back
    to rev 1 so first publishes never carry a bogus suffix.
    """
    counts: list[int] = []
    for d in date_labels:
        result = subprocess.run(
            ["git", "log", "--all", "--oneline", "--grep", d],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return 1
        # Each line is one prior publish that mentioned this date in its
        # commit message; --grep matches any substring so ``diet: 2026-05-25
        # update`` and ``diet: 2026-05-25, 2026-05-26 update`` both count.
        counts.append(
            sum(1 for _ in result.stdout.strip().splitlines() if _.strip())
        )
    if not counts:
        return 1
    return max(counts) + 1


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
