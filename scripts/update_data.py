"""统一手动更新入口。默认只做离线预检，显式 --live 才复用现有 CLI 发起请求。"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import date, timedelta

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backend.app.db import repository
from scripts import (
    pilot_import_benchmark as benchmark_cli,
    pilot_import_etf as etf_cli,
    pilot_import_fund as fund_cli,
    pilot_import_stock as stock_cli,
)


def _read_latest_daily(path: str, asset_id: str) -> date | None:
    if not os.path.exists(path):
        return None
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = repository.query_daily_bars(conn, asset_id)
        return max((row.trade_date for row in rows), default=None)
    finally:
        conn.close()


ASSET_SPECS = {
    "stock": {
        "script": "pilot_import_stock.py",
        "db": "data/live-pilot.db",
        "resolver": stock_cli.resolve_pilot_path,
        "code": "sz000001",
        "asset_id": "stock-000001",
        "latest": stock_cli.read_latest_trade_date,
    },
    "fund": {
        "script": "pilot_import_fund.py",
        "db": "data/live-fund-pilot.db",
        "resolver": fund_cli.resolve_fund_pilot_path,
        "code": "110022",
        "asset_id": "fund-110022",
        "latest": fund_cli.read_latest_fund_nav_date,
    },
    "index": {
        "script": "pilot_import_benchmark.py",
        "db": "data/live-benchmark.db",
        "resolver": benchmark_cli.resolve_benchmark_path,
        "code": "sh000001",
        "asset_id": "index-sh000001",
        "latest": lambda path, asset_id: _read_latest_daily(path, asset_id),
    },
    "etf": {
        "script": "pilot_import_etf.py",
        "db": "data/live-etf-pilot.db",
        "resolver": etf_cli.resolve_etf_path,
        "code": "510300",
        "asset_id": "etf-510300-live",
        "latest": lambda path, asset_id: _read_latest_daily(path, asset_id),
    },
}


def build_targets(asset_types: list[str], code: str | None) -> list[dict]:
    targets = []
    for asset_type in asset_types:
        spec = ASSET_SPECS[asset_type]
        target_code = code or spec["code"]
        targets.append({**spec, "asset_type": asset_type, "code": target_code})
    return targets


def resolve_window(latest: date | None, start: date | None, end: date | None) -> tuple[date, date] | None:
    if start is not None and end is not None:
        return start, end
    if latest is None:
        raise ValueError("数据库尚无记录，请显式指定 --start 和 --end")
    return latest + timedelta(days=1), date.today()


def parse_cli_json(output: str) -> dict | None:
    start = output.find("{")
    end = output.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        return json.loads(output[start : end + 1])
    except json.JSONDecodeError:
        return None


def run_target(target: dict, start: date, end: date, args) -> tuple[int, dict | None]:
    command = [
        sys.executable,
        os.path.join(ROOT, "scripts", target["script"]),
        "--db",
        target["db"],
        "--code",
        target["code"],
        "--start",
        start.isoformat(),
        "--end",
        end.isoformat(),
        "--live",
        "--retries",
        str(args.retries),
        "--backoff",
        str(args.backoff),
    ]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    parsed = parse_cli_json(completed.stdout) or parse_cli_json(completed.stderr)
    return completed.returncode, parsed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset-type", choices=sorted(ASSET_SPECS), required=True)
    parser.add_argument("--code", default=None)
    parser.add_argument("--start", default=None, help="YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="YYYY-MM-DD")
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--backoff", type=float, default=1.0)
    parser.add_argument("--live", action="store_true", help="显式确认后发起真实请求")
    args = parser.parse_args()

    targets = build_targets([args.asset_type], args.code)
    reports = []
    for target in targets:
        latest = target["latest"](os.path.join(ROOT, target["db"]), target["asset_id"])
        try:
            window = resolve_window(latest, _parse_date(args.start), _parse_date(args.end))
        except ValueError as exc:
            reports.append({"asset_type": target["asset_type"], "status": "preflight_failed", "message": str(exc)})
            continue
        reports.append(
            {
                "asset_type": target["asset_type"],
                "asset_code": target["code"],
                "database": os.path.abspath(os.path.join(ROOT, target["db"])),
                "latest_date": latest.isoformat() if latest else None,
                "window": (
                    {"start": window[0].isoformat(), "end": window[1].isoformat()}
                    if window
                    else None
                ),
            }
        )

    print(json.dumps({"status": "preflight", "items": reports}, ensure_ascii=False, indent=2))
    if not args.live:
        return 0

    for report, target in zip(reports, targets):
        if report.get("window") is None:
            print(json.dumps({**report, "status": "skipped"}, ensure_ascii=False))
            continue
        start = date.fromisoformat(report["window"]["start"])
        end = date.fromisoformat(report["window"]["end"])
        code, parsed = run_target(target, start, end, args)
        report["exit_code"] = code
        report["result"] = parsed
        print(json.dumps(report, ensure_ascii=False, indent=2))
        category = (parsed or {}).get("error_category") or (parsed or {}).get("result", {}).get("error_category")
        if category in ("rate_limit", "http_error"):
            print("检测到不可重试错误，停止后续资产更新", file=sys.stderr)
            return 1
    return 0


def _parse_date(value: str | None) -> date | None:
    if value is None:
        return None
    return date.fromisoformat(value)


if __name__ == "__main__":
    sys.exit(main())
