"""采集服务：串联适配器、校验、合并与 Repository。"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Callable

from backend.app.core.quality import AssetType, QualityStatus
from backend.app.db import repository
from backend.app.providers.base import AdapterError
from backend.app.providers.registry import get_adapter_class
from backend.app.services.calendar import partition_fund_nav


STATUS_SUCCESS = "success"
STATUS_PARTIAL = "partial_success"
STATUS_EMPTY = "empty"
STATUS_FAILED = "failed"
STATUS_NOT_READY = "not_ready"


@dataclass(frozen=True)
class IngestionResult:
    asset_id: str
    adapter: str
    status: str
    fetched_rows: int
    valid_rows: int
    anomaly_rows: int
    written_rows: int
    skipped_rows: int
    errors: list[str] = field(default_factory=list)
    completed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def ingest(
    conn: sqlite3.Connection,
    asset_id: str,
    fetcher: Callable,
    start: date | None = None,
    end: date | None = None,
    calendar: set[date] | None = None,
) -> IngestionResult:
    asset = repository.get_asset(conn, asset_id)
    if asset is None:
        return _failed(asset_id, "", ["资产不存在"])

    adapter_class = get_adapter_class(asset.asset_type)
    if adapter_class is None:
        return _failed(asset_id, "", [f"资产类别 {asset.asset_type} 没有已注册适配器"])

    adapter = adapter_class(fetcher)
    try:
        fetched = adapter.fetch_history(asset_id, start, end)
    except AdapterError as exc:
        return _failed(asset_id, adapter.name, [str(exc)])

    if fetched.empty:
        return IngestionResult(
            asset_id=asset_id,
            adapter=adapter.name,
            status=STATUS_EMPTY,
            fetched_rows=0,
            valid_rows=0,
            anomaly_rows=0,
            written_rows=0,
            skipped_rows=0,
            errors=[],
        )

    records = list(fetched.records)
    errors = [f"row {e.row_index}: {e.code}: {e.message}" for e in fetched.errors]
    skipped = len(fetched.errors)

    if asset.asset_type == AssetType.OPEN_FUND:
        # 基金净值日期按基金披露日解释，不能套用股票交易日历做清洗。
        records, placeholders = partition_fund_nav(records)
        skipped += len(placeholders)

    if not records and fetched.errors:
        return _failed(asset_id, adapter.name, errors)

    valid_rows = sum(1 for r in records if r.quality_status == QualityStatus.NORMAL)
    anomaly_rows = sum(1 for r in records if r.quality_status != QualityStatus.NORMAL)

    try:
        with conn:
            if asset.asset_type == AssetType.OPEN_FUND:
                written = repository.insert_fund_navs(conn, records)
            else:
                written = repository.insert_daily_bars(conn, records)
    except sqlite3.Error as exc:
        return _failed(asset_id, adapter.name, errors + [f"数据库写入失败: {type(exc).__name__}"])

    status = STATUS_SUCCESS if skipped == 0 else STATUS_PARTIAL
    return IngestionResult(
        asset_id=asset_id,
        adapter=adapter.name,
        status=status,
        fetched_rows=fetched.fetched_rows,
        valid_rows=valid_rows,
        anomaly_rows=anomaly_rows,
        written_rows=written,
        skipped_rows=skipped,
        errors=errors,
    )


def _failed(asset_id: str, adapter: str, errors: list[str]) -> IngestionResult:
    return IngestionResult(
        asset_id=asset_id,
        adapter=adapter,
        status=STATUS_FAILED,
        fetched_rows=0,
        valid_rows=0,
        anomaly_rows=0,
        written_rows=0,
        skipped_rows=0,
        errors=errors,
    )
