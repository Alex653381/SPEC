"""统一更新调度服务：供管理 API 和 CLI 复用，不在 API 中拼接 shell 命令。"""

from __future__ import annotations

import json
import os
import socket
import threading
import uuid
from datetime import date, timedelta

from backend.app.db.database import init_db
from backend.app.db import repository
from backend.app.quality.checker import check_records
from backend.app.providers.eastmoney import EastmoneyETFAdapter
from backend.app.providers.fund_lsjz import LsjzFundAdapter, eastmoney_lsjz_fetcher
from backend.app.providers.sina import SinaStockAdapter
from backend.app.providers.tencent import TencentIndexAdapter
from backend.app.services.live_validation import (
    classify_error,
    fetch_with_retry,
    redact_error_detail,
)
from backend.app.workers.jobs import TaskExecutionError, TaskResult, run_job_once
from backend.app.workers.live_fund_import import import_live_fund_incremental
from backend.app.workers.live_import import import_live_daily_incremental
from scripts import (
    pilot_import_benchmark as benchmark_cli,
    pilot_import_etf as etf_cli,
    pilot_import_fund as fund_cli,
    pilot_import_stock as stock_cli,
)


ROOT = stock_cli.ROOT
ALLOWED_ASSET_TYPES = ("stock", "fund", "index", "etf")


SPECS = {
    "stock": {
        "db": "data/live-pilot.db",
        "code": "sz000001",
        "asset_id": "stock-000001",
        "resolver": stock_cli.resolve_pilot_path,
        "make": stock_cli.make_live_asset,
        "ensure": stock_cli.ensure_asset,
        "fetch": stock_cli._stock_fetcher,
        "adapter": SinaStockAdapter,
        "writer": lambda conn, asset_id, records: import_live_daily_incremental(conn, asset_id, "stock", records),
    },
    "fund": {
        "db": "data/live-fund-pilot.db",
        "code": "110022",
        "asset_id": "fund-110022",
        "resolver": fund_cli.resolve_fund_pilot_path,
        "make": fund_cli.make_live_fund_asset,
        "ensure": fund_cli.ensure_fund_asset,
        "fetch": eastmoney_lsjz_fetcher,
        "adapter": LsjzFundAdapter,
        "writer": import_live_fund_incremental,
    },
    "index": {
        "db": "data/live-benchmark.db",
        "code": "sh000001",
        "asset_id": "index-sh000001",
        "resolver": benchmark_cli.resolve_benchmark_path,
        "make": benchmark_cli.make_benchmark_asset,
        "ensure": benchmark_cli.ensure_benchmark_asset,
        "fetch": benchmark_cli._tencent_index_fetcher,
        "adapter": TencentIndexAdapter,
        "writer": lambda conn, asset_id, records: import_live_daily_incremental(conn, asset_id, "index", records),
    },
    "etf": {
        "db": "data/live-etf-pilot.db",
        "code": "510300",
        "asset_id": "etf-510300-live",
        "resolver": etf_cli.resolve_etf_path,
        "make": etf_cli.make_etf_asset,
        "ensure": etf_cli.ensure_etf_asset,
        "fetch": etf_cli._eastmoney_etf_fetcher,
        "adapter": EastmoneyETFAdapter,
        "writer": lambda conn, asset_id, records: import_live_daily_incremental(conn, asset_id, "etf", records),
    },
}


def build_plan(asset_type: str, start: date | None, end: date | None) -> dict:
    spec = SPECS[asset_type]
    path = spec["resolver"](os.path.join(ROOT, spec["db"]))
    latest = _read_latest(asset_type, path, spec["asset_id"])
    window = (start, end)
    if window[0] is None or window[1] is None:
        if latest is None:
            window = None
        else:
            window = (latest + timedelta(days=1), date.today())
    return {
        "asset_type": asset_type,
        "asset_code": spec["code"],
        "database": os.path.abspath(path),
        "latest_date": latest.isoformat() if latest else None,
        "window": (
            {"start": window[0].isoformat(), "end": window[1].isoformat()}
            if window
            else None
        ),
    }


def _read_latest(asset_type: str, path: str, asset_id: str) -> date | None:
    if asset_type == "fund":
        return fund_cli.read_latest_fund_nav_date(path, asset_id)
    return stock_cli.read_latest_trade_date(path, asset_id)


