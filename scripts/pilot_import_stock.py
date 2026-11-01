"""真实股票日线受控试点入库。只允许写入 data/live-pilot.db，默认不联网。"""

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
from backend.app.providers.sina import SinaStockAdapter
from backend.app.quality.checker import check_records
from backend.app.schemas.records import AssetRecord
from backend.app.services.live_validation import (
    classify_error,
    fetch_with_retry,
    redact_error_detail,
)
from backend.app.workers.jobs import TaskExecutionError, TaskResult, run_job_once
from backend.app.workers.live_import import (
    import_live_stock_incremental,
    revise_live_stock,
)
from scripts.validate_live_adapters import _stock_fetcher


PILOT_DB_NAME = "live-pilot.db"


def expected_pilot_path() -> str:
    return os.path.abspath(os.path.join(ROOT, "data", PILOT_DB_NAME))


def resolve_pilot_path(db_arg: str) -> str:
    expected = expected_pilot_path()
    given = os.path.abspath(db_arg)
    if os.path.normcase(given) != os.path.normcase(expected):
        raise ValueError(f"拒绝写入非预期数据库：{given}；本阶段只允许 {expected}")
    return given


def make_live_asset(code: str) -> AssetRecord:
    code = code.strip().lower()
    if len(code) < 3 or code[:2] not in ("sz", "sh", "bj"):
        raise ValueError("股票代码格式应为 sz000001、sh600519 或 bj...")
    market = code[:2].upper()
    symbol = code[2:]
    return AssetRecord(
        id=f"stock-{symbol}",
        symbol=symbol,
        name="平安银行" if symbol == "000001" else symbol,
        asset_type="stock",
        market=market,
        currency="CNY",
        provider="sina",
        provider_symbol=code,
        adjustment_mode="qfq",
        price_semantics="qfq",
        volume_unit="shares",
        is_active=True,
    )


def ensure_asset(conn, asset: AssetRecord) -> None:
    existing = repository.get_asset(conn, asset.id)
    if existing is None:
        with conn:
            repository.insert_asset(conn, asset)
        return
    expected = (
        asset.symbol,
        asset.market,
        asset.asset_type,
        asset.adjustment_mode,
    )
    actual = (
        existing.symbol,
        existing.market,
        existing.asset_type,
        existing.adjustment_mode,
    )
    if actual != expected:
        raise ValueError(f"资产 {asset.id} 已存在但元数据不一致：expected={expected} actual={actual}")


def build_handler(asset_id: str, records, context: dict, write_fn):
    def handler(conn, job_id: str) -> TaskResult:
        del job_id
        try:
            result = write_fn(conn, asset_id, records)
        except TaskExecutionError as exc:
            raise TaskExecutionError(
                exc.args[0],
                error_code=exc.error_code,
                summary={**context, **exc.summary},
            ) from exc
        succeeded = result.get("inserted", result.get("revised", 0))
        return TaskResult(
            processed_records=result["input_count"],
            succeeded_records=succeeded,
            summary={**context, **result},
        )

    return handler


def compute_window_from_latest(
    latest: date | None,
    today: date,
    max_days: int,
) -> tuple[date, date] | None:
    if latest is None:
        raise ValueError("数据库尚无该资产记录，请显式指定 --start/--end")
    start = latest + timedelta(days=1)
    if start > today:
        return None
    if (today - start).days > max_days:
        raise ValueError(
            f"自动增量窗口过长：{start.isoformat()} 至 {today.isoformat()} "
            f"超过 {max_days} 天，请显式指定 --start/--end"
        )
    return start, today


def read_latest_trade_date(path: str, asset_id: str) -> date | None:
    if not os.path.exists(path):
        return None
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = repository.query_daily_bars(conn, asset_id)
        return max((row.trade_date for row in rows), default=None)
    finally:
        conn.close()


def _resolve_window(args, pilot_path: str) -> tuple[date, date] | None:
    today = date.today()
    asset_id = f"stock-{args.code.strip().lower()[2:]}"
    if args.mode == "revise":
        if not args.start or not args.end:
            raise ValueError("revise 模式必须显式指定 --start 和 --end")
        return date.fromisoformat(args.start), date.fromisoformat(args.end)
    if args.start and args.end:
        return date.fromisoformat(args.start), date.fromisoformat(args.end)
    if bool(args.start) != bool(args.end):
        raise ValueError("--start 与 --end 必须同时提供")
    latest = read_latest_trade_date(pilot_path, asset_id)
    return compute_window_from_latest(latest, today, args.max_days)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True, help="必须是 data/live-pilot.db")
    parser.add_argument("--code", default="sz000001", help="本阶段固定为 sz000001")
    parser.add_argument("--mode", choices=("update", "revise"), default="update")
    parser.add_argument("--start", help="YYYY-MM-DD；update 模式可省略")
    parser.add_argument("--end", help="YYYY-MM-DD；update 模式可省略")
    parser.add_argument("--max-days", type=int, default=20, help="自动窗口最多覆盖的自然日数")
    parser.add_argument("--retries", type=int, default=2, help="网络/超时类错误的最多重试次数")
    parser.add_argument("--backoff", type=float, default=1.0, help="重试退避基础秒数")
    parser.add_argument("--job-id", default=None)
    parser.add_argument("--live", action="store_true", help="显式确认后发起一次真实请求")
    args = parser.parse_args()

    try:
        pilot_path = resolve_pilot_path(args.db)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.code.strip().lower() != "sz000001":
        print("本阶段只允许股票代码 sz000001", file=sys.stderr)
        return 2

    print(f"pilot_database={pilot_path}")
    print(f"asset_code={args.code.strip().lower()}")
    print(f"mode={args.mode}")

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
        asset = make_live_asset(args.code)
        ensure_asset(conn, asset)

        previous_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(20)
        try:
            adapter = SinaStockAdapter(
                lambda _asset_id, _start, _end: _stock_fetcher(asset.provider_symbol, _start, _end)
            )
            result = fetch_with_retry(
                lambda: adapter.fetch_history(asset.id, start=start, end=end),
                retries=args.retries,
                backoff=args.backoff,
            )
        except Exception as exc:  # noqa: BLE001 - 记录分类后的失败摘要，不重试
            summary = {
                "status": "fetch_failed",
                "provider": "sina",
                "asset_code": asset.provider_symbol,
                "asset_id": asset.id,
                "adjustment_mode": "qfq",
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

        pre_quality = check_records(result.records, [], {asset.id: "stock"})
        context = {
            "provider": "sina",
            "asset_code": asset.provider_symbol,
            "asset_id": asset.id,
            "adjustment_mode": "qfq",
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

        write_fn = revise_live_stock if args.mode == "revise" else import_live_stock_incremental
        job_id = args.job_id or f"live_stock_{args.mode}-{uuid.uuid4().hex}"
        handler = build_handler(asset.id, result.records, context, write_fn)
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
