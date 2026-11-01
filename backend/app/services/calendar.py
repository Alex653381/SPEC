"""交易日历、缺口检测与基金占位行隔离。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable


@dataclass(frozen=True)
class GapInterval:
    start: date
    end: date
    kind: str


def build_calendar(dates: Iterable[date]) -> set[date]:
    return {d for d in dates}


def detect_gaps(
    dates: Iterable[date],
    calendar: set[date],
    start: date | None = None,
    end: date | None = None,
) -> list[GapInterval]:
    """返回日历中缺失的连续交易日区间，不推断缺口原因。"""
    present = set(dates)
    candidates = sorted(d for d in calendar if (start is None or d >= start) and (end is None or d <= end))
    missing = [d for d in candidates if d not in present]
    gaps: list[GapInterval] = []
    for day in missing:
        if gaps and day - gaps[-1].end == timedelta(days=1):
            gaps[-1] = GapInterval(gaps[-1].start, day, "missing")
        else:
            gaps.append(GapInterval(day, day, "missing"))
    return gaps


def partition_fund_nav(
    records: list,
    placeholder_dates: set[date] | None = None,
):
    """仅在显式提供占位日期集合时才隔离；否则保留全部记录，不做猜测式清洗。"""
    if placeholder_dates is None:
        return list(records), []
    valid, placeholders = [], []
    for record in records:
        if record.nav_date in placeholder_dates:
            placeholders.append(record)
        else:
            valid.append(record)
    return valid, placeholders
