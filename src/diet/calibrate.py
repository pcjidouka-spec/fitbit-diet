from dataclasses import replace
from datetime import date, timedelta

import click

from diet.db import get_daily_activity, load_config, open_db, save_config


def run_calibrate(data_dir, days: int = 14) -> None:
    conn = open_db(data_dir / "diet.db")
    cfg = load_config(conn)
    today = date.today()
    click.echo(f"過去 {days} 日の Fitbit カロリー候補:")
    click.echo(
        f"{'date':<12} {'steps':>8} {'distance_km':>12} {'logged_activities':>18} {'marginal':>10}"
    )
    for offset in range(days):
        d = today - timedelta(days=offset)
        a = get_daily_activity(conn, d)
        if a is None:
            continue
        click.echo(
            f"{d.isoformat():<12} {a.steps:>8,} {a.distance_km:>12.1f} "
            f"{(a.logged_activities_kcal or 0):>18,} {(a.marginal_kcal or 0):>10,}"
        )
    click.echo("\n候補の意味:")
    click.echo("  logged_activities: 明示的に記録された運動エントリの合計")
    click.echo(
        "  marginal:          Fitbit が活動由来と推定した分（基礎代謝含まず、推奨デフォルト）"
    )
    choice = click.prompt(
        "採用する exercise_calorie_source",
        type=click.Choice(["logged_activities", "marginal", "decide_later"]),
        default="marginal",
    )
    if choice == "decide_later":
        click.echo("source 未確定、当面 marginal で仮計算します。")
        return
    save_config(conn, replace(cfg, exercise_calorie_source=choice))
    click.echo(f"exercise_calorie_source = {choice} を config に保存しました。")
