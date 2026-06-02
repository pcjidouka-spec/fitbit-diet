"""FastAPI app. Loopback-only local web UI (spec SS2)."""
import secrets
from contextlib import closing
from datetime import date as _date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from diet.db import load_config, load_token, open_db
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
        with closing(_conn()) as conn:
            cfg = load_config(conn)
            if cfg is None:
                return JSONResponse({"code": "no_config", "detail": "run `diet init`"}, status_code=409)
            return service.get_day_dto(conn, cfg, _target(cfg, date))

    @app.get("/api/history")
    def api_history(days: int = Query(default=14, ge=1, le=90),
                    date: _date | None = Query(default=None)):
        with closing(_conn()) as conn:
            cfg = load_config(conn)
            if cfg is None:
                return JSONResponse({"code": "no_config", "detail": "run `diet init`"}, status_code=409)
            return service.get_history_dto(conn, cfg, _target(cfg, date), days=days)

    @app.get("/api/auth/status")
    def api_auth_status():
        with closing(_conn()) as conn:
            return service.auth_status(conn)

    # ------------------------------------------------------------------
    # Pydantic request bodies
    # ------------------------------------------------------------------

    class IntakeBody(BaseModel):
        raw: str
        date: _date | None = None

    class WeightBody(BaseModel):
        kg: float
        date: _date | None = None

    class SyncBody(BaseModel):
        days: int = Field(default=7, ge=1, le=90)

    class PublishBody(BaseModel):
        date: _date | None = None

    # ------------------------------------------------------------------
    # POST endpoints
    # ------------------------------------------------------------------

    @app.post("/api/intake")
    def api_intake(body: IntakeBody):
        with closing(_conn()) as conn:
            cfg = load_config(conn)
            if cfg is None:
                return JSONResponse({"code": "no_config", "detail": "run `diet init`"}, status_code=409)
            try:
                service.apply_intake(conn, _target(cfg, body.date), body.raw)
            except ValueError as e:
                return JSONResponse({"code": "bad_intake", "detail": str(e)}, status_code=400)
        return {"ok": True}

    @app.post("/api/weight")
    def api_weight(body: WeightBody):
        with closing(_conn()) as conn:
            cfg = load_config(conn)
            if cfg is None:
                return JSONResponse({"code": "no_config", "detail": "run `diet init`"}, status_code=409)
            try:
                service.record_weight(conn, _target(cfg, body.date), body.kg)
            except ValueError as e:
                return JSONResponse({"code": "bad_weight", "detail": str(e)}, status_code=400)
        return {"ok": True}

    @app.post("/api/sync")
    def api_sync(body: SyncBody):
        with closing(_conn()) as conn:
            cfg = load_config(conn)
            if cfg is None:
                return JSONResponse({"code": "no_config", "detail": "run `diet init`"}, status_code=409)
            if load_token(conn) is None:
                # Missing token (e.g. after v1→v2 migration wiped the Fitbit token).
                # Same actionable signal as a revoked token: re-auth via the CLI.
                return JSONResponse(
                    {"ok": False, "code": "reauth_required",
                     "detail": "未認証です。CLI で `diet auth` を実行してください。"},
                    status_code=401,
                )
            from diet.cli_helpers import RefreshTokenError
            try:
                outcome = service.run_sync(conn, days=body.days)
            except RefreshTokenError as e:
                # Refresh token revoked — only `diet auth` (CLI) fixes it.
                # /api/auth/status checks token *presence* and can't detect this,
                # so emit a stable reauth signal the UI can act on.
                return JSONResponse(
                    {"ok": False, "code": "reauth_required",
                     "detail": f"{e}\n  CLI で `diet auth` を実行して再認証してください。"},
                    status_code=401,
                )
            except Exception as e:  # noqa: BLE001 — transient/total failure
                return JSONResponse(
                    {"ok": False, "code": "sync_failed", "warning": str(e)},
                    status_code=502,
                )
            # run_sync_async swallows per-day API failures into warnings so one
            # bad day doesn't abort the window. Only a sync that wrote NO activity
            # at all (synced == 0) is a true failure — a day whose weight fetch
            # failed after its activity landed still counts as synced.
            if outcome.synced == 0 and outcome.warnings:
                return JSONResponse(
                    {"ok": False, "code": "sync_all_days_failed", "warnings": outcome.warnings},
                    status_code=502,
                )
        return {"ok": True, "synced": outcome.synced, "warnings": outcome.warnings}

    @app.post("/api/publish")
    def api_publish(body: PublishBody):
        import subprocess

        import jsonschema
        with closing(_conn()) as conn:
            cfg = load_config(conn)
            if cfg is None:
                return JSONResponse({"code": "no_config", "detail": "run `diet init`"}, status_code=409)
            target = _target(cfg, body.date)
            # Generic recovery hint: a failed git step (push/pull/commit) is most
            # often a remote divergence, but may also be auth/network. Advise the
            # rebase-retry first, then manual resolution — without asserting it is
            # definitely a conflict.
            hint = (f"`cd {cfg.hpasaneel_path or '(未設定)'} && "
                    "git pull --rebase && git push` "
                    "で解決を試み、解決しなければ手動で対応してください")
            try:
                service.run_publish(conn, cfg, target)
            except subprocess.CalledProcessError as e:
                return JSONResponse({"code": "publish_git_failed", "detail": f"{e}\n  {hint}"}, status_code=409)
            except service.PublishNoData as e:
                return JSONResponse({"code": "publish_no_data", "detail": str(e)}, status_code=409)
            except service.PublishBlocked as e:
                return JSONResponse({"code": "publish_blocked", "detail": str(e)}, status_code=409)
            except service.PublishUnconfigured as e:
                return JSONResponse({"code": "publish_unconfigured", "detail": str(e)}, status_code=409)
            except jsonschema.ValidationError as e:
                # Existing log.json is valid JSON but violates the public schema
                # (extra field / wrong type). Recoverable → 409, not a 500.
                return JSONResponse({"code": "publish_invalid", "detail": f"{e.message}\n  {hint}"}, status_code=409)
            except ValueError as e:
                # Unexpected pre-flight ValueError (e.g. malformed existing log.json).
                return JSONResponse({"code": "publish_invalid", "detail": f"{e}\n  {hint}"}, status_code=409)
            except Exception as e:  # noqa: BLE001
                return JSONResponse({"code": "publish_failed", "detail": f"{e}\n  {hint}"}, status_code=500)
        return {"ok": True}

    return app
