import os
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
from diet.fitbit_client import FitbitClient
from diet.oauth import refresh_access_token


class RefreshTokenError(Exception):
    """Raised when the OAuth refresh-token itself is invalid (revoked).

    ONLY raised for ``invalid_grant`` (and look-alikes that indicate a dead
    refresh token). Transient HTTP failures from the token endpoint —
    5xx outages, 429 rate limits, ``invalid_client`` credentials errors —
    are re-raised as the original ``httpx.HTTPStatusError`` so the CLI can
    distinguish "re-auth will fix this" from "wait and retry".
    """


def _is_invalid_grant(exc: httpx.HTTPStatusError) -> bool:
    """Return True when the token endpoint response indicates a dead refresh
    token (``invalid_grant``). Anything else (5xx, 429, ``invalid_client``,
    network errors with no parseable body) returns False so the caller can
    re-raise as a non-auth failure.

    Fitbit returns errors in two shapes:
      ``{"errors": [{"errorType": "invalid_grant", ...}]}``
      ``{"error": "invalid_grant", ...}``  (OAuth2 RFC 6749)
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


async def run_sync_async(conn, days: int):
    cfg = load_config(conn)
    tok = load_token(conn)
    if tok is None:
        raise RuntimeError("Not authenticated. Run `diet init` first.")
    tz = ZoneInfo(cfg.timezone)
    today = datetime.now(tz).date()

    async def refresh():
        try:
            new_tok = await refresh_access_token(
                os.environ["FITBIT_CLIENT_ID"],
                os.environ["FITBIT_CLIENT_SECRET"],
                tok.refresh_token,
            )
        except httpx.HTTPStatusError as e:
            # Only ``invalid_grant`` indicates a permanently dead refresh
            # token that the user can fix by re-running ``diet auth``. Other
            # token-endpoint failures (5xx outages, 429 rate limits,
            # ``invalid_client`` credential errors) should propagate as the
            # original HTTPStatusError so the CLI handler can surface a
            # different message ("transient — try later") instead of falsely
            # telling the user to re-auth.
            if _is_invalid_grant(e):
                raise RefreshTokenError(str(e)) from e
            raise
        save_token_atomic(conn, new_tok)
        return new_tok.access_token

    client = FitbitClient(access_token=tok.access_token, on_unauthorized=refresh)
    for offset in range(days):
        d = today - timedelta(days=offset)
        try:
            act = await client.get_activity_summary(d.isoformat())
            summary = act["summary"]
            distance_km = next(
                (
                    x["distance"]
                    for x in summary.get("distances", [])
                    if x["activity"] == "total"
                ),
                0.0,
            )
            logged = sum(a.get("calories", 0) for a in act.get("activities", []))
            marginal = summary.get("marginalCalories", 0)
            upsert_daily_activity(
                conn,
                d,
                steps=summary.get("steps", 0),
                distance_km=distance_km,
                logged_activities_kcal=logged,
                marginal_kcal=marginal,
            )
            weights = await client.get_weight_log(d.isoformat())
            for w in weights:
                upsert_daily_weight(
                    conn, date.fromisoformat(w["date"]), float(w["weight"])
                )
        except RefreshTokenError:
            # Auth layer failure — propagate so the CLI can route the user to
            # ``diet auth``. Per-day API failures (e.g. transient 500s) keep
            # falling through to the generic warning below.
            raise
        except Exception as e:
            print(f"sync warning ({d}): {e}", flush=True)
            continue
