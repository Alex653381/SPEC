"""真实基金净值受控试点入库。只允许写入 data/live-fund-pilot.db，默认不联网。"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sqlite3
import sys
import uuid
from datetime import date, timedelta

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backend.app.db import jobs_repository
from backend.app.db import repository
from backend.app.db.database import init_db
from backend.app.providers.fund_lsjz import LsjzFundAdapter, eastmoney_lsjz_fetcher
from backend.app.quality.checker import check_records
from backend.app.schemas.records import AssetRecord
from backend.app.services.live_validation import (
    classify_error,
    fetch_with_retry,
    redact_error_detail,
)
from backend.app.workers.jobs import TaskExecutionError, TaskResult, run_job_once
from backend.app.workers.live_fund_import import import_live_fund_incremental


PILOT_DB_NAME = "live-fund-pilot.db"


def expected_fund_pilot_path() -> str:
    return os.path.abspath(os.path.join(ROOT, "data", PILOT_DB_NAME))


def resolve_fund_pilot_path(db_arg: str) -> str:
    expected = expected_fund_pilot_path()
    given = os.path.abspath(db_arg)
    if os.path.normcase(given) != os.path.normcase(expected):
        raise ValueError(f"拒绝写入非预期数据库：{given}；本阶段只允许 {expected}")
    return given


def make_live_fund_asset(code: str) -> AssetRecord:
    code = code.strip()
    return AssetRecord(
        id=f"fund-{code}",
        symbol=code,
        name="易方达消费行业股票" if code == "110022" else code,
        asset_type="open_fund",
        market="OTC",
        currency="CNY",
        provider="eastmoney_fund_lsjz",
        provider_symbol=code,
        adjustment_mode=None,
        price_semantics="unit_nav",
        volume_unit=None,
        is_active=True,
    )


def ensure_fund_asset(conn, asset: AssetRecord) -> None:
    existing = repository.get_asset(conn, asset.id)
    if existing is None:
        with conn:
            repository.insert_asset(conn, asset)
        return
    expected = (asset.symbol, asset.asset_type, asset.provider, asset.price_semantics)
    actual = (existing.symbol, existing.asset_type, existing.provider, existing.price_semantics)
    if actual != expected:
        raise ValueError(f"资产 {asset.id} 已存在但元数据不一致：expected={expected} actual={actual}")


def compute_fund_window_from_latest(latest: date | None, today: date, max_days: int):
    if latest is None:
        raise ValueError("数据库尚无该基金记录，请显式指定 --start/--end")
    start = latest + timedelta(days=1)
    if start > today:
        return None
    if (today - start).days > max_days:
        raise ValueError(
            f"自动增量窗口过长：{start.isoformat()} 至 {today.isoformat()} "
            f"超过 {max_days} 天，请显式指定 --start/--end"
        )
    return start, today


def read_latest_fund_nav_date(path: str, asset_id: str) -> date | None:
    if not os.path.exists(path):
        return None
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = repository.query_fund_navs(conn, asset_id)
        return max((row.nav_date for row in rows), default=None)
    finally:
        conn.close()


def _resolve_window(args, pilot_path: str):
    today = date.today()
    asset_id = f"fund-{args.code.strip()}"
    if args.start and args.end:
        return date.fromisoformat(args.start), date.fromisoformat(args.end)
    if bool(args.start) != bool(args.end):
        raise ValueError("--start 与 --end 必须同时提供")
    latest = read_latest_fund_nav_date(pilot_path, asset_id)
    return compute_fund_window_from_latest(latest, today, args.max_days)


def build_fund_handler(asset_id: str, records, context: dict):
    def handler(conn, job_id: str) -> TaskResult:
        del job_id
        try:
            result = import_live_fund_incremental(conn, asset_id, records)
        except TaskExecutionError as exc:
            raise TaskExecutionError(
                exc.args[0],
                error_code=exc.error_code,
                summary={**context, **exc.summary},
            ) from exc
        return TaskResult(
            processed_records=result["input_count"],
            succeeded_records=result["inserted"],
            summary={**context, **result},
        )

    return handler


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True, help="必须是 data/live-fund-pilot.db")
    parser.add_argument("--code", default="110022", help="本阶段固定为 110022")
    parser.add_argument("--start", help="YYYY-MM-DD；update 模式可省略")
    parser.add_argument("--end", help="YYYY-MM-DD；update 模式可省略")
    parser.add_argument("--max-days", type=int, default=60, help="自动窗口最多覆盖的自然日数")
    parser.add_argument("--retries", type=int, default=2, help="网络/超时类错误的最多重试次数")
    parser.add_argument("--backoff", type=float, default=1.0, help="重试退避基础秒数")
    parser.add_argument("--job-id", default=None)
    parser.add_argument("--live", action="store_true", help="显式确认后发起一次真实请求")
    args = parser.parse_args()

    try:
        pilot_path = resolve_fund_pilot_path(args.db)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.code.strip() != "110022":
        print("本阶段只允许基金代码 110022", file=sys.stderr)
        return 2

    print(f"pilot_database={pilot_path}")
    print(f"asset_code={args.code.strip()}")

    if not args.live:
        print(
            json.dumps(
                {
                    "status": "not_executed",
                    "database_written": False,
                    "reason": "未指定 --live，不发起真实请求",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2

    try:
        resolved = _resolve_window(args, pilot_path)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if resolved is None:
        print(
            json.dumps(
                {"status": "up_to_date", "database_written": False},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    start, end = resolved
    if start > end:
        print("日期范围无效：start 晚于 end", file=sys.stderr)
        return 2
    if (end - start).days > args.max_days:
        print(f"日期范围超过上限 {args.max_days} 天", file=sys.stderr)
        return 2

    print(f"request_window={start.isoformat()}/{end.isoformat()}")

    os.makedirs(os.path.dirname(pilot_path), exist_ok=True)
    conn = init_db(pilot_path)
    try:
        asset = make_live_fund_asset(args.code)
        ensure_fund_asset(conn, asset)

        previous_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(20)
        try:
            adapter = LsjzFundAdapter(
                lambda _asset_id, _start, _end: eastmoney_lsjz_fetcher(
                    asset.provider_symbol, _start, _end
                )
            )
            result = fetch_with_retry(
                lambda: adapter.fetch_history(asset.id, start=start, end=end),
                retries=args.retries,
                backoff=args.backoff,
            )
        except Exception as exc:  # noqa: BLE001 - 记录分类后的失败摘要，不重试
            summary = {
                "status": "fetch_failed",
                "provider": "eastmoney_fund_lsjz",
                "asset_code": asset.provider_symbol,
                "asset_id": asset.id,
                "request_window": {"start": start.isoformat(), "end": end.isoformat()},
                "database_path": pilot_path,
                "error_category": classify_error(exc),
                "error_type": type(exc).__name__,
                "error_detail": redact_error_detail(exc),
                "database_written": False,
                "committed": False,
            }
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 1
        finally:
            socket.setdefaulttimeout(previous_timeout)

        pre_quality = check_records([], result.records, {asset.id: "open_fund"})
        context = {
            "provider": "eastmoney_fund_lsjz",
            "asset_code": asset.provider_symbol,
            "asset_id": asset.id,
            "request_window": {"start": start.isoformat(), "end": end.isoformat()},
            "database_path": pilot_path,
            "fetched_rows": result.fetched_rows,
            "converted_rows": len(result.records),
            "skipped_rows": len(result.errors),
            "pre_quality": {
                "issue_count": pre_quality.issue_count,
                "by_severity": pre_quality.by_severity,
            },
        }

        if not result.records:
            print(
                json.dumps(
                    {"status": "empty", "database_written": False, "committed": False, **context},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 1

        job_id = args.job_id or f"live_fund_update-{uuid.uuid4().hex}"
        handler = build_fund_handler(asset.id, result.records, context)
        try:
            record = run_job_once(conn, job_id, handler)
        except jobs_repository.JobStateError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        except sqlite3.Error as exc:
            print(f"任务执行失败：{type(exc).__name__}: {exc}", file=sys.stderr)
            return 2

        execution = json.loads(record.execution_summary) if record.execution_summary else {}
        print(
            json.dumps(
                {
                    "job_id": record.id,
                    "job_type": record.job_type,
                    "status": record.status,
                    "error_code": record.error_code,
                    "error_summary": record.error_summary,
                    "execution_summary": execution,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if record.status == "success" else 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
