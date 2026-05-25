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
