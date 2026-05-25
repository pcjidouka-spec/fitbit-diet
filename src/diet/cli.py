import os
from pathlib import Path

import click

from diet.db import open_db, save_config, Config


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
