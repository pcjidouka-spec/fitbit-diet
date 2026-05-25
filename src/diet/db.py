import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from diet.intake import IntakeEvent, DailyEvents

MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS _meta (schema_version INTEGER NOT NULL);

CREATE TABLE IF NOT EXISTS config (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  birthday TEXT NOT NULL,
  height_cm INTEGER NOT NULL,
  sex TEXT NOT NULL,
  timezone TEXT NOT NULL DEFAULT 'Asia/Tokyo',
  hpasaneel_path TEXT,
  hpasaneel_diet_root TEXT DEFAULT 'content/diet',
  exercise_calorie_source TEXT,
  bootstrap_daily_kcal INTEGER
);

CREATE TABLE IF NOT EXISTS intake_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  date TEXT NOT NULL,
  timestamp TEXT NOT NULL,
  kcal INTEGER NOT NULL,
  op TEXT NOT NULL CHECK (op IN ('append', 'override')),
  note TEXT
);
CREATE INDEX IF NOT EXISTS idx_intake_events_date ON intake_events(date);

CREATE TABLE IF NOT EXISTS daily_activity (
  date TEXT PRIMARY KEY,
  steps INTEGER NOT NULL,
  distance_km REAL NOT NULL,
  logged_activities_kcal INTEGER,
  marginal_kcal INTEGER,
  last_synced TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_weight (
  date TEXT PRIMARY KEY,
  weight_kg REAL NOT NULL,
  last_synced TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fitbit_token (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  access_token TEXT NOT NULL,
  refresh_token TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  user_id TEXT NOT NULL,
  rotated_at TEXT NOT NULL
);

INSERT INTO _meta (schema_version) SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM _meta);
"""


def open_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(MIGRATION_SQL)
    conn.commit()
    return conn


def _ds(d: date) -> str:
    return d.isoformat()


def insert_intake_event(conn, d: date, ts: datetime, kcal: int, op: str, note: str | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO intake_events (date, timestamp, kcal, op, note) VALUES (?, ?, ?, ?, ?)",
        (_ds(d), ts.isoformat(), kcal, op, note),
    )
    conn.commit()
    return cur.lastrowid


def get_events_for_date(conn, d: date) -> list[IntakeEvent]:
    rows = conn.execute(
        "SELECT id, timestamp, kcal, op FROM intake_events WHERE date = ? ORDER BY timestamp ASC, id ASC",
        (_ds(d),),
    ).fetchall()
    return [IntakeEvent(id=r[0], timestamp=datetime.fromisoformat(r[1]), kcal=r[2], op=r[3]) for r in rows]


def get_events_in_range(conn, start: date, end: date) -> dict[date, DailyEvents]:
    """Half-open: [start, end)."""
    rows = conn.execute(
        "SELECT id, date, timestamp, kcal, op FROM intake_events WHERE date >= ? AND date < ? ORDER BY date, timestamp, id",
        (_ds(start), _ds(end)),
    ).fetchall()
    result: dict[date, list[IntakeEvent]] = {}
    for r in rows:
        d = date.fromisoformat(r[1])
        result.setdefault(d, []).append(IntakeEvent(id=r[0], timestamp=datetime.fromisoformat(r[2]), kcal=r[3], op=r[4]))
    return {d: DailyEvents(events=ev) for d, ev in result.items()}


@dataclass(frozen=True)
class DailyActivityRow:
    date: date
    steps: int
    distance_km: float
    logged_activities_kcal: int | None
    marginal_kcal: int | None


def upsert_daily_activity(conn, d: date, steps: int, distance_km: float,
                          logged_activities_kcal: int | None, marginal_kcal: int | None) -> None:
    conn.execute(
        """INSERT INTO daily_activity (date, steps, distance_km, logged_activities_kcal, marginal_kcal, last_synced)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(date) DO UPDATE SET
             steps=excluded.steps, distance_km=excluded.distance_km,
             logged_activities_kcal=excluded.logged_activities_kcal,
             marginal_kcal=excluded.marginal_kcal,
             last_synced=excluded.last_synced""",
        (_ds(d), steps, distance_km, logged_activities_kcal, marginal_kcal, datetime.now().isoformat()),
    )
    conn.commit()


def get_daily_activity(conn, d: date) -> DailyActivityRow | None:
    row = conn.execute(
        "SELECT date, steps, distance_km, logged_activities_kcal, marginal_kcal FROM daily_activity WHERE date = ?",
        (_ds(d),),
    ).fetchone()
    if row is None:
        return None
    return DailyActivityRow(
        date=date.fromisoformat(row[0]), steps=row[1], distance_km=row[2],
        logged_activities_kcal=row[3], marginal_kcal=row[4],
    )


@dataclass(frozen=True)
class DailyWeightRow:
    date: date
    weight_kg: float


def upsert_daily_weight(conn, d: date, weight_kg: float) -> None:
    conn.execute(
        """INSERT INTO daily_weight (date, weight_kg, last_synced) VALUES (?, ?, ?)
           ON CONFLICT(date) DO UPDATE SET weight_kg=excluded.weight_kg, last_synced=excluded.last_synced""",
        (_ds(d), weight_kg, datetime.now().isoformat()),
    )
    conn.commit()


def get_latest_weight_on_or_before(conn, d: date) -> DailyWeightRow | None:
    row = conn.execute(
        "SELECT date, weight_kg FROM daily_weight WHERE date <= ? ORDER BY date DESC LIMIT 1",
        (_ds(d),),
    ).fetchone()
    if row is None:
        return None
    return DailyWeightRow(date=date.fromisoformat(row[0]), weight_kg=row[1])
