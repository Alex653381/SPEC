"""真实指数/ETF 基准资产受控试点入库。只允许写入 data/live-benchmark.db。"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import uuid
from datetime import date

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
from backend.app.providers.tencent import TencentIndexAdapter
from backend.app.quality.checker import check_records
from backend.app.schemas.records import AssetRecord
from backend.app.services.live_validation import (
    classify_error,
    fetch_with_retry,
    redact_error_detail,
)
from backend.app.workers.jobs import TaskExecutionError, TaskResult, run_job_once
from backend.app.workers.live_import import import_live_daily_incremental


PILOT_DB_NAME = "live-benchmark.db"
ALLOWED_CODES = {"sh000001": ("000001", "上证指数", "SH")}


def expected_benchmark_path() -> str:
    return os.path.abspath(os.path.join(ROOT, "data", PILOT_DB_NAME))


def resolve_benchmark_path(db_arg: str) -> str:
    expected = expected_benchmark_path()
    given = os.path.abspath(db_arg)
    if os.path.normcase(given) != os.path.normcase(expected):
        raise ValueError(f"拒绝写入非预期数据库：{given}；本阶段只允许 {expected}")
    return given


def _tencent_index_fetcher(code, start, end):
    import akshare as ak

    df = ak.stock_zh_index_daily_tx(
        symbol=code,
        start_date=start.strftime("%Y%m%d"),
        end_date=end.strftime("%Y%m%d"),
    )
    return df.to_dict("records")


def make_benchmark_asset(code: str) -> AssetRecord:
    code = code.strip().lower()
    if code not in ALLOWED_CODES:
        raise ValueError(f"不支持的基准资产代码：{code}")
    symbol, name, market = ALLOWED_CODES[code]
    return AssetRecord(
        id=f"index-{code}",
        symbol=symbol,
        name=name,
        asset_type="index",
        market=market,
        currency="CNY",
        provider="tencent",
        provider_symbol=code,
        adjustment_mode="none",
        price_semantics="index_points",
        volume_unit="shares",
        is_active=True,
    )


def ensure_benchmark_asset(conn, asset: AssetRecord) -> None:
    existing = repository.get_asset(conn, asset.id)
    if existing is None:
        with conn:
            repository.insert_asset(conn, asset)
        return
    expected = (asset.symbol, asset.asset_type, asset.provider, asset.adjustment_mode)
    actual = (existing.symbol, existing.asset_type, existing.provider, existing.adjustment_mode)
    if actual != expected:
        raise ValueError(f"资产 {asset.id} 已存在但元数据不一致：expected={expected} actual={actual}")


def build_handler(asset_id: str, records, context: dict):
    def handler(conn, job_id: str) -> TaskResult:
        del job_id
        try:
            result = import_live_daily_incremental(conn, asset_id, "index", records)
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
    parser.add_argument("--db", required=True, help="必须是 data/live-benchmark.db")
    parser.add_argument("--code", default="sh000001", help="本阶段固定为 sh000001")
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD")
    parser.add_argument("--max-days", type=int, default=400)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--backoff", type=float, default=1.0)
    parser.add_argument("--job-id", default=None)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()

    try:
        pilot_path = resolve_benchmark_path(args.db)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    try:
        start = date.fromisoformat(args.start)
        end = date.fromisoformat(args.end)
    except ValueError:
        print("日期格式应为 YYYY-MM-DD", file=sys.stderr)
        return 2
    if start > end:
        print("日期范围无效：start 晚于 end", file=sys.stderr)
        return 2
    if (end - start).days > args.max_days:
        print(f"日期范围超过上限 {args.max_days} 天", file=sys.stderr)
        return 2
    if args.code.strip().lower() not in ALLOWED_CODES:
        print(f"本阶段只允许基准资产代码 {', '.join(ALLOWED_CODES)}", file=sys.stderr)
        return 2

    print(f"pilot_database={pilot_path}")
    print(f"asset_code={args.code.strip().lower()}")
    print(f"request_window={start.isoformat()}/{end.isoformat()}")

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

    os.makedirs(os.path.dirname(pilot_path), exist_ok=True)
    conn = init_db(pilot_path)
    try:
        asset = make_benchmark_asset(args.code)
        ensure_benchmark_asset(conn, asset)

        previous_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(20)
        try:
            adapter = TencentIndexAdapter(
                lambda _asset_id, _start, _end: _tencent_index_fetcher(
                    asset.provider_symbol, _start, _end
                )
            )
            result = fetch_with_retry(
                lambda: adapter.fetch_history(asset.id, start=start, end=end),
                retries=args.retries,
                backoff=args.backoff,
            )
        except Exception as exc:  # noqa: BLE001
            summary = {
                "status": "fetch_failed",
                "provider": "tencent",
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

        pre_quality = check_records(result.records, [], {asset.id: "index"})
        context = {
            "provider": "tencent",
            "asset_code": asset.provider_symbol,
            "asset_id": asset.id,
            "adjustment_mode": "none",
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

        job_id = args.job_id or f"live_benchmark_update-{uuid.uuid4().hex}"
        handler = build_handler(asset.id, result.records, context)
        try:
            record = run_job_once(conn, job_id, handler)
        except jobs_repository.JobStateError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        except Exception as exc:  # noqa: BLE001
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
