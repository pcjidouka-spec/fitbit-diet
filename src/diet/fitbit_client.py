from dataclasses import dataclass
import httpx


@dataclass
class RateLimitState:
    limit: int | None = None
    remaining: int | None = None
    reset_seconds: int | None = None


class FitbitClient:
    BASE = "https://api.fitbit.com"

    def __init__(self, access_token: str):
        self.access_token = access_token
        self.rate_limit = RateLimitState()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}

    def _update_rate_limit(self, headers) -> None:
        if "Fitbit-Rate-Limit-Limit" in headers:
            self.rate_limit.limit = int(headers["Fitbit-Rate-Limit-Limit"])
        if "Fitbit-Rate-Limit-Remaining" in headers:
            self.rate_limit.remaining = int(headers["Fitbit-Rate-Limit-Remaining"])
        if "Fitbit-Rate-Limit-Reset" in headers:
            self.rate_limit.reset_seconds = int(headers["Fitbit-Rate-Limit-Reset"])

    async def get_activity_summary(self, date_str: str) -> dict:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{self.BASE}/1/user/-/activities/date/{date_str}.json",
                headers=self._headers(), timeout=30.0,
            )
            self._update_rate_limit(r.headers)
            r.raise_for_status()
            return r.json()

    async def get_weight_log(self, date_str: str) -> list[dict]:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{self.BASE}/1/user/-/body/log/weight/date/{date_str}.json",
                headers=self._headers(), timeout=30.0,
            )
            self._update_rate_limit(r.headers)
            r.raise_for_status()
            return r.json().get("weight", [])
