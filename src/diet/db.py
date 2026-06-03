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
  exercise_calorie_source TEXT,  -- DEPRECATED (unused since Google Health migration; exercise source is always active_energy_kcal). Kept to avoid a schema migration.
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
  total_calories_kcal INTEGER,
  active_energy_kcal INTEGER,
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

INSERT INTO _meta (schema_version) SELECT 2 WHERE NOT EXISTS (SELECT 1 FROM _meta);
"""


def _migrate(conn) -> None:
    """Idempotent v1 (Fitbit) → v2 (Google Health) migration.

    A fresh DB is already created at v2 by MIGRATION_SQL, so each step is
    guarded by checking for the OLD artifact before acting."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(daily_activity)").fetchall()}
    if "marginal_kcal" in cols:
        conn.execute("ALTER TABLE daily_activity RENAME COLUMN marginal_kcal TO active_energy_kcal")
    if "logged_activities_kcal" in cols:
        conn.execute("ALTER TABLE daily_activity RENAME COLUMN logged_activities_kcal TO total_calories_kcal")
    version = conn.execute("SELECT schema_version FROM _meta").fetchone()[0]
    if version < 2:
        # Fitbit tokens are NOT transferable to Google — force a fresh `diet auth`.
        conn.execute("DELETE FROM fitbit_token")
        conn.execute("UPDATE _meta SET schema_version = 2")


def open_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(MIGRATION_SQL)
    _migrate(conn)
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
    total_calories_kcal: int | None
    active_energy_kcal: int | None


def upsert_daily_activity(conn, d: date, steps: int, distance_km: float,
                          total_calories_kcal: int | None, active_energy_kcal: int | None) -> None:
    conn.execute(
        """INSERT INTO daily_activity (date, steps, distance_km, total_calories_kcal, active_energy_kcal, last_synced)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(date) DO UPDATE SET
             steps=excluded.steps, distance_km=excluded.distance_km,
             total_calories_kcal=excluded.total_calories_kcal,
             active_energy_kcal=excluded.active_energy_kcal,
             last_synced=excluded.last_synced""",
        (_ds(d), steps, distance_km, total_calories_kcal, active_energy_kcal, datetime.now().isoformat()),
    )
    conn.commit()


def get_daily_activity(conn, d: date) -> DailyActivityRow | None:
    row = conn.execute(
        "SELECT date, steps, distance_km, total_calories_kcal, active_energy_kcal FROM daily_activity WHERE date = ?",
        (_ds(d),),
    ).fetchone()
    if row is None:
        return None
    return DailyActivityRow(
        date=date.fromisoformat(row[0]), steps=row[1], distance_km=row[2],
        total_calories_kcal=row[3], active_energy_kcal=row[4],
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


@dataclass(frozen=True)
class Config:
    birthday: date
    height_cm: int
    sex: str
    timezone: str
    hpasaneel_path: str | None
    hpasaneel_diet_root: str
    exercise_calorie_source: str | None
    bootstrap_daily_kcal: int | None


def save_config(conn, cfg: Config) -> None:
    conn.execute(
        """INSERT INTO config (id, birthday, height_cm, sex, timezone, hpasaneel_path,
                              hpasaneel_diet_root, exercise_calorie_source, bootstrap_daily_kcal)
           VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
             birthday=excluded.birthday, height_cm=excluded.height_cm, sex=excluded.sex,
             timezone=excluded.timezone, hpasaneel_path=excluded.hpasaneel_path,
             hpasaneel_diet_root=excluded.hpasaneel_diet_root,
             exercise_calorie_source=excluded.exercise_calorie_source,
             bootstrap_daily_kcal=excluded.bootstrap_daily_kcal""",
        (cfg.birthday.isoformat(), cfg.height_cm, cfg.sex, cfg.timezone, cfg.hpasaneel_path,
         cfg.hpasaneel_diet_root, cfg.exercise_calorie_source, cfg.bootstrap_daily_kcal),
    )
    conn.commit()


def load_config(conn) -> Config | None:
    row = conn.execute(
        "SELECT birthday, height_cm, sex, timezone, hpasaneel_path, hpasaneel_diet_root, "
        "exercise_calorie_source, bootstrap_daily_kcal FROM config WHERE id=1"
    ).fetchone()
    if row is None:
        return None
    return Config(birthday=date.fromisoformat(row[0]), height_cm=row[1], sex=row[2], timezone=row[3],
                  hpasaneel_path=row[4], hpasaneel_diet_root=row[5],
                  exercise_calorie_source=row[6], bootstrap_daily_kcal=row[7])


@dataclass(frozen=True)
class Token:
    access_token: str
    refresh_token: str
    expires_at: datetime
    user_id: str


def save_token_atomic(conn, tok: Token) -> None:
    """BEGIN IMMEDIATE で他プロセスと排他、全置換、commit。"""
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("DELETE FROM fitbit_token")
        conn.execute(
            "INSERT INTO fitbit_token (id, access_token, refresh_token, expires_at, user_id, rotated_at) "
            "VALUES (1, ?, ?, ?, ?, ?)",
            (tok.access_token, tok.refresh_token, tok.expires_at.isoformat(), tok.user_id, datetime.now().isoformat()),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def load_token(conn) -> Token | None:
    row = conn.execute(
        "SELECT access_token, refresh_token, expires_at, user_id FROM fitbit_token WHERE id=1"
    ).fetchone()
    if row is None:
        return None
    return Token(access_token=row[0], refresh_token=row[1],
                 expires_at=datetime.fromisoformat(row[2]), user_id=row[3])
