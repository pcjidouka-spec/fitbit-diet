# Google Health API Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the single-user `diet` CLI from the (shutting-down) Fitbit Web API to the Google Health API v4, preserving all features (steps, distance, exercise calories, weight, publish) with no data-correctness regressions.

**Architecture:** Standard Google OAuth 2.0 (loopback HTTP callback, no TLS cert) + a thin `GoogleHealthClient` adapter that hides all REST/JSON-shape knowledge behind plain-number methods. Exercise calories are sourced from `active-energy-burned` (BMR-free, the documented successor to Fitbit "Activity Calories"); `total-calories` (BMR-inclusive) is stored for diagnostics only and is **never** used in the balance. Parsing is isolated in the adapter so the field names that are still unverified against a live account can be corrected in one place during E2E.

**Tech Stack:** Python 3.11+, `httpx` (async), `click`, SQLite (`sqlite3`), `pytest` + `pytest-httpx` + `pytest-asyncio` (`asyncio_mode=auto`) + `pytest-mock`. Run everything with `py -m uv run ...` on Windows.

---

## Decisions locked in (from the 2026-06-01 design session)

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | **Exercise calorie source = `active-energy-burned` (fixed).** `total-calories` stored as diagnostic only; `calibrate`'s source-selection is removed. | Google has no `marginalCalories`. `active-energy-burned` is documented as **excluding** basal burn; `total-calories` **includes** BMR and would reintroduce the double-count the spec forbids. (codex + synthesis agreement) |
| 2 | **OAuth flow = local HTTP loopback callback server.** Drop the self-signed cert entirely; register `http://localhost:8765/callback`. | Google exempts `localhost` from the HTTPS-only redirect rule, so the cert machinery is dead weight. Keeps the auto-browser UX. Manual-paste (`https://www.google.com`) is the documented fallback if loopback fails live. |
| 3 | **Publish OAuth consent screen to Production.** | In Testing status refresh tokens expire in 7 days (kills a daily sync). Single-user < 100-user cap ⇒ no security review needed. (README/spec instruction, not code.) |
| 4 | **Discard old Fitbit token on upgrade; re-auth.** Populate `user_id` from `GET /users/me/identity`. | Fitbit tokens are NOT transferable to Google. A schema bump deletes the stale token row. |
| 5 | **Keep `distance`** via the Google `distance` data type (confirmed to exist). | No dashboard regression. |

## Confirmed API contract (verbatim from docs)

- Authorization URL: `https://accounts.google.com/o/oauth2/v2/auth`
- Token URL: `https://oauth2.googleapis.com/token`
- API base: `https://health.googleapis.com/v4`
- Scopes (read-only): `https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly` and `https://www.googleapis.com/auth/googlehealth.health_metrics_and_measurements.readonly`
- Daily rollup: `POST /v4/users/me/dataTypes/{type}/dataPoints:dailyRollUp` with body `{"range":{"start":{"date":{year,month,day}},"end":{"date":{...next day...}}},"windowSizeDays":1}` → `{"rollupDataPoints":[{"value":{...}}]}`
- Steps value key: `countSum` (int64) — **confirmed**
- Active energy value key: `kcalSum` (double) — **confirmed**
- Weight: `GET /v4/users/me/dataTypes/weight/dataPoints?filter=...` → `dataPoints[].weight.weightGrams` (**grams**, confirmed) + `dataPoints[].weight.sampleTime.civilTime.date`

## ⚠️ Field names ASSUMED (must be re-verified in Task 6 live E2E — isolate in the adapter)

| Use | Assumed shape | Status |
|-----|---------------|--------|
| Distance rollup value key | `meterSum` (meters → /1000 km) | **ASSUMED** |
| Total-calories rollup value key | `kcalSum` (double) | **ASSUMED** (follows ActiveEnergy pattern) |
| Identity response | `{"healthUserId": "...", "legacyUserId": "..."}` | **ASSUMED** (fallback to `"me"`) |
| Weight filter field | `weight.sample_time.civil_time` | **ASSUMED** |
| Rollup `value` is keyed directly (e.g. `value.countSum`, not `value.steps.countSum`) | direct | **ASSUMED** |

These are the only places a live-API surprise can bite. Each is read in exactly one adapter method, so a fix is a one-line change.

---

## File Structure

| File | Responsibility after migration |
|------|--------------------------------|
| `src/diet/oauth.py` | Google OAuth 2.0: build authz URL (offline+consent), plain-HTTP loopback callback, token exchange/refresh (creds in body, refresh-token carry-forward), `fetch_user_id` via identity endpoint. **No cert code.** |
| `src/diet/google_health_client.py` (renamed from `fitbit_client.py`) | `GoogleHealthClient` adapter: per-day `dailyRollUp` for steps/active-energy/total-calories/distance + weight `list`; grams→kg; 401 single-retry. No rate-limit headers. |
| `src/diet/cli_helpers.py` | Sync loop using the new adapter; writes `active_energy_kcal` + `total_calories_kcal` + distance + steps; weight normalization; `GOOGLE_*` env. |
| `src/diet/db.py` | Schema rename `marginal_kcal→active_energy_kcal`, `logged_activities_kcal→total_calories_kcal`; v1→v2 migration (rename columns + wipe token row); `Token`/`DailyActivityRow` updates. |
| `src/diet/helpers.py` | `resolve_exercise_kcal(activity)` → always `active_energy_kcal`. |
| `src/diet/publish.py` | `build_records_from_db(conn, target_dates)` → always `active_energy_kcal`. |
| `src/diet/orchestrator.py` | Updated call sites for the two signature changes above. |
| `src/diet/calibrate.py` | Informational display only (active-energy vs total-calories review); no source selection. |
| `src/diet/cli.py` | `auth` loses `--regen-cert`; `GOOGLE_*` comments; Google-Health wording. |
| `.env.example` (new) | `GOOGLE_CLIENT_ID/SECRET/REDIRECT_URI`. |
| `docs/superpowers/specs/2026-05-25-fitbit-diet-design.md` | Rev 10 amendment. |
| `README.md` | GCP registration + auth steps. |
| `docs/superpowers/plans/2026-06-01-google-health-api-e2e-checklist.md` (new) | Live E2E verification checklist (Task 6). |

**Branch:** work on the existing clean `feat/fitbit-diet-cli` branch (this migration is the continuation of that feature / Phase 10.2). Commit per task.

**Test command (every step):** `py -m uv run pytest -q` (full suite) or `py -m uv run pytest tests/<file>::<test> -v` (single).

---

## Task 1: Calorie column rename + active-energy semantics (DB + consumers)

