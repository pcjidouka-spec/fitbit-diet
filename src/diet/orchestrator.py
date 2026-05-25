"""Daily-flow orchestration (spec §4).

Two entry points:
- ``run_daily_flow``: 5-step flow (sync → intake input → BMR → balance → publish)
- ``run_show_only``: display-only (no sync, no intake prompt, no publish)

Both are called from ``diet.cli``. Heavy imports (DB, async sync) are deferred
inside the functions so ``diet --help`` and ``diet show`` stay snappy.
"""
import asyncio
from datetime import date as _date
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import click


def run_daily_flow(
    data_dir: Path, target_date: _date | None = None
) -> None:
    """Bare ``diet`` command: 5-step interactive daily flow.

    Step 1: Fitbit sync (last 7 days). Failure is non-fatal — print a warning
            and continue so the user can still log a meal offline.
    Step 2: Intake input. ``+N`` appends, ``=N`` overrides, Enter skips.
    Step 3: BMR via Mifflin–St Jeor using the latest weight on or before today.
    Step 4: Balance line via ``decide_intake_kcal`` + ``format_balance``.
    Step 5: Publish to HPasaneel (movement + weight only, never intake).
    """
    from diet.bmr import age_at, mifflin_st_jeor
    from diet.cli_helpers import run_sync_async
    from diet.db import (
        get_daily_activity,
        get_events_for_date,
        get_events_in_range,
        get_latest_weight_on_or_before,
        load_config,
        open_db,
    )
    from diet.formatters import format_balance, format_intake_display
    from diet.helpers import resolve_exercise_kcal
    from diet.intake import decide_intake_kcal, past_avg, recorded_sum

    conn = open_db(data_dir / "diet.db")
    cfg = load_config(conn)
    if cfg is None:
        raise click.ClickException(
            "config が未初期化です。先に `diet init` を実行してください。"
        )
    tz = ZoneInfo(cfg.timezone)
    today = target_date or datetime.now(tz).date()

    # [1/5] Fitbit sync — failure tolerated
    click.echo("[1/5 Fitbit同期] 取得中...")
    try:
        asyncio.run(run_sync_async(conn, days=7))
    except Exception as e:
        click.echo(f"  ⚠ sync failed: {e} (オフラインで続行)")

    activity = get_daily_activity(conn, today)
    weight = get_latest_weight_on_or_before(conn, today)
    if activity is not None:
        click.echo(
            f"  歩数 {activity.steps:,} / 距離 {activity.distance_km:.1f}km"
        )
    if weight is not None:
        click.echo(f"  体重 {weight.weight_kg}kg ({weight.date} 計測)")

    # [2/5] 食事入力
    cur_events = get_events_for_date(conn, today)
    cur_sum = recorded_sum(cur_events) or 0
    user_in = click.prompt(
        f"[2/5 食事入力] 累積 {cur_sum} kcal、入力 (+追加 / =上書き / Enter=skip)",
        default="",
        show_default=False,
    )
    _handle_intake_input(conn, today, user_in.strip())

    # [3/5] BMR
    bmr: float | None = None
    if weight is not None:
        age = age_at(cfg.birthday, today)
        bmr = mifflin_st_jeor(weight.weight_kg, cfg.height_cm, age, cfg.sex)
        click.echo(
            f"[3/5 BMR] {age}歳 / {cfg.height_cm}cm / "
            f"{weight.weight_kg}kg → {int(bmr):,} kcal"
        )
    else:
        click.echo("[3/5 BMR] 体重データなしのため算出不可")

    # [4/5] 収支
    history = get_events_in_range(conn, today - timedelta(days=14), today)
    avg, n = past_avg(history, today)
    today_events = get_events_for_date(conn, today)
    decision = decide_intake_kcal(today_events, avg, n, cfg.bootstrap_daily_kcal)
    exercise = resolve_exercise_kcal(activity, cfg.exercise_calorie_source)
    click.echo("[4/5 収支]")
    click.echo("  " + format_intake_display(decision))
    if bmr is not None and weight is not None and activity is not None:
        click.echo(
            "  "
            + format_balance(
                decision.intake_kcal,
                bmr,
                exercise,
                activity.steps,
                activity.distance_km,
                weight.weight_kg,
            )
        )

    # [5/5] publish
    if not click.confirm("[5/5 公開] HPasaneel に運動・体重のみ公開しますか?"):
        return
    if cfg.hpasaneel_path is None or activity is None or weight is None:
        click.echo("  publish skip: required data missing")
        return
    from diet.publish import build_records_from_db, publish_to_hpasaneel

    records = build_records_from_db(
        conn, [today], cfg.exercise_calorie_source or "marginal"
    )
    try:
        publish_to_hpasaneel(
            Path(cfg.hpasaneel_path),
            cfg.hpasaneel_diet_root,
            records,
            do_push=True,
        )
        click.echo("  publish 完了")
    except Exception as e:
        click.echo(f"  publish 失敗: {e}")
        click.echo(
            f"  手動で `cd {cfg.hpasaneel_path} && "
            f"git pull --rebase && git push` してください"
        )


