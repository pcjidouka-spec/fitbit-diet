from datetime import date, timedelta

import click

from diet.db import get_daily_activity, load_config, open_db


def run_calibrate(data_dir, days: int = 14) -> None:
    conn = open_db(data_dir / "diet.db")
    cfg = load_config(conn)
    if cfg is None:
        raise click.ClickException("config が未初期化です。先に `diet init` を実行してください。")
    today = date.today()
    click.echo(f"過去 {days} 日の活動カロリー（参考表示）:")
    click.echo(f"{'date':<12} {'steps':>8} {'distance_km':>12} {'active_energy':>14} {'total_calories':>15}")
    for offset in range(days):
        d = today - timedelta(days=offset)
        a = get_daily_activity(conn, d)
        if a is None:
            continue
        click.echo(
            f"{d.isoformat():<12} {a.steps:>8,} {a.distance_km:>12.1f} "
            f"{(a.active_energy_kcal or 0):>14,} {(a.total_calories_kcal or 0):>15,}"
        )
    click.echo("\n運動カロリーは active_energy（基礎代謝を除いた活動由来の消費）を使用します。")
    click.echo("total_calories（基礎代謝を含む総消費）は参考値で、収支計算には使いません。")
