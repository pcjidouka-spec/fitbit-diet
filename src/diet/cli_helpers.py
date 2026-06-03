import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from diet.db import (
    load_config,
    load_token,
    save_token_atomic,
    upsert_daily_activity,
    upsert_daily_weight,
)
from diet.google_health_client import GoogleHealthClient
from diet.oauth import refresh_access_token


@dataclass(frozen=True)
class SyncOutcome:
    """Result of a sync run.

    ``synced`` = number of days whose activity row was written (a day where the
    weight fetch failed *after* the activity upsert still counts as synced).
    ``warnings`` = one string per day that hit a per-day API failure. The web
    layer reports a total failure only when ``synced == 0 and warnings``.
    """

    synced: int
    days: int
    warnings: list[str] = field(default_factory=list)


class RefreshTokenError(Exception):
    """Raised when the OAuth refresh-token itself is invalid (revoked).

    ONLY raised for ``invalid_grant`` (and look-alikes that indicate a dead
    refresh token). Transient HTTP failures from the token endpoint are
    raised as ``TransientRefreshError`` so the CLI can distinguish
    "re-auth will fix this" from "wait and retry", and so the per-day
    ``except Exception`` below does not swallow either auth failure as a
    routine warning.
    """


class TransientRefreshError(Exception):
    """Raised when the token-endpoint exchange failed transiently (5xx /
    429 / ``invalid_client``). Distinct from per-day API failures so the
    per-day ``except Exception`` does not swallow it — the user has no
    auth fix to apply, but the sync should still surface as failed."""


def _is_invalid_grant(exc: httpx.HTTPStatusError) -> bool:
    """Return True when the token endpoint response indicates a dead refresh
    token (``invalid_grant``). Anything else (5xx, 429, ``invalid_client``,
    network errors with no parseable body) returns False so the caller can
    re-raise as a non-auth failure.

    The token endpoint is now Google's OAuth2 endpoint, which returns the
    RFC-6749 shape on a dead/expired refresh token:
      ``{"error": "invalid_grant", ...}``  (status 400)
    The legacy ``{"errors": [{"errorType": "invalid_grant", ...}]}`` shape
    (Fitbit-era) is retained below as a harmless fallback — Google never
    emits it, but matching it costs nothing and guards old fixtures.
    """
    resp = exc.response
    if resp is None or resp.status_code != 400:
        return False
    try:
        body = resp.json()
    except Exception:  # noqa: BLE001 — body might not be JSON
        return False
    if body.get("error") == "invalid_grant":
        return True
    errors = body.get("errors") or []
    return any(
        isinstance(e, dict) and e.get("errorType") == "invalid_grant" for e in errors
    )


async def run_sync_async(conn, days: int) -> SyncOutcome:
    """Sync the last `days` days of activity + weight from Google Health.

    Returns a ``SyncOutcome`` (synced-day count + per-day warnings). Auth-layer
    failures (RefreshTokenError / TransientRefreshError) still raise so callers
    can route the user; per-day API failures are collected, not raised, so one
    bad day doesn't abort the whole window. The web layer inspects the outcome
    to tell the browser whether the sync was clean, partial, or a total failure.
    """
    cfg = load_config(conn)
    tok = load_token(conn)
    if tok is None:
        raise RuntimeError("Not authenticated. Run `diet init` first.")
    tz = ZoneInfo(cfg.timezone)
    today = datetime.now(tz).date()

    async def refresh():
        try:
            new_tok = await refresh_access_token(
                os.environ["GOOGLE_CLIENT_ID"],
                os.environ["GOOGLE_CLIENT_SECRET"],
                tok.refresh_token,
                # ★ Carry forward the real healthUserId resolved at auth time.
                # Omitting this defaults user_id to "me" and save_token_atomic
                # (DELETE+INSERT) would overwrite the stored user_id on the
                # first refresh.
                user_id=tok.user_id,
            )
        except httpx.HTTPStatusError as e:
            # Wrap so the per-day ``except Exception`` below does not swallow
            # the failure as a routine warning. Distinguish by error body:
            #   - ``invalid_grant`` → ``RefreshTokenError`` (user fixes via
            #     ``diet auth``)
            #   - anything else (5xx, 429, ``invalid_client``) →
            #     ``TransientRefreshError`` (user waits and retries)
            if _is_invalid_grant(e):
                raise RefreshTokenError(str(e)) from e
            raise TransientRefreshError(str(e)) from e
        except httpx.RequestError as e:
            # Network-level failure (timeout, DNS, connection refused). Has
            # no ``response`` so it cannot be ``invalid_grant``. Wrap as
            # transient so the per-day catch doesn't swallow it into a
            # misleading ``sync complete``.
            raise TransientRefreshError(str(e)) from e
        save_token_atomic(conn, new_tok)
        return new_tok.access_token

    client = GoogleHealthClient(access_token=tok.access_token, on_unauthorized=refresh)
    warnings: list[str] = []
    synced = 0  # days whose activity row was written (even if weight later failed)
    for offset in range(days):
        d = today - timedelta(days=offset)
        wrote_activity = False
        try:
            steps = await client.get_daily_steps(d)
            active_energy = await client.get_daily_active_energy_kcal(d)
            total_calories = await client.get_daily_total_calories_kcal(d)
            distance_km = await client.get_daily_distance_km(d)
            upsert_daily_activity(
                conn,
                d,
                steps=steps,
                distance_km=distance_km,
                total_calories_kcal=total_calories,
                active_energy_kcal=active_energy,
            )
            wrote_activity = True
            weights = await client.get_weight_log(d)
            for w in weights:
                upsert_daily_weight(
                    conn, date.fromisoformat(w["date"]), float(w["weight_kg"])
                )
        except (RefreshTokenError, TransientRefreshError):
            # Auth-layer failures must escape so the CLI can route the user
            # appropriately (``diet auth`` vs transient retry). Per-day API
            # failures (a single bad 4xx/5xx from a daily rollup or
            # get_weight_log call) still fall through to the generic warning
            # so one bad day doesn't abort the whole 7-day sync.
            raise
        except Exception as e:
            # A weight-fetch failure AFTER the activity upsert still counts as a
            # synced day (activity landed) — only ``wrote_activity`` decides that,
            # so the web layer never misreports a partial sync as a total failure.
            msg = f"sync warning ({d}): {e}"
            print(msg, flush=True)
            warnings.append(msg)
        if wrote_activity:
            synced += 1
    return SyncOutcome(synced=synced, days=days, warnings=warnings)