Rename the two activity-calorie columns end-to-end so `active_energy_kcal` is the single BMR-free exercise source and `total_calories_kcal` is diagnostic-only. This task is self-contained (no API/network) and must leave the full suite green.

**Files:**
- Modify: `src/diet/db.py`
- Modify: `src/diet/helpers.py`
- Modify: `src/diet/publish.py:92-128`
- Modify: `src/diet/orchestrator.py` (call sites for `resolve_exercise_kcal` and `build_records_from_db`)
- Test: `tests/test_db.py`, `tests/test_cli_calibrate.py`, `tests/test_orchestrator_e2e.py`, `tests/test_publish_merge.py`, `tests/test_publish_boundary.py`, `tests/test_publish_schema.py`, `tests/test_cli_show.py`, `tests/test_edgecases.py`

- [ ] **Step 1.1: Write a failing migration test** in `tests/test_db.py`:

```python
def test_v1_db_migrates_columns_and_wipes_token(tmp_path):
    """A pre-existing v1 schema (Fitbit) must be migrated to v2: activity
    columns renamed, stale token row deleted, schema_version bumped."""
    import sqlite3
    from datetime import datetime
    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE _meta (schema_version INTEGER NOT NULL);
        INSERT INTO _meta VALUES (1);
        CREATE TABLE daily_activity (
          date TEXT PRIMARY KEY, steps INTEGER NOT NULL, distance_km REAL NOT NULL,
          logged_activities_kcal INTEGER, marginal_kcal INTEGER, last_synced TEXT NOT NULL);
        INSERT INTO daily_activity VALUES ('2026-05-25', 8000, 5.0, 250, 300, '2026-05-25T00:00:00');
        CREATE TABLE fitbit_token (
          id INTEGER PRIMARY KEY CHECK (id=1), access_token TEXT NOT NULL,
          refresh_token TEXT NOT NULL, expires_at TEXT NOT NULL, user_id TEXT NOT NULL,
          rotated_at TEXT NOT NULL);
        INSERT INTO fitbit_token VALUES (1,'A','R','2030-01-01T00:00:00','U','2026-05-25T00:00:00');
        """
    )
    conn.commit(); conn.close()

    from diet.db import open_db, get_daily_activity, load_token
    conn = open_db(db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(daily_activity)").fetchall()}
    assert "active_energy_kcal" in cols and "total_calories_kcal" in cols
    assert "marginal_kcal" not in cols and "logged_activities_kcal" not in cols
    from datetime import date
    a = get_daily_activity(conn, date(2026, 5, 25))
    assert a.active_energy_kcal == 300 and a.total_calories_kcal == 250
    assert load_token(conn) is None  # stale Fitbit token wiped
    assert conn.execute("SELECT schema_version FROM _meta").fetchone()[0] == 2
```

- [ ] **Step 1.2: Run it — expect FAIL** (`active_energy_kcal` not in cols / AttributeError).

Run: `py -m uv run pytest tests/test_db.py::test_v1_db_migrates_columns_and_wipes_token -v`

- [ ] **Step 1.3: Update `db.py` schema + migration.**

In `MIGRATION_SQL`, change the `daily_activity` DDL columns to the new names:

```sql
CREATE TABLE IF NOT EXISTS daily_activity (
  date TEXT PRIMARY KEY,
  steps INTEGER NOT NULL,
  distance_km REAL NOT NULL,
  total_calories_kcal INTEGER,
  active_energy_kcal INTEGER,
  last_synced TEXT NOT NULL
);
```

Add a migration function and call it from `open_db` (after `executescript`, before `commit`):

```python
def _migrate(conn) -> None:
    """Idempotent v1 (Fitbit) → v2 (Google Health) migration.

    A fresh DB is already created at v2 by MIGRATION_SQL, so each step is
    guarded by checking for the OLD artifact before acting.
    """
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
```

```python
def open_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(MIGRATION_SQL)
    _migrate(conn)
    conn.commit()
    return conn
```

