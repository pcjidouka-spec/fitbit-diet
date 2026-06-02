"""FastAPI app. Loopback-only local web UI (spec SS2)."""
import secrets
from datetime import date as _date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from diet.db import load_config, open_db
from diet.web import service
from diet.web.security import LocalhostSecurityMiddleware

_HERE = Path(__file__).parent
_TEMPLATE = (_HERE / "templates" / "index.html").read_text(encoding="utf-8")


def create_app(data_dir: Path, port: int) -> FastAPI:
    # Constrain to a usable, non-privileged TCP port. Privileged ports (80/443)
    # are rejected because browsers omit the port from Host/Origin for
    # scheme-default ports, which the security predicates reject; ports above
    # 65535 can't be bound by uvicorn. This is a loopback dev tool, so a high
    # port is always fine.
    if not 1024 <= port <= 65535:
        raise ValueError(f"port must be in 1024..65535 (got {port})")

    csrf_token = secrets.token_urlsafe(32)
    app = FastAPI()
    app.add_middleware(LocalhostSecurityMiddleware, port=port, csrf_token=csrf_token)
    app.mount("/static", StaticFiles(directory=_HERE / "static"), name="static")

    db_path = data_dir / "diet.db"

    def _conn():
        return open_db(db_path)

    def _today(cfg) -> _date:
        return datetime.now(ZoneInfo(cfg.timezone)).date()

    def _target(cfg, day: _date | None) -> _date:
        # ``day`` is already validated by FastAPI (typed ``date``); a malformed
        # value yields a native 422 before reaching here, never an uncaught 500.
        return day if day is not None else _today(cfg)

    @app.get("/", response_class=HTMLResponse)
    def index():
        return HTMLResponse(_TEMPLATE.replace("{csrf_token}", csrf_token))

    @app.get("/api/day")
    def api_day(date: _date | None = Query(default=None)):
        conn = _conn()
        cfg = load_config(conn)
        if cfg is None:
            return JSONResponse({"code": "no_config", "detail": "run `diet init`"}, status_code=409)
        return service.get_day_dto(conn, cfg, _target(cfg, date))

    @app.get("/api/history")
    def api_history(days: int = Query(default=14, ge=1, le=90),
                    date: _date | None = Query(default=None)):
        conn = _conn()
        cfg = load_config(conn)
        if cfg is None:
            return JSONResponse({"code": "no_config", "detail": "run `diet init`"}, status_code=409)
        return service.get_history_dto(conn, cfg, _target(cfg, date), days=days)

    @app.get("/api/auth/status")
    def api_auth_status():
        return service.auth_status(_conn())

    return app
