"""测试辅助构造器，全部为合成数据，不伪装成真实行情。"""

from __future__ import annotations

from datetime import date, datetime, timezone

from backend.app.schemas.records import (
    AssetRecord,
    DailyBarRecord,
    FundNavRecord,
)


def make_bar(
    asset_id: str = "asset_stock_000001",
    trade_date: date = date(2024, 1, 2),
    open_: float = 10.0,
    high: float = 10.5,
    low: float = 9.8,
    close: float = 10.2,
    volume: float = 1000.0,
    turnover: float | None = 10000.0,
    adjustment_mode: str = "qfq",
    provider: str = "sina",
    quality_status: str = "normal",
) -> DailyBarRecord:
    return DailyBarRecord(
        asset_id=asset_id,
        trade_date=trade_date,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
        turnover=turnover,
        adjustment_mode=adjustment_mode,
        provider=provider,
        fetched_at=datetime(2026, 10, 31, 0, 0, tzinfo=timezone.utc),
        quality_status=quality_status,
    )


def make_nav(
    asset_id: str = "asset_fund_110022",
    nav_date: date = date(2024, 1, 2),
    unit_nav: float = 1.5,
    accumulated_nav: float | None = 1.8,
    provider: str = "eastmoney_fund",
    quality_status: str = "normal",
) -> FundNavRecord:
    return FundNavRecord(
        asset_id=asset_id,
        nav_date=nav_date,
        unit_nav=unit_nav,
        accumulated_nav=accumulated_nav,
        provider=provider,
        fetched_at=datetime(2026, 10, 31, 0, 0, tzinfo=timezone.utc),
        quality_status=quality_status,
    )


def make_asset(
    asset_id: str = "asset_stock_000001",
    asset_type: str = "stock",
    symbol: str = "000001",
) -> AssetRecord:
    return AssetRecord(
        id=asset_id,
        symbol=symbol,
        name="synthetic asset",
        asset_type=asset_type,
        market="SZ" if asset_type == "stock" else "SH",
        provider="synthetic",
        provider_symbol=symbol,
        price_semantics="close" if asset_type != "open_fund" else "unit_nav",
        volume_unit="shares" if asset_type != "open_fund" else None,
        adjustment_mode="qfq" if asset_type == "stock" else None,
    )