def run_asset_update(asset_type: str, start: date, end: date, retries: int = 2, backoff: float = 1.0) -> dict:
    spec = SPECS[asset_type]
    path = spec["resolver"](os.path.join(ROOT, spec["db"]))
    conn = init_db(path)
    try:
        asset = spec["make"](spec["code"])
        spec["ensure"](conn, asset)

        previous_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(20)
        try:
            adapter = spec["adapter"](
                lambda _asset_id, _start, _end: spec["fetch"](asset.provider_symbol, _start, _end)
            )
            fetched = fetch_with_retry(
                lambda: adapter.fetch_history(asset.id, start=start, end=end),
                retries=retries,
                backoff=backoff,
            )
        except Exception as exc:  # noqa: BLE001
            return {
                "status": "fetch_failed",
                "error_category": classify_error(exc),
                "error_type": type(exc).__name__,
                "error_detail": redact_error_detail(exc),
                "database_written": False,
                "committed": False,
            }
        finally:
            socket.setdefaulttimeout(previous_timeout)

        if asset_type == "fund":
            pre_quality = check_records([], fetched.records, {asset.id: "open_fund"})
        else:
            pre_quality = check_records(fetched.records, [], {asset.id: asset_type})
        context = {
            "provider": asset.provider,
            "asset_code": asset.provider_symbol,
            "asset_id": asset.id,
            "request_window": {"start": start.isoformat(), "end": end.isoformat()},
            "database_path": path,
            "fetched_rows": fetched.fetched_rows,
            "converted_rows": len(fetched.records),
            "skipped_rows": len(fetched.errors),
            "pre_quality": {
                "issue_count": pre_quality.issue_count,
                "by_severity": pre_quality.by_severity,
            },
        }
        if not fetched.records:
            return {**context, "status": "empty", "database_written": False, "committed": False}

        def handler(conn, job_id):
            del job_id
            try:
                result = spec["writer"](conn, asset.id, fetched.records)
            except TaskExecutionError as exc:
                raise TaskExecutionError(
                    exc.args[0],
                    error_code=exc.error_code,
                    summary={**context, **exc.summary},
                ) from exc
            return TaskResult(
                processed_records=result["input_count"],
                succeeded_records=result.get("inserted", 0),
                summary={**context, **result},
            )

        job_id = f"admin-{asset_type}-{uuid.uuid4().hex}"
        record = run_job_once(conn, job_id, handler)
        execution = json.loads(record.execution_summary) if record.execution_summary else {}
        post = _read_post_state(asset_type, conn, asset.id)
        return {
            "job_id": record.id,
            "status": record.status,
            "result_status": classify_result_status(record.status, execution),
            "error_code": record.error_code,
            "error_summary": record.error_summary,
            "execution_summary": execution,
            "post_check": post,
        }
    finally:
        conn.close()


def classify_result_status(job_status: str, execution: dict | None) -> str:
    if job_status != "success":
        return "failed"
    if not execution:
        return "no_new_data"
    inserted = execution.get("inserted")
    if inserted is None:
        return "no_new_data"
    if int(inserted) > 0:
        return "updated"
    if execution.get("changed_count"):
        return "difference_reported"
    return "no_new_data"


def _read_post_state(asset_type: str, conn, asset_id: str) -> dict:
    if asset_type == "fund":
        rows = repository.query_fund_navs(conn, asset_id)
        dates = [row.nav_date for row in rows]
    else:
        rows = repository.query_daily_bars(conn, asset_id)
        dates = [row.trade_date for row in rows]
    return {
        "record_count": len(rows),
        "first_date": min(dates).isoformat() if dates else None,
        "last_date": max(dates).isoformat() if dates else None,
    }


class UpdateJobManager:
    def __init__(self):
        self._jobs: dict[str, dict] = {}
        self._running: set[str] = set()
        self._lock = threading.Lock()

    def start(self, asset_type: str, start: date, end: date, retries: int, backoff: float) -> dict:
        with self._lock:
            if asset_type in self._running:
                return {"error": "same_asset_running"}
            self._running.add(asset_type)
            job_id = f"admin-{asset_type}-{uuid.uuid4().hex}"
            self._jobs[job_id] = {"id": job_id, "asset_type": asset_type, "status": "running", "result": None}

        def worker():
            result = run_asset_update(asset_type, start, end, retries, backoff)
            with self._lock:
                status = "success" if result.get("status") in ("success", "empty") else "failed"
                self._jobs[job_id]["status"] = status
                self._jobs[job_id]["result"] = result
                self._running.discard(asset_type)

        threading.Thread(target=worker, daemon=True).start()
        return self._jobs[job_id]

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None
