from dataclasses import dataclass
from datetime import date, datetime, timedelta


SAMPLE_FLOOR = 3


@dataclass(frozen=True)
class IntakeEvent:
    id: int
    timestamp: datetime
    kcal: int
    op: str  # 'append' | 'override'


def recorded_sum(events: list[IntakeEvent]) -> int | None:
    if not events:
        return None
    sorted_events = sorted(events, key=lambda e: (e.timestamp, e.id))
    last_override_idx = None
    for i, e in enumerate(sorted_events):
        if e.op == "override":
            last_override_idx = i
    if last_override_idx is None:
        return sum(e.kcal for e in sorted_events)
    baseline = sorted_events[last_override_idx].kcal
    after = sum(e.kcal for e in sorted_events[last_override_idx + 1:] if e.op == "append")
    return baseline + after


def is_complete_day(events: list[IntakeEvent]) -> bool:
    return any(e.op == "override" for e in events)


@dataclass(frozen=True)
class DailyEvents:
    events: list[IntakeEvent]


def past_avg(
    history: dict[date, DailyEvents],
    target_date: date,
) -> tuple[float | None, int]:
    """Half-open window [target_date - 14, target_date), complete days only."""
    start = target_date - timedelta(days=14)
    sums: list[int] = []
    for d, daily in history.items():
        if start <= d < target_date and is_complete_day(daily.events):
            s = recorded_sum(daily.events)
            if s is not None:
                sums.append(s)
    n = len(sums)
    if n < SAMPLE_FLOOR:
        return (None, n)
    return (sum(sums) / n, n)


@dataclass(frozen=True)
class IntakeDecision:
    intake_kcal: int | None
    label: str
    recorded_part: int | None = None
    supplement_part: int | None = None
    n_samples: int = 0


@dataclass(frozen=True)
class ParsedIntake:
    kcal: int
    op: str  # 'append' | 'override'


def parse_kcal(raw: str) -> "ParsedIntake | None":
    """Parse a freeform intake line into a ParsedIntake, or None for skip.

    click 非依存の純関数。CLI（orchestrator）と Web（service）で共用する。
    不正入力は ValueError を送出し、呼び出し側（click / FastAPI）が翻訳する。

      - ""            → None（skip）
      - "+N" (N>=1)   → ParsedIntake(N, "append")
      - "=N" (N>=0)   → ParsedIntake(N, "override")
    先頭 +/= を剥いてから int 化するため、"+-500" のような負値は弾く。
    """
    s = raw.strip()
    if not s:
        return None
    if s.startswith("+"):
        return ParsedIntake(kcal=_parse_int(s, s[1:], min_value=1), op="append")
    if s.startswith("="):
        return ParsedIntake(kcal=_parse_int(s, s[1:], min_value=0), op="override")
    raise ValueError(f"unrecognized input: {raw!r} (+追加 or =上書き or Enter)")


def _parse_int(raw: str, payload: str, *, min_value: int) -> int:
    try:
        kcal = int(payload)
    except ValueError as e:
        raise ValueError(
            f"unrecognized input: {raw!r} (+N or =N の N は非負整数)"
        ) from e
    if kcal < min_value:
        raise ValueError(
            f"unrecognized input: {raw!r} (N は {min_value} 以上である必要があります)"
        )
    return kcal


def decide_intake_kcal(
    today_events: list[IntakeEvent],
    past_avg_val: float | None,
    n_samples: int,
    bootstrap_baseline: int | None,
) -> IntakeDecision:
    rec = recorded_sum(today_events)
    is_complete = is_complete_day(today_events)
    has_avg = past_avg_val is not None and n_samples >= SAMPLE_FLOOR
    has_baseline = bootstrap_baseline is not None

    if is_complete:
        assert rec is not None, "complete day implies non-empty events"
        return IntakeDecision(intake_kcal=rec, label="recorded_authoritative", n_samples=n_samples)

    if rec is not None:
        if has_avg:
            if rec >= past_avg_val:
                return IntakeDecision(intake_kcal=rec, label="recorded_partial_high", n_samples=n_samples)
            est = round(past_avg_val)
            return IntakeDecision(
                intake_kcal=est, label="estimated_avg_supplement",
                recorded_part=rec, supplement_part=est - rec, n_samples=n_samples,
            )
        if has_baseline:
            if rec >= bootstrap_baseline:
                return IntakeDecision(intake_kcal=rec, label="recorded_partial_high", n_samples=n_samples)
            return IntakeDecision(
                intake_kcal=bootstrap_baseline, label="estimated_baseline_supplement",
                recorded_part=rec, supplement_part=bootstrap_baseline - rec, n_samples=n_samples,
            )
        return IntakeDecision(intake_kcal=rec, label="recorded_no_baseline", n_samples=n_samples)

    if has_avg:
        return IntakeDecision(intake_kcal=round(past_avg_val), label="estimated_avg", n_samples=n_samples)
    if has_baseline:
        return IntakeDecision(intake_kcal=bootstrap_baseline, label="estimated_baseline", n_samples=n_samples)
    return IntakeDecision(intake_kcal=None, label="unconfirmed", n_samples=n_samples)
