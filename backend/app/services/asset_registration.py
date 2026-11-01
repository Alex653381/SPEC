"""按代码新增真实股票或 ETF 资产，只抓取短区间并写入对应试点数据库。"""

from __future__ import annotations

import socket
from datetime import date

from backend.app.db.database import init_db
from backend.app.providers.fund_lsjz import LsjzFundAdapter, eastmoney_lsjz_fetcher
from backend.app.providers.sina import SinaETFAdapter, SinaStockAdapter
from backend.app.providers.tencent import TencentIndexAdapter
from backend.app.quality.checker import check_records
from backend.app.schemas.records import AssetRecord
from backend.app.services.live_validation import (
    classify_error,
    fetch_with_retry,
    redact_error_detail,
)
from backend.app.workers.live_fund_import import import_live_fund_incremental
from backend.app.workers.live_import import import_live_daily_incremental
from scripts import (
    pilot_import_benchmark as benchmark_cli,
    pilot_import_etf as etf_cli,
    pilot_import_fund as fund_cli,
    pilot_import_stock as stock_cli,
)


def _stock_fetcher(code, start, end):
    return stock_cli._stock_fetcher(code, start, end)


def _sina_etf_fetcher(code, start, end):
    import akshare as ak

    del start, end
    df = ak.fund_etf_hist_sina(symbol=code)
    return df.to_dict("records")


def _stock_asset(code: str, name: str, market: str) -> AssetRecord:
    symbol = code[2:]
    return AssetRecord(
        id=f"stock-{symbol}",
        symbol=symbol,
        name=name or symbol,
        asset_type="stock",
        market=market,
        currency="CNY",
        provider="sina",
        provider_symbol=code,
        adjustment_mode="qfq",
        price_semantics="close",
        volume_unit="shares",
        is_active=True,
    )


def _etf_asset(code: str, name: str, market: str) -> AssetRecord:
    prefix = "sh" if market == "SH" else "sz"
    return AssetRecord(
        id=f"etf-{code}-live",
        symbol=code,
        name=name or code,
        asset_type="etf",
        market=market,
        currency="CNY",
        provider="sina",
        provider_symbol=prefix + code,
        adjustment_mode="none",
        price_semantics="close",
        volume_unit="shares",
        is_active=True,
    )


