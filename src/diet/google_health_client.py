from datetime import date, datetime, timedelta, timezone

import httpx

BASE = "https://health.googleapis.com/v4"

# Recency key for samples missing/unparseable physicalTime. Aware (UTC) so it
# never collides with parsed aware timestamps; minimal so it never wins.
EPOCH = datetime.min.replace(tzinfo=timezone.utc)


class GoogleHealthClient:
    """Adapter over the Google Health API v4 data endpoints.

    All HTTP + JSON-shape knowledge lives here so callers see plain numbers.

    ALL CONFIRMED live (2026-06-04): weight weightGrams (→/1000 kg), weight
    filter field weight.sample_time.civil_time, identity healthUserId/
    legacyUserId, and every rollup, nested as rollupDataPoints[0].<camelCaseType>
    .<metric> (NOT a generic `value` key):
      - steps → steps.countSum            (int64 as STRING, e.g. "17663")
      - active-energy-burned → activeEnergyBurned.kcalSum   (double)
      - total-calories → totalCalories.kcalSum              (double)
      - distance → distance.millimetersSum (int64 as STRING, MILLIMETRES → /1e6 km)
    Note int64 sums arrive as JSON strings, doubles as numbers; callers coerce.
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

    async def _daily_rollup_value(self, data_type: str, d: date, wrapper_key: str, value_key: str):
        """Read a single daily rollup metric.

        ★ Live E2E (2026-06-04): the rollup value is NOT under a generic
        ``value`` key. Each point nests the metric under a data-type-specific
        camelCase wrapper, e.g. total-calories → ``{"totalCalories": {"kcalSum": ...}}``
        (CONFIRMED against the real API). The other three wrapper keys are the
        camelCase form of their data type (steps / activeEnergyBurned / distance);
        this account has no step/activity data so they could not be confirmed
        live, but they follow the same pattern as the confirmed total-calories.
        """
        url = f"{BASE}/users/me/dataTypes/{data_type}/dataPoints:dailyRollUp"
        r = await self._request("POST", url, json=self._civil_day_body(d))
        points = r.json().get("rollupDataPoints", [])
        if not points:
            return None
        return points[0].get(wrapper_key, {}).get(value_key)

    async def get_daily_steps(self, d: date) -> int:
        v = await self._daily_rollup_value("steps", d, "steps", "countSum")
        return int(v or 0)

    async def get_daily_active_energy_kcal(self, d: date) -> int:
        v = await self._daily_rollup_value("active-energy-burned", d, "activeEnergyBurned", "kcalSum")
        return round(v) if v is not None else 0

    async def get_daily_total_calories_kcal(self, d: date) -> int:
        # CONFIRMED live 2026-06-04: rollupDataPoints[0].totalCalories.kcalSum
        v = await self._daily_rollup_value("total-calories", d, "totalCalories", "kcalSum")
        return round(v) if v is not None else 0

    async def get_daily_distance_km(self, d: date) -> float:
        # CONFIRMED live 2026-06-04: distance.millimetersSum (millimetres, and the
        # int64 sum arrives as a STRING). 12078318 mm = 12.078 km. (The earlier
        # ASSUMED meterSum/metres was wrong on both key and unit.)
        v = await self._daily_rollup_value("distance", d, "distance", "millimetersSum")
        return round(float(v or 0) / 1_000_000.0, 3)

    async def get_weight_log(self, d: date) -> list[dict]:
        """Return [{"date": "YYYY-MM-DD", "weight_kg": float}] for civil day d."""
        nxt = d + timedelta(days=1)
        flt = (
            f'weight.sample_time.civil_time >= "{d.isoformat()}T00:00:00" '
            f'AND weight.sample_time.civil_time < "{nxt.isoformat()}T00:00:00"'
        )
        url = f"{BASE}/users/me/dataTypes/weight/dataPoints"
        # Accumulate across pages, then reduce to the newest sample per civil
        # date. A day can have multiple measurements; keep the one with the
        # latest physicalTime so the value fed downstream (e.g. BMR) is current.
        newest: dict[str, tuple] = {}  # local_date -> (sort_key, weight_kg)
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
                sample_time = w.get("sampleTime", {}) or {}
                civ = (sample_time.get("civilTime", {}) or {}).get("date", {})
                if civ:
                    local = date(civ["year"], civ["month"], civ["day"]).isoformat()
                else:
                    local = d.isoformat()
                # Deterministic recency key, always tz-aware (normalised to
                # UTC) so naive and aware timestamps never collide in `>`.
                # physicalTime may be absent or RFC3339 without an offset.
                phys = sample_time.get("physicalTime")
                try:
                    parsed = datetime.fromisoformat(phys) if phys else None
                except ValueError:
                    parsed = None
                if parsed is None:
                    sort_key = EPOCH
                elif parsed.tzinfo is None:
                    sort_key = parsed.replace(tzinfo=timezone.utc)
                else:
                    sort_key = parsed
                weight_kg = round(grams / 1000.0, 2)
                prev = newest.get(local)
                if prev is None or sort_key > prev[0]:
                    newest[local] = (sort_key, weight_kg)
            page_token = body.get("nextPageToken")
            if not page_token:
                break
        return [{"date": k, "weight_kg": v[1]} for k, v in newest.items()]
