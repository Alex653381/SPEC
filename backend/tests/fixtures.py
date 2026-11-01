"""合成数据测试夹具。所有记录都是测试样本，不伪装成真实行情。"""

from __future__ import annotations

from datetime import date, timedelta

from backend.app.db import repository
from backend.app.schemas.records import AssetRecord
from backend.tests.support import make_asset, make_bar, make_nav


ASSETS = (
    make_asset("stock-000001", "stock", "000001"),
    make_asset("index-000001", "index", "000001"),
    make_asset("etf-510300", "etf", "510300"),
    make_asset("fund-110022", "open_fund", "110022"),
)


def trading_days(start: date = date(2024, 1, 2), end: date = date(2024, 1, 31)) -> list[date]:
    days = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def build_stock_bars(asset_id: str = "stock-000001") -> list:
    days = trading_days()
    missing = {days[6], days[7]}
    rows = []
    for i, day in enumerate(days):
        if day in missing:
            continue
        open_ = 10 + i * 0.04
        body = 0.06 + (i % 4) * 0.05
        close = open_ + body * (1 if i % 2 == 0 else -1)
        high = max(open_, close) + 0.03 + (i % 3) * 0.02
        low = min(open_, close) - 0.03 - (i % 4) * 0.02
        rows.append(
            make_bar(
                asset_id=asset_id,
                trade_date=day,
                open_=open_,
                close=close,
                high=high,
                low=low,
                volume=1000 + i,
                turnover=(1000 + i) * close,
                adjustment_mode="qfq",
                provider="synthetic",
            )
        )
    return rows


def build_index_bars(asset_id: str = "index-000001") -> list:
    days = trading_days()
    rows = []
    for i, day in enumerate(days):
        open_ = 3000 + i * 0.8
        body = 2 + (i % 4) * 3
        close = open_ + body * (1 if i % 3 == 0 else -1)
        high = max(open_, close) + 4 + (i % 3) * 2
        low = min(open_, close) - 4 - (i % 4) * 2
        rows.append(
            make_bar(
                asset_id=asset_id,
                trade_date=day,
                open_=open_,
                close=close,
                high=high,
                low=low,
                volume=1_000_000 + i * 1000,
                turnover=None,
                adjustment_mode="none",
                provider="synthetic",
            )
        )
    return rows


def build_etf_bars(asset_id: str = "etf-510300") -> list:
    days = trading_days()
    rows = []
    for i, day in enumerate(days):
        open_ = 4.0 + i * 0.008
        body = 0.02 + (i % 4) * 0.015
        close = open_ + body * (1 if i % 2 == 0 else -1)
        high = max(open_, close) + 0.02 + (i % 3) * 0.01
        low = min(open_, close) - 0.02 - (i % 4) * 0.01
        rows.append(
            make_bar(
                asset_id=asset_id,
                trade_date=day,
                open_=open_,
                close=close,
                high=high,
                low=low,
                volume=2_000_000 + i * 1000,
                turnover=(2_000_000 + i * 1000) * close,
                adjustment_mode="none",
                provider="synthetic",
            )
        )
    return rows


def build_fund_navs(asset_id: str = "fund-110022") -> list:
    days = trading_days()
    missing = {days[9]}
    return [
        make_nav(
            asset_id=asset_id,
            nav_date=day,
            unit_nav=round(1.0 + i * 0.01 + (0.005 * (i % 3)) * (1 if i % 2 == 0 else -1), 4),
            accumulated_nav=round(1.2 + i * 0.01 + (0.005 * (i % 3)) * (1 if i % 2 == 0 else -1), 4),
            provider="synthetic",
        )
        for i, day in enumerate(days)
        if day not in missing
    ]


def seed_database(conn) -> None:
    with conn:
        for asset in ASSETS:
            repository.insert_asset(conn, asset)
        repository.insert_daily_bars(conn, build_stock_bars())
        repository.insert_daily_bars(conn, build_index_bars())
        repository.insert_daily_bars(conn, build_etf_bars())
        repository.insert_fund_navs(conn, build_fund_navs())