def _index_asset(code: str, name: str, market: str) -> AssetRecord:
    return AssetRecord(
        id=f"index-{code}",
        symbol=code[2:],
        name=name or code,
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


def _fund_asset(code: str, name: str) -> AssetRecord:
    return AssetRecord(
        id=f"fund-{code}",
        symbol=code,
        name=name or code,
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


def normalize_index_code(code: str) -> str:
    normalized = code.strip().lower()
    if len(normalized) == 6 and normalized.isdigit():
        normalized = ("sh" if normalized.startswith("0") else "sz") + normalized
    return normalized


def register_asset(
    asset_type: str,
    code: str,
    name: str | None,
    market: str | None,
    start: date,
    end: date,
    retries: int = 1,
    backoff: float = 1.0,
) -> dict:
    if asset_type == "stock":
        normalized = normalize_index_code(code)
        if len(normalized) != 8 or normalized[:2] not in ("sh", "sz", "bj") or not normalized[2:].isdigit():
            raise ValueError("股票代码格式应为 sh/sz/bj 加 6 位数字")
        market_value = market or normalized[:2].upper()
        asset = _stock_asset(normalized, name or "", market_value)
        path = stock_cli.resolve_pilot_path("data/live-pilot.db")
        adapter = SinaStockAdapter(
            lambda _asset_id, _start, _end: _stock_fetcher(asset.provider_symbol, _start, _end)
        )
        data_class = "stock"
        import_fn = lambda conn, asset_id, records: import_live_daily_incremental(conn, asset_id, "stock", records)
    elif asset_type == "etf":
        normalized = code.strip()
        if len(normalized) != 6 or not normalized.isdigit():
            raise ValueError("ETF 代码应为 6 位数字")
        market_value = market or ("SH" if normalized.startswith("5") else "SZ")
        asset = _etf_asset(normalized, name or "", market_value)
        path = etf_cli.resolve_etf_path("data/live-etf-pilot.db")
        adapter = SinaETFAdapter(
            lambda _asset_id, _start, _end: _sina_etf_fetcher(asset.provider_symbol, _start, _end)
        )
        data_class = "etf"
        import_fn = lambda conn, asset_id, records: import_live_daily_incremental(conn, asset_id, "etf", records)
    elif asset_type == "index":
        normalized = code.strip().lower()
        if len(normalized) != 8 or normalized[:2] not in ("sh", "sz") or not normalized[2:].isdigit():
            raise ValueError("指数代码格式应为 sh/sz 加 6 位数字")
        market_value = market or normalized[:2].upper()
        asset = _index_asset(normalized, name or "", market_value)
        path = benchmark_cli.resolve_benchmark_path("data/live-benchmark.db")
        adapter = TencentIndexAdapter(
            lambda _asset_id, _start, _end: benchmark_cli._tencent_index_fetcher(asset.provider_symbol, _start, _end)
        )
        data_class = "index"
        import_fn = lambda conn, asset_id, records: import_live_daily_incremental(conn, asset_id, "index", records)
    elif asset_type == "fund":
        normalized = code.strip()
        if len(normalized) != 6 or not normalized.isdigit():
            raise ValueError("基金代码应为 6 位数字")
        asset = _fund_asset(normalized, name or "")
        path = fund_cli.resolve_fund_pilot_path("data/live-fund-pilot.db")
        adapter = LsjzFundAdapter(
            lambda _asset_id, _start, _end: eastmoney_lsjz_fetcher(asset.provider_symbol, _start, _end)
        )
        data_class = "open_fund"
        import_fn = import_live_fund_incremental
    else:
        raise ValueError("仅支持 stock、etf、index 和 fund")

    conn = init_db(path)
    try:
        ensure_asset(conn, asset)
        previous_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(25)
        try:
            try:
                fetched = fetch_with_retry(
                    lambda: adapter.fetch_history(asset.id, start=start, end=end),
                    retries=retries,
                    backoff=backoff,
                )
            except Exception as exc:  # noqa: BLE001
                return {
                    "status": "fetch_failed",
                    "asset_type": asset_type,
                    "asset_id": asset.id,
                    "provider": asset.provider,
                    "error_category": classify_error(exc),
                    "error_type": type(exc).__name__,
                    "error_detail": redact_error_detail(exc),
                    "database_written": False,
                }
        finally:
            socket.setdefaulttimeout(previous_timeout)

        records = fetched.records
        if asset_type == "etf":
            records = [record for record in records if start <= record.trade_date <= end]

        if data_class == "open_fund":
            pre_quality = check_records([], records, {asset.id: "open_fund"})
        else:
            pre_quality = check_records(records, [], {asset.id: data_class})
        if not records:
            return {
                "status": "empty",
                "asset_type": asset_type,
                "asset_id": asset.id,
                "provider": asset.provider,
                "fetched_rows": fetched.fetched_rows,
                "converted_rows": 0,
                "database_written": False,
                "quality_issue_count": 0,
            }

        result = import_fn(conn, asset.id, records)
        return {
            "status": "success",
            "asset_type": asset_type,
            "asset_id": asset.id,
            "provider": asset.provider,
            "fetched_rows": fetched.fetched_rows,
            "converted_rows": len(records),
            "quality_issue_count": pre_quality.issue_count,
            "inserted": result["inserted"],
            "skipped": result["skipped"],
            "conflicts": result["conflicts"],
            "database_written": True,
            "committed": result["committed"],
        }
    finally:
        conn.close()


def expand_asset(
    asset_type: str,
    code: str,
    start: date,
    end: date,
    retries: int = 1,
    backoff: float = 1.0,
) -> dict:
    """为已注册资产扩展历史，复用注册路径的校验、抓取和幂等导入。"""
    if asset_type == "stock":
        normalized = normalize_index_code(code)
        if len(normalized) != 8 or normalized[:2] not in ("sh", "sz", "bj") or not normalized[2:].isdigit():
            raise ValueError("股票代码格式应为 sh/sz/bj 加 6 位数字")
        market_value = normalized[:2].upper()
        asset = _stock_asset(normalized, "", market_value)
        path = stock_cli.resolve_pilot_path("data/live-pilot.db")
        adapter = SinaStockAdapter(
            lambda _asset_id, _start, _end: _stock_fetcher(asset.provider_symbol, _start, _end)
        )
        data_class = "stock"
        import_fn = lambda conn, asset_id, records: import_live_daily_incremental(conn, asset_id, "stock", records)
    elif asset_type == "etf":
        normalized = code.strip()
        if len(normalized) != 6 or not normalized.isdigit():
            raise ValueError("ETF 代码应为 6 位数字")
        market_value = "SH" if normalized.startswith("5") else "SZ"
        asset = _etf_asset(normalized, "", market_value)
        path = etf_cli.resolve_etf_path("data/live-etf-pilot.db")
        adapter = SinaETFAdapter(
            lambda _asset_id, _start, _end: _sina_etf_fetcher(asset.provider_symbol, _start, _end)
        )
        data_class = "etf"
        import_fn = lambda conn, asset_id, records: import_live_daily_incremental(conn, asset_id, "etf", records)
    elif asset_type == "index":
        normalized = code.strip().lower()
        if len(normalized) != 8 or normalized[:2] not in ("sh", "sz") or not normalized[2:].isdigit():
            raise ValueError("指数代码格式应为 sh/sz 加 6 位数字")
        market_value = normalized[:2].upper()
        asset = _index_asset(normalized, "", market_value)
        path = benchmark_cli.resolve_benchmark_path("data/live-benchmark.db")
        adapter = TencentIndexAdapter(
            lambda _asset_id, _start, _end: benchmark_cli._tencent_index_fetcher(asset.provider_symbol, _start, _end)
        )
        data_class = "index"
        import_fn = lambda conn, asset_id, records: import_live_daily_incremental(conn, asset_id, "index", records)
    elif asset_type == "fund":
        normalized = code.strip()
        if len(normalized) != 6 or not normalized.isdigit():
            raise ValueError("基金代码应为 6 位数字")
        asset = _fund_asset(normalized, "")
        path = fund_cli.resolve_fund_pilot_path("data/live-fund-pilot.db")
        adapter = LsjzFundAdapter(
            lambda _asset_id, _start, _end: eastmoney_lsjz_fetcher(asset.provider_symbol, _start, _end)
        )
        data_class = "open_fund"
        import_fn = import_live_fund_incremental
    else:
        raise ValueError("仅支持 stock、etf、index 和 fund")

    conn = init_db(path)
    try:
        ensure_asset(conn, asset)
        previous_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(25)
        try:
            try:
                fetched = fetch_with_retry(
                    lambda: adapter.fetch_history(asset.id, start=start, end=end),
                    retries=retries,
                    backoff=backoff,
                )
            except Exception as exc:  # noqa: BLE001
                return {
                    "status": "fetch_failed",
                    "asset_type": asset_type,
                    "asset_id": asset.id,
                    "provider": asset.provider,
                    "error_category": classify_error(exc),
                    "error_type": type(exc).__name__,
                    "error_detail": redact_error_detail(exc),
                    "database_written": False,
                }
        finally:
            socket.setdefaulttimeout(previous_timeout)

        records = fetched.records
        if asset_type == "etf":
            records = [record for record in records if start <= record.trade_date <= end]

        if data_class == "open_fund":
            pre_quality = check_records([], records, {asset.id: "open_fund"})
        else:
            pre_quality = check_records(records, [], {asset.id: data_class})
        if not records:
            return {
                "status": "empty",
                "asset_type": asset_type,
                "asset_id": asset.id,
                "provider": asset.provider,
                "fetched_rows": fetched.fetched_rows,
                "converted_rows": 0,
                "quality_issue_count": 0,
                "database_written": False,
            }

        result = import_fn(conn, asset.id, records)
        return {
            "status": "success",
            "asset_type": asset_type,
            "asset_id": asset.id,
            "provider": asset.provider,
            "fetched_rows": fetched.fetched_rows,
            "converted_rows": len(records),
            "quality_issue_count": pre_quality.issue_count,
            "inserted": result["inserted"],
            "skipped": result["skipped"],
            "conflicts": result["conflicts"],
            "database_written": True,
            "committed": result["committed"],
        }
    finally:
        conn.close()


def ensure_asset(conn, asset: AssetRecord) -> None:
    from backend.app.db import repository

    existing = repository.get_asset(conn, asset.id)
    if existing is None:
        with conn:
            repository.insert_asset(conn, asset)
        return
