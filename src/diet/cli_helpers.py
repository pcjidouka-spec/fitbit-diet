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
                total_calories_kcal=logged,
                active_energy_kcal=marginal,
            )
            weights = await client.get_weight_log(d.isoformat())
            for w in weights:
                upsert_daily_weight(
                    conn, date.fromisoformat(w["date"]), float(w["weight"])
                )
        except (RefreshTokenError, TransientRefreshError):
            # Auth-layer failures must escape so the CLI can route the user
            # appropriately (``diet auth`` vs transient retry). Per-day API
            # failures (a single bad 4xx/5xx from get_activity_summary or
            # get_weight_log) still fall through to the generic warning so
            # one bad day doesn't abort the whole 7-day sync.
            raise
        except Exception as e:
            print(f"sync warning ({d}): {e}", flush=True)
            continue
