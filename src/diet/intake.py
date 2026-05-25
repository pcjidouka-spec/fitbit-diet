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
            est = max(rec, bootstrap_baseline)
            return IntakeDecision(
                intake_kcal=est, label="estimated_baseline_supplement",
                recorded_part=rec, supplement_part=est - rec, n_samples=n_samples,
            )
        return IntakeDecision(intake_kcal=rec, label="recorded_no_baseline", n_samples=n_samples)

    if has_avg:
        return IntakeDecision(intake_kcal=round(past_avg_val), label="estimated_avg", n_samples=n_samples)
    if has_baseline:
        return IntakeDecision(intake_kcal=bootstrap_baseline, label="estimated_baseline", n_samples=n_samples)
    return IntakeDecision(intake_kcal=None, label="unconfirmed", n_samples=n_samples)
