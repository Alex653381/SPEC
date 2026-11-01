"""MVP 数据源验证：连续性、增量与稳定性。

只验证进入最小可用版本所需的四类代表性资产。输出精简 JSON，不保存全量原始数据。
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta

import pandas as pd

import akshare as ak


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "data", "samples")
OUT_PATH = os.path.join(OUT_DIR, "mvp-validation-summary.json")
TODAY = datetime.now()


def norm_dates(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce").dt.normalize()


def date_col_of(df: pd.DataFrame) -> str | None:
    for candidate in ("日期", "净值日期", "date", "交易日期", "时间"):
        if candidate in df.columns:
            return candidate
    return None


def describe(df: pd.DataFrame) -> dict:
    info: dict = {"shape": list(df.shape), "columns": list(df.columns)}
    dcol = date_col_of(df)
    if dcol is not None:
        dates = norm_dates(df[dcol])
        info["date_column"] = dcol
        info["date_min"] = dates.min().strftime("%Y-%m-%d") if pd.notna(dates.min()) else None
        info["date_max"] = dates.max().strftime("%Y-%m-%d") if pd.notna(dates.max()) else None
        info["date_invalid_count"] = int(dates.isna().sum())
        info["date_duplicate_count"] = int(dates.duplicated().sum())
        info["date_weekend_count"] = int(dates.dropna().dt.day_of_week.isin([5, 6]).sum())
        if len(dates.dropna()) > 1:
            info["date_sorted_ascending"] = bool(
                (dates.dropna().diff().dropna() >= pd.Timedelta(0)).all()
            )

    for col in df.columns:
        if pd.api.types.is_numeric_dtype(df[col]):
            info[f"{col}_null_count"] = int(df[col].isna().sum())
            info[f"{col}_negative_count"] = int((df[col] < 0).sum())

    if all(c in df.columns for c in ("open", "high", "low", "close")):
        high, low, open_, close = df["high"], df["low"], df["open"], df["close"]
        info["ohlc_high_below_low_count"] = int((high < low).sum())
        info["ohlc_high_below_open_count"] = int((high < open_).sum())
        info["ohlc_high_below_close_count"] = int((high < close).sum())
        info["ohlc_low_above_open_count"] = int((low > open_).sum())
        info["ohlc_low_above_close_count"] = int((low > close).sum())

    if "单位净值" in df.columns:
        nav = pd.to_numeric(df["单位净值"], errors="coerce")
        info["unit_nav_nonpositive_count"] = int((nav <= 0).sum())
    return info


def fetch(fn, attempts: int = 3, sleep: float = 2.0) -> tuple[pd.DataFrame | None, dict]:
    error = None
    times = []
    last_df = None
    for attempt in range(1, attempts + 1):
        started = time.time()
        try:
            last_df = fn()
            times.append(round(time.time() - started, 2))
            return last_df, {"ok": True, "attempts": attempt, "elapsed_s": times}
        except Exception as exc:  # noqa: BLE001 - 保留异常类型与原文用于诊断
            times.append(round(time.time() - started, 2))
            error = f"{type(exc).__name__}: {exc}"
            if attempt < attempts:
                time.sleep(sleep)
    return None, {"ok": False, "attempts": attempts, "elapsed_s": times, "error": error}


def load_saved(rel: str) -> pd.DataFrame | None:
    path = os.path.join(OUT_DIR, rel)
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path)
    return df


def compare_close(fresh: pd.DataFrame, saved: pd.DataFrame | None, date_col: str, value_col: str) -> dict:
    if saved is None:
        return {"checked": False, "reason": "saved sample not found"}
    try:
        a = fresh[[date_col, value_col]].copy()
        b = saved[[date_col, value_col]].copy()
        a[date_col] = norm_dates(a[date_col])
        b[date_col] = norm_dates(b[date_col])
        merged = a.merge(b, on=date_col, suffixes=("_fresh", "_saved"))
        diff = (pd.to_numeric(merged[f"{value_col}_fresh"], errors="coerce")
                - pd.to_numeric(merged[f"{value_col}_saved"], errors="coerce")).abs()
        mismatches = int((diff > 1e-6).sum())
        return {"checked": True, "overlap_rows": int(len(merged)), "mismatch_rows": mismatches}
    except Exception as exc:  # noqa: BLE001
        return {"checked": False, "reason": f"{type(exc).__name__}: {exc}"}


def gap_analysis(dates: pd.Series, calendar, label: str) -> dict:
    date_idx = pd.DatetimeIndex(dates.dropna().drop_duplicates().sort_values())
    calendar_idx = pd.DatetimeIndex(calendar)
    lo = date_idx.min()
    hi = date_idx.max()
    cal = calendar_idx[(calendar_idx >= lo) & (calendar_idx <= hi)]
    missing = cal.difference(date_idx)
    runs = []
    if len(missing):
        cur = [missing[0]]
        for d in missing[1:]:
            if d - cur[-1] == timedelta(days=1):
                cur.append(d)
            else:
                runs.append(cur)
                cur = [d]
        runs.append(cur)
    result = {
        "label": label,
        "calendar_days_in_range": int(len(cal)),
        "missing_trading_days": int(len(missing)),
        "gap_runs": int(len(runs)),
        "largest_gap_run": int(max((len(r) for r in runs), default=0)),
        "first_gap_runs": [[d.strftime("%Y-%m-%d") for d in r][:3] for r in runs[:5]],
    }
    return result


def main() -> int:
    # 以新浪上证指数日线作为 A 股交易日历基准。
    index_df, index_status = fetch(lambda: ak.stock_zh_index_daily(symbol="sh000001"), attempts=2)
    if index_df is None:
        print("index calendar fetch failed", index_status, file=sys.stderr)
        return 1
    calendar = norm_dates(index_df["date"]).dropna().sort_values().reset_index(drop=True)

    assets = [
        {
            "id": "stock_000001",
            "category": "A股股票",
            "name": "平安银行",
            "symbol": "000001",
            "interface": "stock_zh_a_daily(symbol='sz000001', adjust='qfq')",
            "date_col": "date",
            "value_col": "close",
            "saved_csv": "stock_sina_000001_qfq.csv",
            "fn": lambda: ak.stock_zh_a_daily(symbol="sz000001", start_date="19900101", end_date="21000118", adjust="qfq"),
            "incremental": lambda: ak.stock_zh_a_daily(
                symbol="sz000001",
                start_date=(TODAY - timedelta(days=90)).strftime("%Y%m%d"),
                end_date=TODAY.strftime("%Y%m%d"),
                adjust="qfq",
            ),
        },
        {
            "id": "index_sh000001",
            "category": "宽基指数",
            "name": "上证指数",
            "symbol": "000001",
            "interface": "stock_zh_index_daily(symbol='sh000001')",
            "date_col": "date",
            "value_col": "close",
            "saved_csv": "index_sina_sh000001.csv",
            "fn": lambda: ak.stock_zh_index_daily(symbol="sh000001"),
            "incremental": None,
        },
        {
            "id": "etf_510300",
            "category": "场内ETF",
            "name": "沪深300ETF",
            "symbol": "510300",
            "interface": "fund_etf_hist_sina(symbol='sh510300')",
            "date_col": "date",
            "value_col": "close",
            "saved_csv": "etf_sina_510300.csv",
            "fn": lambda: ak.fund_etf_hist_sina(symbol="sh510300"),
            "incremental": None,
        },
        {
            "id": "fund_110022",
            "category": "场外开放式基金",
            "name": "易方达消费行业股票",
            "symbol": "110022",
            "interface": "fund_open_fund_info_em(symbol='110022', indicator='单位净值走势')",
            "date_col": "净值日期",
            "value_col": "单位净值",
            "saved_csv": "fund_em_110022_unit_nav.csv",
            "fn": lambda: ak.fund_open_fund_info_em(symbol="110022", indicator="单位净值走势"),
            "incremental": None,
        },
    ]

    results = []
    for asset in assets:
        print(f"== {asset['id']}", flush=True)
        df, status = fetch(asset["fn"], attempts=3)
        row = {
            "id": asset["id"],
            "category": asset["category"],
            "name": asset["name"],
            "symbol": asset["symbol"],
            "interface": asset["interface"],
            "stability": status,
        }
        if df is None:
            row["result"] = "failed"
            results.append(row)
            print("   FAIL", status, flush=True)
            continue

        row["result"] = "ok"
        row["describe"] = describe(df)
        dates = norm_dates(df[asset["date_col"]])
        row["gap"] = gap_analysis(dates, calendar, asset["category"])
        row["revision_same_day"] = compare_close(
            df, load_saved(asset["saved_csv"]), asset["date_col"], asset["value_col"]
        )

        if asset["incremental"] is not None:
            inc_df, inc_status = fetch(asset["incremental"], attempts=2)
            if inc_df is None:
                row["incremental"] = {"supported": "function failed", "status": inc_status}
            else:
                row["incremental"] = {
                    "supported": True,
                    "rows": int(len(inc_df)),
                    "date_min": norm_dates(inc_df[asset["date_col"]]).min().strftime("%Y-%m-%d"),
                    "date_max": norm_dates(inc_df[asset["date_col"]]).max().strftime("%Y-%m-%d"),
                    "within_requested_window": bool(
                        norm_dates(inc_df[asset["date_col"]]).min()
                        >= pd.Timestamp((TODAY - timedelta(days=90)).date())
                    ),
                }
        else:
            row["incremental"] = {
                "supported": False,
                "note": "接口无日期参数，返回全量历史；增量需客户端按最新日期合并去重",
            }

        results.append(row)
        print("   OK", status["elapsed_s"], "rows", len(df), flush=True)

    os.makedirs(OUT_DIR, exist_ok=True)
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "akshare_version": ak.__version__,
        "pandas_version": pd.__version__,
        "calendar_source": "index_sina_sh000001",
        "results": results,
    }
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    print("summary ->", os.path.relpath(OUT_PATH, ROOT), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
