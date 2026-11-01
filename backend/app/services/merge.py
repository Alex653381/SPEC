"""增量数据与已有数据的合并去重。"""

from __future__ import annotations

from dataclasses import dataclass

from backend.app.schemas.records import DailyBarRecord, FundNavRecord


@dataclass(frozen=True)
class MergeConflict:
    key: str
    kept_provider: str
    incoming_provider: str
    reason: str


def _merge(existing: list, incoming: list, key_fn, same_fn, preserve_existing: bool = True):
    index = {key_fn(record): record for record in existing}
    conflicts: list[MergeConflict] = []
    result = list(existing)

    for record in incoming:
        key = key_fn(record)
        if key not in index:
            index[key] = record
            result.append(record)
            continue
        old = index[key]
        if same_fn(record, old):
            continue
        conflicts.append(
            MergeConflict(
                key=str(key),
                kept_provider=old.provider,
                incoming_provider=record.provider,
                reason="existing preserved" if preserve_existing else "incoming replaced existing",
            )
        )
        if not preserve_existing:
            index[key] = record
            result = [record if key_fn(item) == key else item for item in result]

    result.sort(key=lambda item: getattr(item, _sort_field(item)))
    return result, conflicts


def _sort_field(record) -> str:
    if isinstance(record, DailyBarRecord):
        return "trade_date"
    if isinstance(record, FundNavRecord):
        return "nav_date"
    return "trade_date"


def merge_daily_bars(
    existing: list[DailyBarRecord],
    incoming: list[DailyBarRecord],
    preserve_existing: bool = True,
):
    key = lambda r: (r.asset_id, r.trade_date, r.adjustment_mode)
    same = lambda a, b: (
        a.asset_id,
        a.trade_date,
        a.adjustment_mode,
        a.open,
        a.high,
        a.low,
        a.close,
        a.volume,
        a.turnover,
    ) == (
        b.asset_id,
        b.trade_date,
        b.adjustment_mode,
        b.open,
        b.high,
        b.low,
        b.close,
        b.volume,
        b.turnover,
    )
    return _merge(existing, incoming, key, same, preserve_existing)


def merge_fund_navs(
    existing: list[FundNavRecord],
    incoming: list[FundNavRecord],
    preserve_existing: bool = True,
):
    key = lambda r: (r.asset_id, r.nav_date)
    same = lambda a, b: (
        a.asset_id,
        a.nav_date,
        a.unit_nav,
        a.accumulated_nav,
    ) == (
        b.asset_id,
        b.nav_date,
        b.unit_nav,
        b.accumulated_nav,
    )
    return _merge(existing, incoming, key, same, preserve_existing)
