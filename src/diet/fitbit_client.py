from dataclasses import dataclass
import httpx


@dataclass
class RateLimitState:
    limit: int | None = None
    remaining: int | None = None
    reset_seconds: int | None = None


class FitbitClient:
    BASE = "https://api.fitbit.com"

    def __init__(self, access_token: str, on_unauthorized=None):
        self.access_token = access_token
        self.rate_limit = RateLimitState()
        self.on_unauthorized = on_unauthorized

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}

    def _update_rate_limit(self, headers) -> None:
        if "Fitbit-Rate-Limit-Limit" in headers:
            self.rate_limit.limit = int(headers["Fitbit-Rate-Limit-Limit"])
        if "Fitbit-Rate-Limit-Remaining" in headers:
            self.rate_limit.remaining = int(headers["Fitbit-Rate-Limit-Remaining"])
        if "Fitbit-Rate-Limit-Reset" in headers:
            self.rate_limit.reset_seconds = int(headers["Fitbit-Rate-Limit-Reset"])

    async def _request(self, method: str, url: str) -> httpx.Response:
        async with httpx.AsyncClient() as client:
            r = await client.request(method, url, headers=self._headers(), timeout=30.0)
            self._update_rate_limit(r.headers)
            if r.status_code == 401 and self.on_unauthorized:
                # single retry only
                self.access_token = await self.on_unauthorized()
                async with httpx.AsyncClient() as client2:
                    r = await client2.request(method, url, headers=self._headers(), timeout=30.0)
                    self._update_rate_limit(r.headers)
            r.raise_for_status()
            return r

    async def get_activity_summary(self, date_str: str) -> dict:
        r = await self._request("GET", f"{self.BASE}/1/user/-/activities/date/{date_str}.json")
        return r.json()

    async def get_weight_log(self, date_str: str) -> list[dict]:
        r = await self._request("GET", f"{self.BASE}/1/user/-/body/log/weight/date/{date_str}.json")
        return r.json().get("weight", [])
