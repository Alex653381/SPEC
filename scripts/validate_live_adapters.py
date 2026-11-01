"""四类资产真实接口小规模验证脚本。

默认不联网：数据使用许可尚未确认，必须显式传入 --live 才可能发起单次请求。
每类接口最多请求一次，不重试、不并发、不批量、不写正式数据库。
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
from datetime import date, datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backend.app.providers.sina import SinaStockAdapter
from backend.app.quality.checker import check_records
from backend.app.services.live_validation import (
    classify_error,
    is_retryable_error,
    recent_window,
    redact_error_detail,
)


SAMPLES_DIR = os.path.join(ROOT, "data", "samples")

STOCK_FIELD_MAPPING = {
    "date": "trade_date",
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "volume": "volume",
    "amount": "turnover",
    "adjustment_mode": "qfq",
}


CAPABILITIES = {
    "stock": {
        "interface": "ak.stock_zh_a_daily(symbol='sz000001', adjust='qfq')",
        "supports_date_range": True,
    },
    "index": {
        "interface": "ak.stock_zh_index_daily(symbol='sh000001')",
        "supports_date_range": False,
    },
    "etf": {
        "interface": "ak.fund_etf_hist_sina(symbol='sh510300')",
        "supports_date_range": False,
    },
    "fund": {
        "interface": "ak.fund_open_fund_info_em(symbol='110022', indicator='单位净值走势')",
        "supports_date_range": False,
    },
}


def _stock_fetcher(code, start, end):
    import akshare as ak

    df = ak.stock_zh_a_daily(
        symbol=code,
        start_date=start.strftime("%Y%m%d"),
        end_date=end.strftime("%Y%m%d"),
        adjust="qfq",
    )
    return df.to_dict("records")


def run_stock(
    start: date,
    end: date,
    code: str = "sz000001",
    retries: int = 1,
    fetcher=None,
) -> dict:
    fetch = fetcher or _stock_fetcher
    attempts = max(1, retries + 1)
    last_error = None
    last_category = "unknown"

    for attempt in range(1, attempts + 1):
        previous_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(20)
        try:
            adapter = SinaStockAdapter(lambda _asset_id, _start, _end: fetch(code, _start, _end))
            result = adapter.fetch_history(f"live-stock-{code}", start=start, end=end)
            quality = check_records(result.records, [], {f"live-stock-{code}": "stock"})
            return {
                "adapter": result.adapter,
                "asset_code": code,
                "fetched_at": result.fetched_at.isoformat(),
                "fetched_rows": result.fetched_rows,
                "converted_rows": len(result.records),
                "skipped_rows": len(result.errors),
                "errors": [f"{e.row_index}: {e.code}: {e.message}" for e in result.errors],
                "date_min": min(r.trade_date.isoformat() for r in result.records) if result.records else None,
                "date_max": max(r.trade_date.isoformat() for r in result.records) if result.records else None,
                "adjustment_mode": "qfq",
                "field_mapping": STOCK_FIELD_MAPPING,
                "units": {"volume": "shares", "turnover": "yuan"},
                "quality": {
                    "total_records": quality.total_records,
                    "passed_records": quality.passed_records,
                    "issue_count": quality.issue_count,
                    "by_severity": quality.by_severity,
                    "issues": [
                        {
                            "rule_id": issue.rule_id,
                            "severity": issue.severity,
                            "business_date": issue.business_date,
                            "field": issue.field,
                            "message": issue.message,
                        }
                        for issue in quality.issues
                    ],
                },
                "database_written": False,
                "attempts": attempt,
            }
        except Exception as exc:  # noqa: BLE001 - 验证脚本记录错误类型，不重试限流类错误
            last_error = exc
            last_category = classify_error(exc)
            if attempt >= attempts or not is_retryable_error(last_category):
                break
        finally:
            socket.setdefaulttimeout(previous_timeout)

    return {
        "status": "error",
        "adapter": "sina",
        "asset_code": code,
        "adjustment_mode": "qfq",
        "field_mapping": STOCK_FIELD_MAPPING,
        "error_category": last_category,
        "error_type": type(last_error).__name__ if last_error else None,
        "error_detail": redact_error_detail(last_error) if last_error else None,
        "attempts": attempt,
        "database_written": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset", choices=list(CAPABILITIES), required=True)
    parser.add_argument("--code", default="sz000001", help="股票代码，仅 --asset stock 时使用，例如 sz000001")
    parser.add_argument("--days", type=int, default=10)
    parser.add_argument("--start", help="YYYY-MM-DD，默认按 --days 计算")
    parser.add_argument("--end", help="YYYY-MM-DD，默认今天")
    parser.add_argument("--retries", type=int, default=1, help="网络/超时类错误的最多重试次数")
    parser.add_argument("--save", action="store_true", help="将脱敏摘要保存到 data/samples/")
    parser.add_argument("--live", action="store_true", help="显式确认后发起单次真实请求")
    args = parser.parse_args()

    if args.start or args.end:
        start = date.fromisoformat(args.start) if args.start else None
        end = date.fromisoformat(args.end) if args.end else date.today()
        if start is None:
            start = end - __import__("datetime").timedelta(days=args.days)
    else:
        start, end = recent_window(days=args.days)

    capability = CAPABILITIES[args.asset]
    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "asset": args.asset,
        "interface": capability["interface"],
        "supports_date_range": capability["supports_date_range"],
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "live_request_executed": False,
        "database_written": False,
    }

    if not args.live:
        summary["status"] = "not_executed"
        summary["reason"] = "数据使用许可尚未确认，未发起真实请求"
    elif not capability["supports_date_range"]:
        summary["status"] = "blocked"
        summary["reason"] = "接口不支持日期范围，真实请求会返回全量历史，超出本轮限制"
    else:
        result = run_stock(start, end, code=args.code, retries=args.retries)
        summary["result"] = result
        if result.get("status") == "error":
            summary["status"] = "error"
            summary["error_category"] = result.get("error_category")
            summary["error_type"] = result.get("error_type")
        else:
            summary["status"] = "ok"
            summary["live_request_executed"] = True

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.save:
        os.makedirs(SAMPLES_DIR, exist_ok=True)
        path = os.path.join(SAMPLES_DIR, "live-adapter-validation.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(summary, fh, ensure_ascii=False, indent=2)
        print(f"saved -> {os.path.relpath(path, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
