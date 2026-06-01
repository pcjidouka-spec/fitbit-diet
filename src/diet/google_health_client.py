from datetime import date, datetime, timedelta

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
                # Deterministic recency key: parse physicalTime, fall back to
                # min datetime when missing/unparseable so it never wins.
                phys = sample_time.get("physicalTime")
                try:
                    sort_key = datetime.fromisoformat(phys) if phys else datetime.min
                except ValueError:
                    sort_key = datetime.min
                weight_kg = round(grams / 1000.0, 2)
                prev = newest.get(local)
                if prev is None or sort_key > prev[0]:
                    newest[local] = (sort_key, weight_kg)
            page_token = body.get("nextPageToken")
            if not page_token:
                break
        return [{"date": k, "weight_kg": v[1]} for k, v in newest.items()]
