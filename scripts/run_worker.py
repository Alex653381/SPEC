"""本地手动触发一次后台任务。"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import uuid

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
from backend.app.workers.jobs import run_job_once
from backend.app.workers.quality_task import quality_check_handler
from backend.app.workers.synthetic_import import synthetic_import_handler
from backend.tests import fixtures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--task", choices=("quality_check", "synthetic_import_stock", "synthetic_import_fund"), required=True)
    parser.add_argument("--batch", choices=("small", "full"), default="small")
    parser.add_argument("--job-id", default=None)
    args = parser.parse_args()

    if not os.path.exists(args.db):
        print(f"数据库不存在：{args.db}", file=sys.stderr)
        return 2

    conn = init_db(args.db)
    job_id = args.job_id or f"{args.task}-{uuid.uuid4().hex}"
    try:
        handler = _build_handler(args.task, args.batch)
        record = run_job_once(conn, job_id, handler)
    except jobs_repository.JobStateError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except sqlite3.Error as exc:
        print(f"任务执行失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    finally:
        conn.close()

    output = {
        "job_id": record.id,
        "job_type": record.job_type,
        "status": record.status,
        "processed_records": record.processed_records,
        "succeeded_records": record.succeeded_records,
        "error_code": record.error_code,
        "error_summary": record.error_summary,
        "execution_summary": record.execution_summary,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if record.status == "success" else 1


def _build_handler(task: str, batch: str):
    if task == "quality_check":
        return quality_check_handler
    if task == "synthetic_import_stock":
        asset_id = "stock-000001"
        records = fixtures.build_stock_bars() if batch == "full" else fixtures.build_stock_bars()[:5]
        data_class = "daily_bar"
    else:
        asset_id = "fund-110022"
        records = fixtures.build_fund_navs() if batch == "full" else fixtures.build_fund_navs()[:5]
        data_class = "fund_nav"

    def handler(conn, job_id):
        asset = repository.get_asset(conn, asset_id)
        if asset is None:
            raise jobs_repository.JobStateError(f"资产 {asset_id} 不存在，请先初始化演示数据库")
        return synthetic_import_handler(conn, job_id, asset_id, records, data_class)

    return handler


if __name__ == "__main__":
    sys.exit(main())
