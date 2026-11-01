"""只读质量检查任务处理器。"""

from __future__ import annotations

import sqlite3

from backend.app.db import repository
from backend.app.quality.checker import check_records
from backend.app.workers.jobs import TaskResult


def quality_check_handler(conn: sqlite3.Connection, job_id: str) -> TaskResult:
    del job_id
    assets, _ = repository.list_assets(conn, limit=100000)
    asset_types = {asset.id: asset.asset_type for asset in assets}
    daily_bars = repository.query_all_daily_bars(conn)
    fund_navs = repository.query_all_fund_navs(conn)
    report = check_records(daily_bars, fund_navs, asset_types)
    return TaskResult(
        processed_records=report.total_records,
        succeeded_records=report.passed_records,
        summary=report.to_dict(),
    )
