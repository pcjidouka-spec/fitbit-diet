import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from diet.db import (
    load_config,
    load_token,
    save_token_atomic,
    upsert_daily_activity,
    upsert_daily_weight,
)
from diet.fitbit_client import FitbitClient
from diet.oauth import refresh_access_token


async def run_sync_async(conn, days: int):
    cfg = load_config(conn)
    tok = load_token(conn)
    if tok is None:
        raise RuntimeError("Not authenticated. Run `diet init` first.")
    tz = ZoneInfo(cfg.timezone)
    today = datetime.now(tz).date()

    async def refresh():
        new_tok = await refresh_access_token(
            os.environ["FITBIT_CLIENT_ID"],
            os.environ["FITBIT_CLIENT_SECRET"],
            tok.refresh_token,
        )
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
        except Exception as e:
            print(f"sync warning ({d}): {e}", flush=True)
            continue