def run_show_only(data_dir: Path, target_date: _date) -> None:
    """``diet show``: display-only — no sync, no intake prompt, no publish."""
    from diet.bmr import age_at, mifflin_st_jeor
    from diet.db import (
        get_daily_activity,
        get_events_for_date,
        get_events_in_range,
        get_latest_weight_on_or_before,
        load_config,
        open_db,
    )
    from diet.formatters import format_balance, format_intake_display
    from diet.helpers import resolve_exercise_kcal
    from diet.intake import decide_intake_kcal, past_avg

    conn = open_db(data_dir / "diet.db")
    cfg = load_config(conn)
    if cfg is None:
        raise click.ClickException(
            "config が未初期化です。先に `diet init` を実行してください。"
        )
    activity = get_daily_activity(conn, target_date)
    weight = get_latest_weight_on_or_before(conn, target_date)
    history = get_events_in_range(
        conn, target_date - timedelta(days=14), target_date
    )
    avg, n = past_avg(history, target_date)
    today_events = get_events_for_date(conn, target_date)
    decision = decide_intake_kcal(today_events, avg, n, cfg.bootstrap_daily_kcal)
    click.echo(format_intake_display(decision))
    if weight is not None and activity is not None:
        age = age_at(cfg.birthday, target_date)
        bmr = mifflin_st_jeor(weight.weight_kg, cfg.height_cm, age, cfg.sex)
        exercise = resolve_exercise_kcal(activity, cfg.exercise_calorie_source)
        click.echo(
            format_balance(
                decision.intake_kcal,
                bmr,
                exercise,
                activity.steps,
                activity.distance_km,
                weight.weight_kg,
            )
        )


def _handle_intake_input(conn, target: _date, raw: str) -> None:
    """Parse the freeform intake input line and persist as an intake_event.

    Accepted forms:
      - ``""`` → skip
      - ``"+N"`` → append N kcal
      - ``"=N"`` → override total to N kcal (also marks the day as complete)
    Any other input raises ``click.ClickException``.
    """
    from diet.db import insert_intake_event

    if not raw:
        return
    now = datetime.now()
    if raw.startswith("+"):
        try:
            kcal = int(raw[1:])
        except ValueError as e:
            raise click.ClickException(
                f"unrecognized input: {raw!r} (+N or =N の N は整数)"
            ) from e
        insert_intake_event(conn, target, now, kcal, "append")
    elif raw.startswith("="):
        try:
            kcal = int(raw[1:])
        except ValueError as e:
            raise click.ClickException(
                f"unrecognized input: {raw!r} (+N or =N の N は整数)"
            ) from e
        insert_intake_event(conn, target, now, kcal, "override")
    else:
        raise click.ClickException(
            f"unrecognized input: {raw!r} (+追加 or =上書き or Enter)"
        )
