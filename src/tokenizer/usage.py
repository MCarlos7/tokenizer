from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from tokenizer.opencode_db import UsageRecord
from tokenizer.pricing import PROVIDER, ModelPrice

FIVE_HOURS = timedelta(hours=5)
WEEK = timedelta(days=7)

LIMITS_PERCENT = {"5h": 20.0, "weekly": 50.0, "monthly": 100.0}


@dataclass(frozen=True)
class Window:
    name: str
    used_percent: float
    limit_percent: float
    resets_at: datetime | None

    @property
    def remaining_percent(self) -> float:
        return max(self.limit_percent - self.used_percent, 0.0)


def utc(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def record_percent(record: UsageRecord, prices: dict[str, ModelPrice]) -> float:
    """Porcentaje del límite mensual del plan que consume una petición."""
    if record.provider != PROVIDER:
        return 0.0
    price = prices.get(record.model)
    if price is None or not price.monthly_limit:
        return 0.0
    return price.cost(record) / price.monthly_limit * 100


def start_of_week(now: datetime) -> datetime:
    monday = now - timedelta(days=now.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)


def add_months(moment: datetime, months: int) -> datetime:
    total = moment.year * 12 + (moment.month - 1) + months
    year, month_index = divmod(total, 12)
    day = min(moment.day, calendar.monthrange(year, month_index + 1)[1])
    return moment.replace(year=year, month=month_index + 1, day=day)


def billing_period(
    now: datetime,
    renews_at: datetime | None = None,
) -> tuple[datetime, datetime]:
    """Periodo de pago actual: de la última renovación a la próxima.

    Sin fecha de renovación, usa meses naturales en UTC.
    """
    if renews_at is None:
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return start, add_months(start, 1)
    end = renews_at
    while end <= now:
        end = add_months(end, 1)
    return add_months(end, -1), end


def compute_windows(
    records: list[UsageRecord],
    prices: dict[str, ModelPrice],
    now: datetime | None = None,
    renews_at: datetime | None = None,
) -> list[Window]:
    """Calcula los tres límites de Go: 5 h (desde el primer uso), semanal y mensual."""
    now = now or datetime.now(timezone.utc)
    events = sorted(
        ((utc(r.created_ms), record_percent(r, prices)) for r in records),
        key=lambda event: event[0],
    )

    month_start, month_end = billing_period(now, renews_at)
    week_start = start_of_week(now)

    five_start: datetime | None = None
    five_used = 0.0
    week_used = 0.0
    month_used = 0.0

    for moment, percent in events:
        if five_start is None or moment >= five_start + FIVE_HOURS:
            five_start = moment
            five_used = 0.0
        five_used += percent
        if moment >= week_start:
            week_used += percent
        if month_start <= moment < month_end:
            month_used += percent

    five_active = five_start is not None and now < five_start + FIVE_HOURS

    return [
        Window(
            name="5h",
            used_percent=five_used if five_active else 0.0,
            limit_percent=LIMITS_PERCENT["5h"],
            resets_at=five_start + FIVE_HOURS if five_active else None,
        ),
        Window(
            name="weekly",
            used_percent=week_used,
            limit_percent=LIMITS_PERCENT["weekly"],
            resets_at=week_start + WEEK,
        ),
        Window(
            name="monthly",
            used_percent=month_used,
            limit_percent=LIMITS_PERCENT["monthly"],
            resets_at=month_end,
        ),
    ]


def usage_by_model(
    records: list[UsageRecord],
    prices: dict[str, ModelPrice],
    since: datetime,
    until: datetime | None = None,
) -> dict[str, float]:
    totals: dict[str, float] = {}
    for record in records:
        moment = utc(record.created_ms)
        if moment < since or (until is not None and moment >= until):
            continue
        percent = record_percent(record, prices)
        if percent:
            totals[record.model] = totals.get(record.model, 0.0) + percent
    return dict(sorted(totals.items(), key=lambda item: item[1], reverse=True))
