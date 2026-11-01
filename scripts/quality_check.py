"""只读数据质量检查 CLI。

用法：
    python scripts/quality_check.py --db data/demo-synthetic.db [--json]

检查程序执行失败返回 2；数据库存在且可读时，即使发现问题也返回 0。
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backend.app.db import repository
from backend.app.quality.checker import check_records


REQUIRED_TABLES = {"assets", "daily_bars", "fund_nav"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True, help="要检查的 SQLite 文件路径")
    parser.add_argument("--json", action="store_true", help="输出完整 JSON 报告")
    args = parser.parse_args()

    if not os.path.exists(args.db):
        print(f"数据库不存在：{args.db}", file=sys.stderr)
        return 2

    uri_path = os.path.abspath(args.db).replace("\\", "/")
    try:
        conn = sqlite3.connect(f"file:{uri_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
    except sqlite3.Error as exc:
        print(f"无法打开数据库：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    try:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = REQUIRED_TABLES - tables
        if missing:
            print(f"数据库结构不兼容，缺少表：{', '.join(sorted(missing))}", file=sys.stderr)
            return 2

        assets, _ = repository.list_assets(conn, limit=100000)
        asset_types = {asset.id: asset.asset_type for asset in assets}
        daily_bars = repository.query_all_daily_bars(conn)
        fund_navs = repository.query_all_fund_navs(conn)
    except sqlite3.Error as exc:
        print(f"读取数据库失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    finally:
        conn.close()

    report = check_records(daily_bars, fund_navs, asset_types)
    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"completed: {report.completed}")
        print(f"total_records: {report.total_records}")
        print(f"passed_records: {report.passed_records}")
        print(f"issue_count: {report.issue_count}")
        print("by_severity:")
        for severity in ("error", "warning", "info"):
            print(f"  {severity}: {report.by_severity.get(severity, 0)}")
        for issue in report.issues[:20]:
            print(
                f"  [{issue.severity}] {issue.rule_id} {issue.asset_id} "
                f"{issue.data_class} {issue.business_date or '-'} {issue.message}"
            )
        if report.issue_count > 20:
            print(f"  ... 另有 {report.issue_count - 20} 条问题")
    return 0


if __name__ == "__main__":
    sys.exit(main())
