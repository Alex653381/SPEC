"""AKShare 阶段 0 数据源验证脚本。

用途：对股票、指数、场内 ETF、场外基金的代表性代码，实测 AKShare
各接口的可用性、返回字段、历史覆盖、复权口径、单位与数据质量。

运行：
    python scripts/validate_akshare.py --no-em   # 仅新浪/腾讯等非东方财富通道
    python scripts/validate_akshare.py --em      # 包含东方财富通道（触发限流时请等待后重试）
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime

import pandas as pd

import akshare as ak


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE_DIR = os.path.join(ROOT, "data", "samples")
SUMMARY_PATH = os.path.join(SAMPLE_DIR, "summary.json")


def stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def num_or_none(value):
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    if isinstance(value, (int, float)):
        return value
    return str(value)


def json_safe(value):
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    return num_or_none(value)


def detect_date_column(df: pd.DataFrame):
    for candidate in ("日期", "净值日期", "date", "交易日期", "时间"):
        if candidate in df.columns:
            return candidate
    return None


def summarize(df: pd.DataFrame, name: str) -> dict:
    info: dict = {
        "case": name,
        "shape": list(df.shape),
        "columns": list(df.columns),
        "dtypes": {str(c): str(t) for c, t in df.dtypes.items()},
    }

    date_col = detect_date_column(df)
    if date_col is not None:
        parsed = pd.to_datetime(df[date_col], errors="coerce")
        info["date_column"] = date_col
        info["date_min"] = parsed.min().strftime("%Y-%m-%d") if pd.notna(parsed.min()) else None
        info["date_max"] = parsed.max().strftime("%Y-%m-%d") if pd.notna(parsed.max()) else None
        info["date_invalid_count"] = int(parsed.isna().sum())
        info["date_duplicate_count"] = int(parsed.duplicated().sum())
        info["date_weekend_count"] = int(parsed.dropna().dt.day_of_week.isin([5, 6]).sum())
        valid = parsed.dropna()
        if len(valid) > 1:
            info["date_sorted_ascending"] = bool((valid.diff().dropna() >= pd.Timedelta(0)).all())

    for col in df.columns:
        if pd.api.types.is_numeric_dtype(df[col]):
            info[f"{col}_null_count"] = int(df[col].isna().sum())
            info[f"{col}_negative_count"] = int((df[col] < 0).sum())

    ohlc = ["开盘", "最高", "最低", "收盘"]
    present = [c for c in ohlc if c in df.columns]
    if len(present) == 4:
        high = df["最高"]
        low = df["最低"]
        open_ = df["开盘"]
        close = df["收盘"]
        info["ohlc_high_below_low_count"] = int((high < low).sum())
        info["ohlc_high_below_open_count"] = int((high < open_).sum())
        info["ohlc_high_below_close_count"] = int((high < close).sum())
        info["ohlc_low_above_open_count"] = int((low > open_).sum())
        info["ohlc_low_above_close_count"] = int((low > close).sum())

    ohlc_en = ["open", "high", "low", "close"]
    if all(c in df.columns for c in ohlc_en):
        high = df["high"]
        low = df["low"]
        open_ = df["open"]
        close = df["close"]
        info["ohlc_high_below_low_count"] = int((high < low).sum())
        info["ohlc_high_below_open_count"] = int((high < open_).sum())
        info["ohlc_high_below_close_count"] = int((high < close).sum())
        info["ohlc_low_above_open_count"] = int((low > open_).sum())
        info["ohlc_low_above_close_count"] = int((low > close).sum())

    if "单位净值" in df.columns:
        nav = pd.to_numeric(df["单位净值"], errors="coerce")
        info["unit_nav_nonpositive_count"] = int((nav <= 0).sum())
        info["unit_nav_null_count"] = int(nav.isna().sum())
    if "累计净值" in df.columns:
        acc = pd.to_numeric(df["累计净值"], errors="coerce")
        info["accumulated_nav_null_count"] = int(acc.isna().sum())

    info["head"] = df.head(3).to_dict(orient="records")
    info["tail"] = df.tail(3).to_dict(orient="records")
    return info


def run_case(case: dict) -> dict:
    name = case["name"]
    print(f"[{stamp()}] RUN  {name}", flush=True)
    result = {
        "case": name,
        "category": case.get("category"),
        "interface": case.get("interface"),
        "provider": case.get("provider"),
        "params": case.get("params"),
        "ok": False,
    }
    df = None
    last_error = None
    attempts = case.get("attempts", 2)
    for attempt in range(1, attempts + 1):
        started = time.time()
        try:
            df = case["fn"]()
            elapsed = round(time.time() - started, 2)
            print(f"[{stamp()}] OK   {name} attempt={attempt} elapsed={elapsed}s", flush=True)
            result["elapsed_s"] = elapsed
            result["attempts"] = attempt
            break
        except Exception as exc:  # noqa: BLE001 - 验证脚本需要保留异常类型与原文
            elapsed = round(time.time() - started, 2)
            last_error = f"{type(exc).__name__}: {exc}"
            print(
                f"[{stamp()}] FAIL {name} attempt={attempt} elapsed={elapsed}s {last_error}",
                flush=True,
            )
            result["last_error"] = last_error
            if attempt < attempts:
                time.sleep(case.get("retry_sleep", 8))

    if df is not None:
        result["ok"] = True
        result["summary"] = summarize(df, name)
        os.makedirs(SAMPLE_DIR, exist_ok=True)
        csv_path = os.path.join(SAMPLE_DIR, f"{name}.csv")
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        result["csv_path"] = os.path.relpath(csv_path, ROOT)
        result["rows"] = int(len(df))
    else:
        result["ok"] = False
        result["last_error"] = last_error
    return result


def build_cases(include_em: bool) -> list[dict]:
    cases: list[dict] = []

    def add(name, category, interface, provider, fn, params=None):
        cases.append(
            {
                "name": name,
                "category": category,
                "interface": interface,
                "provider": provider,
                "params": params,
                "fn": fn,
            }
        )

    # 股票：新浪（不复权 / 前复权 / 后复权）与腾讯（前复权）。
    add(
        "stock_sina_000001_raw",
        "stock",
        "stock_zh_a_daily",
        "sina",
        lambda: ak.stock_zh_a_daily(symbol="sz000001", start_date="19900101", end_date="21000118", adjust=""),
        {"symbol": "sz000001", "adjust": ""},
    )
    add(
        "stock_sina_000001_qfq",
        "stock",
        "stock_zh_a_daily",
        "sina",
        lambda: ak.stock_zh_a_daily(symbol="sz000001", start_date="19900101", end_date="21000118", adjust="qfq"),
        {"symbol": "sz000001", "adjust": "qfq"},
    )
    add(
        "stock_sina_000001_hfq",
        "stock",
        "stock_zh_a_daily",
        "sina",
        lambda: ak.stock_zh_a_daily(symbol="sz000001", start_date="19900101", end_date="21000118", adjust="hfq"),
        {"symbol": "sz000001", "adjust": "hfq"},
    )
    add(
        "stock_sina_600519_qfq",
        "stock",
        "stock_zh_a_daily",
        "sina",
        lambda: ak.stock_zh_a_daily(symbol="sh600519", start_date="19900101", end_date="21000118", adjust="qfq"),
        {"symbol": "sh600519", "adjust": "qfq"},
    )
    add(
        "stock_tx_000001_qfq",
        "stock",
        "stock_zh_a_hist_tx",
        "tencent",
        lambda: ak.stock_zh_a_hist_tx(symbol="sz000001", start_date="19900101", end_date="20500101", adjust="qfq"),
        {"symbol": "sz000001", "adjust": "qfq"},
    )

    # 指数：新浪。
    add(
        "index_sina_sh000001",
        "index",
        "stock_zh_index_daily",
        "sina",
        lambda: ak.stock_zh_index_daily(symbol="sh000001"),
        {"symbol": "sh000001"},
    )
    add(
        "index_sina_sz399001",
        "index",
        "stock_zh_index_daily",
        "sina",
        lambda: ak.stock_zh_index_daily(symbol="sz399001"),
        {"symbol": "sz399001"},
    )
    add(
        "index_tx_sh000001",
        "index",
        "stock_zh_index_daily_tx",
        "tencent",
        lambda: ak.stock_zh_index_daily_tx(symbol="sh000001"),
        {"symbol": "sh000001"},
    )

    # 场内 ETF：新浪。
    add(
        "etf_sina_510300",
        "etf",
        "fund_etf_hist_sina",
        "sina",
        lambda: ak.fund_etf_hist_sina(symbol="sh510300"),
        {"symbol": "sh510300"},
    )
    add(
        "etf_sina_159915",
        "etf",
        "fund_etf_hist_sina",
        "sina",
        lambda: ak.fund_etf_hist_sina(symbol="sz159915"),
        {"symbol": "sz159915"},
    )

    # 场外开放式基金：东方财富天天基金（与 push2 行情端点不同，单独验证）。
    add(
        "fund_em_110022_unit_nav",
        "open_fund",
        "fund_open_fund_info_em",
        "eastmoney_fund",
        lambda: ak.fund_open_fund_info_em(symbol="110022", indicator="单位净值走势"),
        {"symbol": "110022", "indicator": "单位净值走势"},
    )
    add(
        "fund_em_110022_acc_nav",
        "open_fund",
        "fund_open_fund_info_em",
        "eastmoney_fund",
        lambda: ak.fund_open_fund_info_em(symbol="110022", indicator="累计净值走势"),
        {"symbol": "110022", "indicator": "累计净值走势"},
    )
    add(
        "fund_em_000001_unit_nav",
        "open_fund",
        "fund_open_fund_info_em",
        "eastmoney_fund",
        lambda: ak.fund_open_fund_info_em(symbol="000001", indicator="单位净值走势"),
        {"symbol": "000001", "indicator": "单位净值走势"},
    )

    # 资产识别 / 元数据 / 快照。
    add(
        "meta_stock_code_name",
        "stock",
        "stock_info_a_code_name",
        "exchange",
        lambda: ak.stock_info_a_code_name(),
        {},
    )
    add(
        "meta_index_list",
        "index",
        "index_stock_info",
        "eastmoney",
        lambda: ak.index_stock_info(),
        {},
    )
    add(
        "meta_fund_name_em",
        "open_fund",
        "fund_name_em",
        "eastmoney_fund",
        lambda: ak.fund_name_em(),
        {},
    )
    add(
        "meta_etf_category_sina",
        "etf",
        "fund_etf_category_sina",
        "sina",
        lambda: ak.fund_etf_category_sina(symbol="ETF基金"),
        {"symbol": "ETF基金"},
    )
    add(
        "meta_open_fund_daily_em",
        "open_fund",
        "fund_open_fund_daily_em",
        "eastmoney_fund",
        lambda: ak.fund_open_fund_daily_em(),
        {},
    )

    if include_em:
        # 东方财富 push2 行情端点：已观测到限流，纳入正式验证并记录。
        add(
            "stock_em_000001_qfq",
            "stock",
            "stock_zh_a_hist",
            "eastmoney_push2his",
            lambda: ak.stock_zh_a_hist(symbol="000001", period="daily", start_date="19700101", end_date="20500101", adjust="qfq"),
            {"symbol": "000001", "period": "daily", "adjust": "qfq"},
        )
        add(
            "index_em_000300",
            "index",
            "index_zh_a_hist",
            "eastmoney_push2his",
            lambda: ak.index_zh_a_hist(symbol="000300", period="daily", start_date="19700101", end_date="22220101"),
            {"symbol": "000300", "period": "daily"},
        )
        add(
            "etf_em_510300_qfq",
            "etf",
            "fund_etf_hist_em",
            "eastmoney_push2his",
            lambda: ak.fund_etf_hist_em(symbol="510300", period="daily", start_date="19700101", end_date="20500101", adjust="qfq"),
            {"symbol": "510300", "period": "daily", "adjust": "qfq"},
        )
        add(
            "spot_stock_em",
            "stock",
            "stock_zh_a_spot_em",
            "eastmoney_push2",
            lambda: ak.stock_zh_a_spot_em(),
            {},
        )
        add(
            "meta_stock_em_000001",
            "stock",
            "stock_individual_info_em",
            "eastmoney",
            lambda: ak.stock_individual_info_em(symbol="000001"),
            {"symbol": "000001"},
        )
        add(
            "spot_etf_em",
            "etf",
            "fund_etf_spot_em",
            "eastmoney_push2",
            lambda: ak.fund_etf_spot_em(),
            {},
        )
    return cases


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--em", action="store_true", help="包含东方财富通道")
    parser.add_argument("--no-em", dest="em", action="store_false")
    parser.add_argument("--only", help="只运行名称包含该子串的用例")
    parser.set_defaults(em=False)
    args = parser.parse_args()

    print(f"[{stamp()}] akshare={ak.__version__} pandas={pd.__version__}", flush=True)
    cases = build_cases(include_em=args.em)
    if args.only:
        cases = [c for c in cases if args.only in c["name"]]
    results = []
    for case in cases:
        results.append(run_case(case))
        time.sleep(1.5)

    os.makedirs(SAMPLE_DIR, exist_ok=True)
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "akshare_version": ak.__version__,
        "pandas_version": pd.__version__,
        "results": json_safe(results),
    }
    with open(SUMMARY_PATH, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    print(f"[{stamp()}] summary written to {os.path.relpath(SUMMARY_PATH, ROOT)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
