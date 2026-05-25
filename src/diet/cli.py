import os
from pathlib import Path

import click
from dotenv import find_dotenv, load_dotenv

from diet.db import open_db, save_config, Config

# Load .env at CLI import time so FITBIT_CLIENT_ID / FITBIT_CLIENT_SECRET
# (and any other env-driven config) are available throughout the process.
# usecwd=True ensures we find the user's .env in the directory where they
# invoke `diet`, not the one next to cli.py in site-packages.
load_dotenv(find_dotenv(usecwd=True))


def _data_dir() -> Path:
    return Path(os.environ.get("DIET_DATA_DIR", "data"))


@click.group(invoke_without_command=True)
@click.option("--date", "date_str", default=None, type=str, help="YYYY-MM-DD")
@click.pass_context
def app(ctx: click.Context, date_str: str | None) -> None:
    """Personal diet tracking CLI."""
    if ctx.invoked_subcommand is None:
        # Task 6.8: default bare 'diet'
        from datetime import date as _date

        from diet.orchestrator import run_daily_flow

        target = _date.fromisoformat(date_str) if date_str else None
        run_daily_flow(data_dir=_data_dir(), target_date=target)


@app.command()
@click.option("--port", default=8765, type=int)
def init(port: int) -> None:
    """First-time setup."""
    data_dir = _data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    birthday = click.prompt(
        "生年月日 (YYYY-MM-DD)", type=click.DateTime(formats=["%Y-%m-%d"])
    )
    height = click.prompt("身長 (cm)", type=int)
    sex = click.prompt("性別 (male/female)", type=click.Choice(["male", "female"]))
    tz = click.prompt("タイムゾーン", default="Asia/Tokyo")
    hpath = click.prompt("HPasaneel リポジトリパス", default="C:/code/HPasaneel")
    droot = click.prompt("HPasaneel ダッシュボードルート", default="content/diet")
    bootstrap_in = click.prompt(
        "普段 1 日のカロリー目安 (不明なら Enter で skip)",
        default="",
        show_default=False,
    )
    bootstrap_val = int(bootstrap_in) if bootstrap_in.strip() else None
    cfg = Config(
        birthday=birthday.date(),
        height_cm=height,
        sex=sex,
        timezone=tz,
        hpasaneel_path=hpath,
        hpasaneel_diet_root=droot,
        exercise_calorie_source=None,
        bootstrap_daily_kcal=bootstrap_val,
    )
    conn = open_db(data_dir / "diet.db")
    save_config(conn, cfg)
    click.echo("config saved.")
    from diet.oauth import run_init_flow

    run_init_flow(data_dir=data_dir, port=port, conn=conn)
    _run_initial_sync(conn, days=30)
    click.echo(
        "初期 sync 完了。`diet calibrate` で exercise_calorie_source を決めてください。"
    )


def _run_initial_sync(conn, days: int) -> None:
    import asyncio

    from diet.cli_helpers import run_sync_async

    asyncio.run(run_sync_async(conn, days=days))


@app.command()
@click.option("--port", default=8765, type=click.IntRange(min=1, max=65535))
@click.option("--regen-cert", is_flag=True, help="証明書を再生成 (期限切れ時)")
def auth(port: int, regen_cert: bool) -> None:
    """Re-run OAuth (without re-prompting profile)."""
    from diet.db import load_config
    from diet.oauth import generate_self_signed_cert, run_init_flow

    data_dir = _data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    conn = open_db(data_dir / "diet.db")
    if load_config(conn) is None:
        raise click.ClickException(
            "config が未初期化です。先に `diet init` を実行してください。"
        )
    if regen_cert:
        cert = data_dir / "oauth_cert.pem"
        key = data_dir / "oauth_key.pem"
        cert.unlink(missing_ok=True)
        key.unlink(missing_ok=True)
        generate_self_signed_cert(cert, key, "localhost", days_valid=3650)
    run_init_flow(data_dir=data_dir, port=port, conn=conn)