> Note: a fresh DB gets `daily_activity` with the new column names, so the `ALTER ... RENAME` branches are skipped (the old names aren't present). The `version < 2` branch still bumps a fresh DB from the `INSERT ... SELECT 1` default — that's fine; wiping an empty `fitbit_token` is a no-op. To keep a fresh DB at v2 directly, change the seed line to `INSERT INTO _meta (schema_version) SELECT 2 WHERE NOT EXISTS (SELECT 1 FROM _meta);` and the migration's `version < 2` branch only fires for genuine v1 DBs.

- [ ] **Step 1.4: Update `db.py` dataclass + functions.**

```python
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
```

> ⚠️ `upsert_daily_activity` argument **order changes** to `(..., total_calories_kcal, active_energy_kcal)`. Every existing caller passes positional `(logged, marginal)`; the new positional order is `(total_calories, active_energy)`. Because the old call sites used keyword args (`logged_activities_kcal=...`, `marginal_kcal=...`), update them to the new keywords (`total_calories_kcal=...`, `active_energy_kcal=...`). The `test_edgecases.py` positional call `upsert_daily_activity(conn, target, 8000, 5.0, 250, 300)` keeps the same numbers but now means `total_calories=250, active_energy=300` (the 300 was `marginal` → now `active_energy`; semantics preserved since marginal→active_energy is the rename).

- [ ] **Step 1.5: Update `helpers.py`** to drop source branching:

```python
def resolve_exercise_kcal(activity) -> int:
    """Exercise kcal for the day = active-energy-burned (BMR-free).

    Google Health has no marginalCalories; active-energy-burned is the
    documented BMR-free successor. total_calories_kcal is diagnostic-only
    and is intentionally NOT selectable, to prevent BMR double-counting.
    """
    if activity is None:
        return 0
    return activity.active_energy_kcal or 0
```

- [ ] **Step 1.6: Update `publish.py:92-128`** `build_records_from_db` — drop the `exercise_calorie_source` parameter and branch:

```python
def build_records_from_db(conn, target_dates: list[date]) -> list[PublicDayRecord]:
    """Read publishable records from the DB.

    ★ Privacy boundary unchanged: SELECT only from daily_activity + daily_weight.
    exercise_kcal = active_energy_kcal (BMR-free).
    """
    from diet.db import get_daily_activity, get_latest_weight_on_or_before
    records: list[PublicDayRecord] = []
    for d in target_dates:
        a = get_daily_activity(conn, d)
        w = get_latest_weight_on_or_before(conn, d)
        if a is None or w is None:
            continue
        records.append(
            PublicDayRecord(
                date=d, steps=a.steps, distance_km=a.distance_km,
                exercise_kcal=a.active_energy_kcal or 0, weight_kg=w.weight_kg,
            )
        )
    return records
```

- [ ] **Step 1.7: Update `orchestrator.py` call sites.**

- `resolve_exercise_kcal(activity, cfg.exercise_calorie_source)` → `resolve_exercise_kcal(activity)` (2 sites: ~line 113, ~line 200).
- `build_records_from_db(conn, [today], cfg.exercise_calorie_source or "marginal")` → `build_records_from_db(conn, [today])` (~line 138).
- Read the surrounding code first; if any other `build_records_from_db`/`resolve_exercise_kcal` calls exist, update them too (grep).

- [ ] **Step 1.8: Update affected tests (mechanical).**

General rules to apply across `tests/test_orchestrator_e2e.py`, `tests/test_cli_show.py`, `tests/test_publish_merge.py`, `tests/test_publish_boundary.py`, `tests/test_publish_schema.py`:
  - `upsert_daily_activity(... logged_activities_kcal=L, marginal_kcal=M)` keyword calls → `total_calories_kcal=L, active_energy_kcal=M` (marginal→active_energy preserves the exercise value).
  - positional `upsert_daily_activity(conn, d, steps, dist, L, M)` → numerically identical; the 4th/5th args are now `total_calories_kcal=L, active_energy_kcal=M` semantically (no edit needed unless an assertion reads the renamed attribute).
  - `build_records_from_db(...)` in **both** positional form `build_records_from_db(conn, dates, "marginal"|"logged_activities")` **and keyword form** `build_records_from_db(conn, target_dates=[...], exercise_calorie_source="marginal")` → drop the source argument entirely: `build_records_from_db(conn, target_dates=[...])`.
  - `.marginal_kcal` / `.logged_activities_kcal` attribute reads → `.active_energy_kcal` / `.total_calories_kcal`.

- **`tests/test_publish_boundary.py` (★ privacy-boundary file — DO NOT skip; these are load-bearing).** Exact sites:
  - lines ~72-79 and ~106-113: `upsert_daily_activity(conn, target, steps=..., distance_km=..., logged_activities_kcal=X, marginal_kcal=Y)` → `total_calories_kcal=X, active_energy_kcal=Y`.
  - line ~135: positional `upsert_daily_activity(conn, target, 1, 1.0, 1, 1)` → unchanged (numbers identical).
  - **3 sites** (lines ~82-84, ~118-120, ~140-142): `build_records_from_db(conn, target_dates=[target], exercise_calorie_source="marginal")` → `build_records_from_db(conn, target_dates=[target])`. These will raise `TypeError: unexpected keyword argument 'exercise_calorie_source'` after Step 1.6 if missed, so Step 1.10 cannot go green without this edit.
- **`tests/test_publish_merge.py` / `tests/test_publish_schema.py`:** grep first — if they contain no `upsert_daily_activity` / `build_records_from_db` / `marginal_kcal` references, they need no edit (likely no-ops).
- `tests/test_edgecases.py`: the two `upsert_daily_activity(conn, target, 8000, 5.0, 250, 300)` positional calls stay numerically identical (now total=250, active=300). No change needed unless an assertion reads the old attribute names.

> Note: `src/diet/calibrate.py` still reads `a.marginal_kcal` at this point and is rewritten in Task 4 (calibrate). Its tests are deferred in Step 1.9, so the green suite is unaffected; the module is simply not exercised until Task 4.

- [ ] **Step 1.9: Defer `test_cli_calibrate.py`** to Task 4 (calibrate is rewritten there). For now, if its `marginal` assertions break, temporarily `@pytest.mark.skip` the two calibrate tests with reason `"rewritten in Task 4"`; the rewrite in Step 4.1 replaces the whole file (removing the skips).

- [ ] **Step 1.10: Run full suite — expect PASS** (except any intentionally-skipped calibrate tests).

Run: `py -m uv run pytest -q`

- [ ] **Step 1.11: Commit.**

```bash
git add -A
git commit -m "refactor(db): rename activity calorie columns to active_energy/total_calories + v2 migration"
```

---

## Task 2: OAuth → Google (oauth.py + cli.py auth)

Swap Fitbit OAuth for Google OAuth 2.0; drop the self-signed cert; loopback over plain HTTP; creds in body; refresh-token carry-forward; populate `user_id` from the identity endpoint.

**Files:**
- Modify: `src/diet/oauth.py`
- Modify: `src/diet/cli.py:85-107` (`auth` command — remove `--regen-cert`/cert logic) and `:9-13` (comment)
- Test: `tests/test_oauth.py` (rewrite), `tests/test_cli_auth.py` (rewrite cert cases), `tests/test_cli_init.py` (env rename), `tests/test_edgecases.py` (cert + refresh tests)

- [ ] **Step 2.1: Rewrite `tests/test_oauth.py`** (cert tests removed; Google URLs/scopes; refresh carry-forward; identity):

```python
from urllib.parse import parse_qs, urlparse

import pytest

from diet.oauth import (
    GOOGLE_AUTHZ_URL,
    GOOGLE_TOKEN_URL,
    SCOPES,
    build_authorization_url,
    exchange_code_for_token,
    refresh_access_token,
)


def test_build_authz_url_params():
    url = build_authorization_url("CID", "http://localhost:8765/callback", SCOPES, "state123")
    assert url.startswith(GOOGLE_AUTHZ_URL)
    qs = parse_qs(urlparse(url).query)
    assert qs["client_id"] == ["CID"]
    assert qs["response_type"] == ["code"]
    assert qs["redirect_uri"] == ["http://localhost:8765/callback"]
    assert qs["access_type"] == ["offline"]
    assert qs["prompt"] == ["consent"]
    assert "googlehealth.activity_and_fitness.readonly" in qs["scope"][0]
    assert "googlehealth.health_metrics_and_measurements.readonly" in qs["scope"][0]
    assert qs["state"] == ["state123"]


async def test_exchange_success_populates_user_id_from_identity(httpx_mock):
    httpx_mock.add_response(
        url=GOOGLE_TOKEN_URL, method="POST",
        json={"access_token": "A1", "refresh_token": "R1", "expires_in": 3599, "scope": "x", "token_type": "Bearer"},
    )
    httpx_mock.add_response(
        url="https://health.googleapis.com/v4/users/me/identity",
        json={"healthUserId": "HUID", "legacyUserId": "LUID"},
    )
    tok = await exchange_code_for_token("CID", "CSEC", "C1", "http://localhost:8765/callback")
    assert tok.access_token == "A1"
    assert tok.refresh_token == "R1"
    assert tok.user_id == "HUID"


async def test_exchange_identity_failure_falls_back_to_me(httpx_mock):
    httpx_mock.add_response(
        url=GOOGLE_TOKEN_URL, method="POST",
        json={"access_token": "A1", "refresh_token": "R1", "expires_in": 3599},
    )
    httpx_mock.add_response(
        url="https://health.googleapis.com/v4/users/me/identity", status_code=500, json={}
    )
    tok = await exchange_code_for_token("CID", "CSEC", "C1", "http://localhost:8765/callback")
    assert tok.user_id == "me"  # graceful fallback


async def test_refresh_without_new_refresh_token_carries_forward(httpx_mock):
    """Google omits refresh_token on refresh — must carry the old one forward."""
    httpx_mock.add_response(
        url=GOOGLE_TOKEN_URL, method="POST",
        json={"access_token": "A2", "expires_in": 3599, "scope": "x", "token_type": "Bearer"},
    )
    tok = await refresh_access_token("CID", "CSEC", "R1", user_id="HUID")
    assert tok.access_token == "A2"
    assert tok.refresh_token == "R1"   # carried forward
    assert tok.user_id == "HUID"       # carried forward


async def test_refresh_with_new_refresh_token_uses_it(httpx_mock):
    httpx_mock.add_response(
        url=GOOGLE_TOKEN_URL, method="POST",
        json={"access_token": "A2", "refresh_token": "R2", "expires_in": 3599},
    )
    tok = await refresh_access_token("CID", "CSEC", "R1", user_id="HUID")
    assert tok.refresh_token == "R2"


async def test_exchange_4xx_raises(httpx_mock):
    httpx_mock.add_response(
        url=GOOGLE_TOKEN_URL, method="POST", status_code=400, json={"error": "invalid_grant"},
    )
    import httpx
    with pytest.raises(httpx.HTTPStatusError):
        await exchange_code_for_token("CID", "CSEC", "BAD", "http://localhost:8765/callback")
```

- [ ] **Step 2.2: Run — expect FAIL** (imports `GOOGLE_AUTHZ_URL` etc. don't exist).

- [ ] **Step 2.3: Rewrite `src/diet/oauth.py`:**

```python
import http.server
import threading
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import httpx

from diet.db import Token

GOOGLE_AUTHZ_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
HEALTH_BASE = "https://health.googleapis.com/v4"
SCOPES = [
    "https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly",
    "https://www.googleapis.com/auth/googlehealth.health_metrics_and_measurements.readonly",
]


def build_authorization_url(client_id: str, redirect_uri: str, scopes: list[str], state: str) -> str:
    params = {
        "client_id": client_id,
        "response_type": "code",
        "scope": " ".join(scopes),
        "redirect_uri": redirect_uri,
        "state": state,
        "access_type": "offline",   # request a refresh_token
        "prompt": "consent",        # force refresh_token issuance on re-auth
    }
    return f"{GOOGLE_AUTHZ_URL}?{urllib.parse.urlencode(params)}"


@dataclass
class CallbackResult:
    code: str | None = None
    state: str | None = None
    error: str | None = None


def run_callback_server(port: int = 8765, timeout_sec: int = 300) -> CallbackResult:
    """Listen for the OAuth redirect once over plain HTTP, then shut down.

    Google exempts http://localhost from the HTTPS-only redirect rule, so no
    TLS certificate is needed.
    """
    result = CallbackResult()
    finished = threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != "/callback":
                self.send_response(404); self.end_headers(); return
            qs = urllib.parse.parse_qs(parsed.query)
            result.code = (qs.get("code") or [None])[0]
            result.state = (qs.get("state") or [None])[0]
            result.error = (qs.get("error") or [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<h1>Authorization received</h1><p>You can close this tab.</p>")
            finished.set()
        def log_message(self, fmt, *args): pass

    httpd = http.server.HTTPServer(("localhost", port), Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    finished.wait(timeout=timeout_sec)
    httpd.shutdown()
    return result


async def _post_token(data: dict) -> dict:
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    async with httpx.AsyncClient() as client:
        r = await client.post(GOOGLE_TOKEN_URL, data=data, headers=headers, timeout=30.0)
        r.raise_for_status()
        return r.json()


async def fetch_user_id(access_token: str) -> str:
    """Resolve the user id via GET /users/me/identity. Falls back to "me" on
    any failure or unexpected shape (the response schema is unverified)."""
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{HEALTH_BASE}/users/me/identity",
                headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
                timeout=30.0,
            )
            r.raise_for_status()
            body = r.json()
        return body.get("healthUserId") or body.get("legacyUserId") or "me"
    except Exception:  # noqa: BLE001 — identity is best-effort
        return "me"


async def exchange_code_for_token(client_id: str, client_secret: str, code: str, redirect_uri: str) -> Token:
    body = await _post_token({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "client_secret": client_secret,
    })
    user_id = await fetch_user_id(body["access_token"])
    return Token(
        access_token=body["access_token"],
        refresh_token=body["refresh_token"],
        expires_at=datetime.now() + timedelta(seconds=int(body["expires_in"])),
        user_id=user_id,
    )


async def refresh_access_token(client_id: str, client_secret: str, refresh_token: str, user_id: str = "me") -> Token:
    body = await _post_token({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
    })
    return Token(
        access_token=body["access_token"],
        refresh_token=body.get("refresh_token", refresh_token),  # Google omits it ⇒ carry forward
        expires_at=datetime.now() + timedelta(seconds=int(body["expires_in"])),
        user_id=user_id,
    )


def run_init_flow(data_dir: Path, port: int, conn) -> None:
    """Build URL, open browser, run loopback callback, exchange, save token."""
    import asyncio
    import os
    import secrets
    import webbrowser

    from diet.db import save_token_atomic

    client_id = os.environ["GOOGLE_CLIENT_ID"]
    client_secret = os.environ["GOOGLE_CLIENT_SECRET"]
    redirect = os.environ.get("GOOGLE_REDIRECT_URI", f"http://localhost:{port}/callback")
    state = secrets.token_urlsafe(16)
    url = build_authorization_url(client_id, redirect, SCOPES, state)
    print(f"ブラウザを開いて以下の URL にアクセスし、Google アカウントで認可してください:\n{url}")
    webbrowser.open(url)
    cb = run_callback_server(port=port)
    if cb.error or not cb.code or cb.state != state:
        raise RuntimeError(f"OAuth failed: error={cb.error}, state mismatch?")
    tok = asyncio.run(exchange_code_for_token(client_id, client_secret, cb.code, redirect))
    save_token_atomic(conn, tok)
    print("Google Health OAuth 成功、token 保存完了。")
```

> Removed: `generate_self_signed_cert`, all `ssl`/`cryptography`/`base64` imports. `data_dir` is now unused by `run_init_flow` but kept in the signature for the `cli.py` call compatibility (it's harmless; or drop it and update the 2 call sites).

- [ ] **Step 2.4: Run `tests/test_oauth.py` — expect PASS.**

- [ ] **Step 2.5: Update `cli.py` `auth` command** (`:85-107`): remove `--regen-cert` option and the cert block; drop `generate_self_signed_cert` import:

```python
@app.command()
@click.option("--port", default=8765, type=click.IntRange(min=1, max=65535))
def auth(port: int) -> None:
    """Re-run Google OAuth (without re-prompting profile)."""
    from diet.db import load_config
    from diet.oauth import run_init_flow

    data_dir = _data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    conn = open_db(data_dir / "diet.db")
    if load_config(conn) is None:
        raise click.ClickException("config が未初期化です。先に `diet init` を実行してください。")
    run_init_flow(data_dir=data_dir, port=port, conn=conn)
```

Also update the comment at `cli.py:9-12` to reference `GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET`.

- [ ] **Step 2.6: Rewrite the cert/auth tests.**

- `tests/test_cli_auth.py`: delete `test_auth_regen_cert_removes_existing_and_regenerates`; in the other tests change `monkeypatch.setenv("FITBIT_CLIENT_ID"...)` → `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` where present (the `_seed_config` `exercise_calorie_source="marginal"` value is harmless — leave or set `None`). Keep `test_auth_runs_oauth_flow`, `test_auth_custom_port`, `test_auth_without_config_fails_cleanly`.
- `tests/test_edgecases.py`: **delete** `test_cert_validity_period`, `test_generate_idempotent_when_both_exist`, `test_cli_auth_regen_cert_replaces_files` (cert is gone). Rename every `monkeypatch.setenv("FITBIT_CLIENT_ID", ...)`/`FITBIT_CLIENT_SECRET` → `GOOGLE_*` (≈10 sites). The refresh tests (`test_refresh_failure_with_revoked_token_propagates`, `test_cli_sync_with_real_*`) hit the token endpoint — change `url="https://api.fitbit.com/oauth2/token"` → `GOOGLE_TOKEN_URL` value `https://oauth2.googleapis.com/token`, change `refresh_access_token("CID","CSEC","REVOKED_REFRESH")` is fine (user_id defaults). These also mock the activity endpoint — those URL changes belong to Task 3/4 (see note). To keep the suite green at the Task 2 boundary, the activity-endpoint mocks in `test_cli_sync_with_real_*` will still reference the old client until Task 3; if that breaks, mark those four `test_cli_sync_with_real_*` tests `@pytest.mark.skip(reason="rewritten in Task 4")` and restore in Task 4.
- `tests/test_cli_init.py`: rename `FITBIT_CLIENT_ID`/`FITBIT_CLIENT_SECRET` → `GOOGLE_*`.

- [ ] **Step 2.7: Run full suite — expect PASS** (with Task-3/4-deferred skips noted).

- [ ] **Step 2.8: Commit.**

```bash
git add -A
git commit -m "feat(oauth): migrate to Google OAuth 2.0 loopback flow, drop self-signed cert"
```

---

## Task 3: GoogleHealthClient + sync loop rewrite

Rename the client module and rewrite the adapter + the per-day sync loop together (they are tightly coupled).

**Files:**
- Rename/Create: `src/diet/fitbit_client.py` → `src/diet/google_health_client.py`
- Modify: `src/diet/cli_helpers.py`
- Modify: `src/diet/cli.py` (sync command wording + the `sync` import of client if any)
- Test: rename `tests/test_fitbit_client.py` → `tests/test_google_health_client.py` (rewrite); rename `tests/test_fitbit_client_rate_limit.py` → fold into the new file or `tests/test_google_health_client_429.py`; update `tests/test_cli_sync.py`, `tests/test_edgecases.py` (429 + real-refresh tests).

- [ ] **Step 3.1: Write `tests/test_google_health_client.py`:**

```python
import datetime as dt

import pytest

from diet.google_health_client import GoogleHealthClient, BASE

D = dt.date(2026, 5, 25)


async def test_daily_steps_rollup(httpx_mock):
    httpx_mock.add_response(
        url=f"{BASE}/users/me/dataTypes/steps/dataPoints:dailyRollUp", method="POST",
        json={"rollupDataPoints": [{"value": {"countSum": 8123}}]},
        match_headers={"Authorization": "Bearer A1"},
    )
    client = GoogleHealthClient(access_token="A1")
    assert await client.get_daily_steps(D) == 8123


async def test_daily_active_energy_rollup(httpx_mock):
    httpx_mock.add_response(
        url=f"{BASE}/users/me/dataTypes/active-energy-burned/dataPoints:dailyRollUp", method="POST",
        json={"rollupDataPoints": [{"value": {"kcalSum": 412.7}}]},
    )
    client = GoogleHealthClient(access_token="A1")
    assert await client.get_daily_active_energy_kcal(D) == 413  # rounded


async def test_daily_distance_km_converts_meters(httpx_mock):
    httpx_mock.add_response(
        url=f"{BASE}/users/me/dataTypes/distance/dataPoints:dailyRollUp", method="POST",
        json={"rollupDataPoints": [{"value": {"meterSum": 5230}}]},
    )
    client = GoogleHealthClient(access_token="A1")
    assert await client.get_daily_distance_km(D) == 5.23


async def test_empty_rollup_returns_zero(httpx_mock):
    httpx_mock.add_response(
        url=f"{BASE}/users/me/dataTypes/steps/dataPoints:dailyRollUp", method="POST",
        json={"rollupDataPoints": []},
    )
    client = GoogleHealthClient(access_token="A1")
    assert await client.get_daily_steps(D) == 0


async def test_weight_log_grams_to_kg_and_local_date(httpx_mock):
    httpx_mock.add_response(
        url__regex=r".*/users/me/dataTypes/weight/dataPoints.*", method="GET",
        json={"dataPoints": [{"weight": {
            "weightGrams": 71200,
            "sampleTime": {"civilTime": {"date": {"year": 2026, "month": 5, "day": 25}},
                           "physicalTime": "2026-05-25T07:30:00+09:00"},
        }}]},
    )
    client = GoogleHealthClient(access_token="A1")
    out = await client.get_weight_log(D)
    assert out == [{"date": "2026-05-25", "weight_kg": 71.2}]


async def test_401_triggers_one_refresh(httpx_mock):
    url = f"{BASE}/users/me/dataTypes/steps/dataPoints:dailyRollUp"
    httpx_mock.add_response(url=url, method="POST", status_code=401, json={})
    httpx_mock.add_response(url=url, method="POST", json={"rollupDataPoints": [{"value": {"countSum": 10}}]})
    calls = {"n": 0}
    async def refresh():
        calls["n"] += 1
        return "A2"
    client = GoogleHealthClient(access_token="A1", on_unauthorized=refresh)
    assert await client.get_daily_steps(D) == 10
    assert calls["n"] == 1 and client.access_token == "A2"


async def test_401_twice_raises(httpx_mock):
    url = f"{BASE}/users/me/dataTypes/steps/dataPoints:dailyRollUp"
    httpx_mock.add_response(url=url, method="POST", status_code=401, json={})
    httpx_mock.add_response(url=url, method="POST", status_code=401, json={})
    async def refresh():
        return "A2"
    client = GoogleHealthClient(access_token="A1", on_unauthorized=refresh)
    import httpx
    with pytest.raises(httpx.HTTPStatusError):
        await client.get_daily_steps(D)


async def test_429_raises(httpx_mock):
    httpx_mock.add_response(
        url=f"{BASE}/users/me/dataTypes/steps/dataPoints:dailyRollUp", method="POST",
        status_code=429, json={"error": {"code": 429, "status": "RESOURCE_EXHAUSTED"}},
    )
    import httpx
    client = GoogleHealthClient(access_token="A1")
    with pytest.raises(httpx.HTTPStatusError):
        await client.get_daily_steps(D)
```

> `url__regex` / `match_headers` are pytest-httpx features; if the installed version uses a different kwarg (`url=re.compile(...)`), adapt. For the weight filter URL, matching by regex avoids brittleness over the exact encoded `filter=` query.

- [ ] **Step 3.2: Run — expect FAIL** (module `google_health_client` missing).

- [ ] **Step 3.3: Create `src/diet/google_health_client.py`** (delete `fitbit_client.py`):

```python
from datetime import date, timedelta

import httpx

BASE = "https://health.googleapis.com/v4"


class GoogleHealthClient:
    """Adapter over the Google Health API v4 data endpoints.

    All HTTP + JSON-shape knowledge lives here so callers see plain numbers.
    CONFIRMED field names: steps countSum, active-energy-burned kcalSum,
    weight weightGrams. ASSUMED (verify in live E2E): distance meterSum,
    total-calories kcalSum, weight filter field weight.sample_time.civil_time,
    and that the rollup `value` is keyed directly (value.countSum).
    """

    def __init__(self, access_token: str, on_unauthorized=None):
        self.access_token = access_token
        self.on_unauthorized = on_unauthorized

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}", "Accept": "application/json"}

    async def _request(self, method: str, url: str, *, json=None, params=None) -> httpx.Response:
        async with httpx.AsyncClient() as client:
            r = await client.request(method, url, headers=self._headers(), json=json, params=params, timeout=30.0)
            if r.status_code == 401 and self.on_unauthorized:
                self.access_token = await self.on_unauthorized()  # single retry only
                async with httpx.AsyncClient() as client2:
                    r = await client2.request(method, url, headers=self._headers(), json=json, params=params, timeout=30.0)
            r.raise_for_status()
            return r

    @staticmethod
    def _civil_day_body(d: date) -> dict:
        nxt = d + timedelta(days=1)
        return {
            "range": {
                "start": {"date": {"year": d.year, "month": d.month, "day": d.day}},
                "end": {"date": {"year": nxt.year, "month": nxt.month, "day": nxt.day}},
            },
            "windowSizeDays": 1,
        }

    async def _daily_rollup_value(self, data_type: str, d: date, value_key: str):
        url = f"{BASE}/users/me/dataTypes/{data_type}/dataPoints:dailyRollUp"
        r = await self._request("POST", url, json=self._civil_day_body(d))
        points = r.json().get("rollupDataPoints", [])
        if not points:
            return None
        return points[0].get("value", {}).get(value_key)

    async def get_daily_steps(self, d: date) -> int:
        v = await self._daily_rollup_value("steps", d, "countSum")
        return int(v or 0)

    async def get_daily_active_energy_kcal(self, d: date) -> int:
        v = await self._daily_rollup_value("active-energy-burned", d, "kcalSum")
        return round(v) if v is not None else 0

    async def get_daily_total_calories_kcal(self, d: date) -> int:
        v = await self._daily_rollup_value("total-calories", d, "kcalSum")  # ASSUMED key
        return round(v) if v is not None else 0

    async def get_daily_distance_km(self, d: date) -> float:
        v = await self._daily_rollup_value("distance", d, "meterSum")  # ASSUMED key + meters
        return round((v or 0) / 1000.0, 3)

    async def get_weight_log(self, d: date) -> list[dict]:
        """Return [{"date": "YYYY-MM-DD", "weight_kg": float}] for civil day d."""
        nxt = d + timedelta(days=1)
        flt = (
            f'weight.sample_time.civil_time >= "{d.isoformat()}T00:00:00" '
            f'AND weight.sample_time.civil_time < "{nxt.isoformat()}T00:00:00"'
        )
        url = f"{BASE}/users/me/dataTypes/weight/dataPoints"
        out: list[dict] = []
        page_token = None
        while True:
            params = {"filter": flt, "pageSize": 1000}
            if page_token:
                params["pageToken"] = page_token
            r = await self._request("GET", url, params=params)
            body = r.json()
            for dp in body.get("dataPoints", []):
                w = dp.get("weight", {})
                grams = w.get("weightGrams")
                if grams is None:
                    continue
                civ = (w.get("sampleTime", {}).get("civilTime", {}) or {}).get("date", {})
                if civ:
                    local = date(civ["year"], civ["month"], civ["day"]).isoformat()
                else:
                    local = d.isoformat()
                out.append({"date": local, "weight_kg": round(grams / 1000.0, 2)})
            page_token = body.get("nextPageToken")
            if not page_token:
                break
        return out
```

- [ ] **Step 3.4: Run `tests/test_google_health_client.py` — expect PASS.**

- [ ] **Step 3.5: Rewrite `cli_helpers.py` sync loop:**

Change the import and env vars, and replace the per-day extraction. Key diffs:

```python
from diet.google_health_client import GoogleHealthClient   # was: from diet.fitbit_client import FitbitClient
```

In `run_sync_async`, `refresh()` reads `GOOGLE_*` and carries the user_id forward:

```python
    async def refresh():
        try:
            new_tok = await refresh_access_token(
                os.environ["GOOGLE_CLIENT_ID"],
                os.environ["GOOGLE_CLIENT_SECRET"],
                tok.refresh_token,
                user_id=tok.user_id,
            )
        except httpx.HTTPStatusError as e:
            if _is_invalid_grant(e):
                raise RefreshTokenError(str(e)) from e
            raise TransientRefreshError(str(e)) from e
        except httpx.RequestError as e:
            raise TransientRefreshError(str(e)) from e
        save_token_atomic(conn, new_tok)
        return new_tok.access_token
```

Replace the client construction + per-day body:

```python
    client = GoogleHealthClient(access_token=tok.access_token, on_unauthorized=refresh)
    for offset in range(days):
        d = today - timedelta(days=offset)
        try:
            steps = await client.get_daily_steps(d)
            active_energy = await client.get_daily_active_energy_kcal(d)
            total_calories = await client.get_daily_total_calories_kcal(d)
            distance_km = await client.get_daily_distance_km(d)
            upsert_daily_activity(
                conn, d,
                steps=steps,
                distance_km=distance_km,
                total_calories_kcal=total_calories,
                active_energy_kcal=active_energy,
            )
            weights = await client.get_weight_log(d)
            for w in weights:
                upsert_daily_weight(conn, date.fromisoformat(w["date"]), float(w["weight_kg"]))
        except (RefreshTokenError, TransientRefreshError):
            raise
        except Exception as e:
            print(f"sync warning ({d}): {e}", flush=True)
            continue
```

`_is_invalid_grant` is unchanged (Google returns `{"error":"invalid_grant"}` at 400, already handled; the `errors[]` branch is dead but harmless).

- [ ] **Step 3.6: Update `cli.py` `sync` docstring/wording** ("Fitbit" → "Google Health"); the transient-error Japanese message "Fitbit 側の一時的な障害" → "Google Health 側の一時的な障害". No logic change.

- [ ] **Step 3.7: Update `tests/test_cli_sync.py`** — `_seed_token` is fine (`Token` unchanged). These tests mock `run_sync_async` directly (no real HTTP), so only env renames if any (none here). Run to confirm.

- [ ] **Step 3.8: Update `tests/test_edgecases.py` 429 + real-refresh tests:**

- `test_429_reset_seconds_in_state`: replace with a 429-raises test against the new client:

```python
async def test_429_raises_resource_exhausted(httpx_mock):
    import httpx
    from diet.google_health_client import GoogleHealthClient, BASE
    httpx_mock.add_response(
        url=f"{BASE}/users/me/dataTypes/steps/dataPoints:dailyRollUp", method="POST",
        status_code=429, json={"error": {"status": "RESOURCE_EXHAUSTED"}},
    )
    client = GoogleHealthClient(access_token="A")
    with pytest.raises(httpx.HTTPStatusError):
        await client.get_daily_steps(date(2026, 5, 25))
```

- `test_cli_sync_with_real_refresh_failure_directs_to_auth` / `..._transient_...` / `..._network_...`: change the first per-day call mock from the Fitbit activity URL to the steps rollup URL `re.compile(r".*/users/me/dataTypes/steps/dataPoints:dailyRollUp")` with `method="POST"`, and the token-endpoint mock URL `https://api.fitbit.com/oauth2/token` → `https://oauth2.googleapis.com/token`. The invalid_grant body `{"errors":[{"errorType":"invalid_grant"}]}` → `{"error":"invalid_grant"}` (Google shape); the 503/transient body can stay any JSON. Restore any skips added in Task 2.
- `test_refresh_failure_with_revoked_token_propagates`: token URL → Google; body → `{"error":"invalid_grant"}`.

- [ ] **Step 3.9: Run full suite — expect PASS.**

- [ ] **Step 3.10: Commit.**

```bash
git add -A
git commit -m "feat(client): replace FitbitClient with GoogleHealthClient + rewrite sync loop"
```

---

## Task 4: calibrate → informational display + config/.env/cosmetics

**Files:**
- Modify: `src/diet/calibrate.py`
- Modify: `src/diet/cli.py` (init guidance message; `calibrate` docstring)
- Create: `.env.example`
- Modify: `pyproject.toml` (optional: drop `cryptography` dependency — now unused)
- Test: `tests/test_cli_calibrate.py` (rewrite)

- [ ] **Step 4.1: Rewrite `tests/test_cli_calibrate.py`** to assert display-only (no prompt, no config write):

```python
from datetime import date, timedelta

from click.testing import CliRunner

from diet.cli import app
from diet.db import Config, open_db, save_config, upsert_daily_activity


def _seed_config(db_path):
    conn = open_db(db_path)
    save_config(conn, Config(
        birthday=date(1979, 12, 1), height_cm=169, sex="male", timezone="Asia/Tokyo",
        hpasaneel_path=None, hpasaneel_diet_root="content/diet",
        exercise_calorie_source=None, bootstrap_daily_kcal=2000,
    ))
    return conn


def test_calibrate_displays_recent_activity(tmp_path, monkeypatch):
    monkeypatch.setenv("DIET_DATA_DIR", str(tmp_path))
    conn = _seed_config(tmp_path / "diet.db")
    today = date.today()
    for offset in range(3):
        d = today - timedelta(days=offset)
        upsert_daily_activity(conn, d, steps=5000 + offset * 100, distance_km=3.5,
                              total_calories_kcal=1800 + offset, active_energy_kcal=300 + offset)
    runner = CliRunner()
    result = runner.invoke(app, ["calibrate", "--days", "5"])
    assert result.exit_code == 0, result.output
    assert "active_energy" in result.output
    assert "total_calories" in result.output
```

- [ ] **Step 4.2: Run — expect FAIL.**

- [ ] **Step 4.3: Rewrite `src/diet/calibrate.py`:**

```python
from datetime import date, timedelta

import click

from diet.db import get_daily_activity, load_config, open_db


def run_calibrate(data_dir, days: int = 14) -> None:
    conn = open_db(data_dir / "diet.db")
    cfg = load_config(conn)
    if cfg is None:
        raise click.ClickException("config が未初期化です。先に `diet init` を実行してください。")
    today = date.today()
    click.echo(f"過去 {days} 日の活動カロリー（参考表示）:")
    click.echo(f"{'date':<12} {'steps':>8} {'distance_km':>12} {'active_energy':>14} {'total_calories':>15}")
    for offset in range(days):
        d = today - timedelta(days=offset)
        a = get_daily_activity(conn, d)
        if a is None:
            continue
        click.echo(
            f"{d.isoformat():<12} {a.steps:>8,} {a.distance_km:>12.1f} "
            f"{(a.active_energy_kcal or 0):>14,} {(a.total_calories_kcal or 0):>15,}"
        )
    click.echo("\n運動カロリーは active_energy（基礎代謝を除いた活動由来の消費）を使用します。")
    click.echo("total_calories（基礎代謝を含む総消費）は参考値で、収支計算には使いません。")
```

> `exercise_calorie_source` config column is now vestigial (kept for backward compatibility, unused). Do not write it here.

- [ ] **Step 4.4: Update `cli.py`:** init success message `"…`diet calibrate` で exercise_calorie_source を決めてください。"` → `"初期 sync 完了。`diet calibrate` で直近の活動カロリーを確認できます。"`; `calibrate` command docstring → `"Show recent activity-calorie figures (informational)."`.

- [ ] **Step 4.5: Overwrite `.env.example`** (the file already exists with `FITBIT_*` keys — replace its contents; ASCII only, LF is fine for `.env`):

```
# Google Cloud OAuth client credentials (from Google Cloud Console)
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-client-secret
# Loopback redirect registered on the OAuth client (Web application type)
GOOGLE_REDIRECT_URI=http://localhost:8765/callback
```

- [ ] **Step 4.6: (Optional) Drop `cryptography`** from `pyproject.toml` dependencies (now unused). If removed, run `py -m uv lock` / `py -m uv sync`. Skip if it risks other breakage; leaving it is harmless.

- [ ] **Step 4.7: Run full suite — expect PASS.**

- [ ] **Step 4.8: Commit.**

```bash
git add -A
git commit -m "feat(calibrate): informational display only + GOOGLE_* env (.env.example)"
```

---

## Task 5: Spec rev 10 + README

**Files:**
- Modify: `docs/superpowers/specs/2026-05-25-fitbit-diet-design.md`
- Modify: `README.md`

- [ ] **Step 5.1: Add a "Rev 10 — Google Health API migration" amendment** at the top of the spec capturing the 5 decisions + the confirmed API contract + the ASSUMED-field list. Rewrite the Fitbit-specific sections:
  - §4 data flow: Fitbit Web API → Google Health API; exercise calorie = `active-energy-burned` (BMR-free); `total-calories` diagnostic-only; note Renpho→Fitbit→Google Health weight path needs live verification.
  - §6 schema: `daily_activity` columns now `active_energy_kcal` / `total_calories_kcal`; v1→v2 migration; `user_id` populated from identity; token non-transferable.
  - §8 registration: replace dev.fitbit.com with GCP Console (create project, enable Google Health API, OAuth consent screen → **Production**, add test user `pcjidouka@gmail.com`, create **Web application** OAuth client, register `http://localhost:8765/callback`).
  - §9/§11: `google_health_client.py` responsibilities, `dailyRollUp` model, 429 backoff (no rate-limit headers).

- [ ] **Step 5.2: Rewrite `README.md`** setup/auth sections:
  - GCP Console steps (above). `.env` keys `GOOGLE_*`.
  - `diet init`/`diet auth`: browser opens, authorize with Google — no cert warning step.
  - `diet calibrate`: now informational.
  - One-time migration note: existing Fitbit tokens are discarded; re-run `diet auth` (re-consent).

- [ ] **Step 5.3: Commit (docs — no codex review needed).**

```bash
git add -A
git commit -m "docs: spec rev 10 + README for Google Health API migration"
```

---

## Task 6: Full-suite verification + live-E2E checklist

**Files:**
- Create: `docs/superpowers/plans/2026-06-01-google-health-api-e2e-checklist.md`

- [ ] **Step 6.1: Run the full suite and capture the count.**

Run: `py -m uv run pytest -q`
Expected: all tests pass (was 159; net count changes — cert tests removed (~5), client/oauth tests reshaped). Record the new number.

- [ ] **Step 6.2: Grep for stragglers** — there must be zero references to Fitbit-era identifiers in `src/`:

Run: `py -m uv run python -c "import diet.cli, diet.oauth, diet.google_health_client, diet.cli_helpers, diet.calibrate, diet.publish, diet.orchestrator"`
Grep `src/` for `fitbit_client`, `FitbitClient`, `marginal_kcal`, `logged_activities_kcal`, `marginalCalories`, `FITBIT_CLIENT`, `api.fitbit.com`, `www.fitbit.com`, `generate_self_signed_cert`, `oauth_cert.pem` — all should be gone (only docs/comments may mention Fitbit historically).

- [ ] **Step 6.3: Write the live-E2E checklist** documenting what only a real Google account can verify (the ASSUMED fields). Contents:
  1. GCP setup done (project, API enabled, consent screen **Production**, test user added, Web OAuth client, redirect `http://localhost:8765/callback`, `.env` filled).
  2. `py -m uv run diet auth` → browser authorizes → token saved (verify `diet auth` completes, no cert prompt).
  3. `py -m uv run diet sync --days 3` → inspect `data/diet.db`: `daily_activity.steps/active_energy_kcal/distance_km` populated, `daily_weight.weight_kg` sane (NOT 1000×, confirming grams→kg).
  4. **Verify ASSUMED fields against real responses** (the only real risk): distance `meterSum`, total-calories `kcalSum`, identity `healthUserId`, weight filter `weight.sample_time.civil_time`, `value.countSum` nesting. If any differs, fix the single adapter line + its unit test.
  5. Confirm Renpho weight actually appears in Google Health for the account.
  6. `py -m uv run diet` end-to-end → publish to HPasaneel; verify dashboard shows steps/distance/exercise/weight.

- [ ] **Step 6.4: Commit the checklist.**

```bash
git add -A
git commit -m "docs: live E2E verification checklist for Google Health migration"
```

- [ ] **Step 6.5: Codex review of the code commits** (per global rule, after the code-bearing commits): `codex review --commit <SHA>` for Tasks 1–4 HEADs (or the squashed range). Address P1/P2 before any merge.

---

## Out of scope / deferred

- **Live API verification** (Task 6 checklist) — requires the user's GCP project + credentials; cannot be done in this implementation session. Both codex and the migration synthesis agreed: implement against documented shapes now, verify live before declaring the migration complete.
- **PR / merge to `main`** — after live E2E passes.
- **Intraday / batching optimizations** — per-day rollups (≈5 requests/day) are well under the 300 req/min per-user limit for a 30-day initial sync; YAGNI.