@app.command()
@click.option("--date", "date_str", default=None, help="YYYY-MM-DD (default today)")
def show(date_str: str | None) -> None:
    """Display-only mode (no Fitbit sync, no publish)."""
    from datetime import date as _date, datetime
    from zoneinfo import ZoneInfo

    from diet.db import load_config
    from diet.orchestrator import run_show_only

    conn = open_db(_data_dir() / "diet.db")
    cfg = load_config(conn)
    if cfg is None:
        raise click.ClickException(
            "config が未初期化です。先に `diet init` を実行してください。"
        )
    target = (
        _date.fromisoformat(date_str)
        if date_str
        else datetime.now(ZoneInfo(cfg.timezone)).date()
    )
    run_show_only(_data_dir(), target)


@app.command()
@click.argument("kcal", type=click.IntRange(min=1))
def baseline(kcal: int) -> None:
    """Update bootstrap_daily_kcal."""
    from dataclasses import replace

    from diet.db import load_config, save_config

    conn = open_db(_data_dir() / "diet.db")
    cfg = load_config(conn)
    if cfg is None:
        raise click.ClickException(
            "config が未初期化です。先に `diet init` を実行してください。"
        )
    save_config(conn, replace(cfg, bootstrap_daily_kcal=kcal))
    click.echo(f"baseline updated to {kcal} kcal/day")


@app.command()
@click.argument("kg", type=click.FloatRange(min=0.0, min_open=True))
@click.option("--date", "date_str", default=None, help="YYYY-MM-DD (default today)")
def weight(kg: float, date_str: str | None) -> None:
    """Manually record a weight reading."""
    from datetime import date as _date, datetime
    from zoneinfo import ZoneInfo

    from diet.db import load_config, upsert_daily_weight

    conn = open_db(_data_dir() / "diet.db")
    cfg = load_config(conn)
    if cfg is None:
        raise click.ClickException(
            "config が未初期化です。先に `diet init` を実行してください。"
        )
    target = (
        _date.fromisoformat(date_str)
        if date_str
        else datetime.now(ZoneInfo(cfg.timezone)).date()
    )
    upsert_daily_weight(conn, target, kg)
    click.echo(f"weight {kg}kg recorded for {target}")


@app.command()
@click.option("--days", default=14, type=click.IntRange(min=1))
def calibrate(days: int) -> None:
    """Show recent Fitbit calorie candidates and select exercise_calorie_source."""
    from diet.calibrate import run_calibrate

    run_calibrate(_data_dir(), days=days)


@app.command()
@click.option("--days", default=7, type=click.IntRange(min=1))
def sync(days: int) -> None:
    """Fetch Fitbit activity + weight for the last N days."""
    import asyncio

    import httpx

    from diet.cli_helpers import RefreshTokenError, run_sync_async
    from diet.db import load_token

    conn = open_db(_data_dir() / "diet.db")
    if load_token(conn) is None:
        raise click.ClickException("Not authenticated. Run `diet init` first.")
    try:
        asyncio.run(run_sync_async(conn, days=days))
    except (RefreshTokenError, httpx.HTTPStatusError) as e:
        # Auth-layer failure (revoked refresh token / invalid_grant). The
        # per-day fetch inside ``run_sync_async`` swallows transient errors,
        # so anything reaching here is a refresh-side failure and the user
        # needs to re-run ``diet auth``. ``httpx.HTTPStatusError`` is kept
        # for tests that mock ``run_sync_async`` directly.
        click.echo(f"sync failed: {e}", err=True)
        click.echo(
            "refresh token が無効になった可能性があります。"
            "`diet auth` で再認証してください。",
            err=True,
        )
        raise click.ClickException(
            "refresh token invalid — run `diet auth` to re-authenticate."
        ) from e
    click.echo(f"sync complete ({days} days)")
