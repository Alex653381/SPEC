"""统一数据记录结构。股票/指数/ETF 使用日线，场外基金使用净值。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime

from backend.app.core.quality import AssetType, QualityStatus


@dataclass(frozen=True)
class AssetRecord:
    id: str
    symbol: str
    name: str
    asset_type: str
    market: str
    provider: str
    provider_symbol: str
    price_semantics: str
    currency: str = "CNY"
    volume_unit: str | None = None
    adjustment_mode: str | None = None
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class DailyBarRecord:
    asset_id: str
    trade_date: date
    open: float
    high: float
    low: float
    close: float
    volume: float
    adjustment_mode: str
    provider: str
    fetched_at: datetime
    turnover: float | None = None
    validated_at: datetime | None = None
    quality_status: str = QualityStatus.NORMAL


@dataclass(frozen=True)
class FundNavRecord:
    asset_id: str
    nav_date: date
    unit_nav: float
    provider: str
    fetched_at: datetime
    accumulated_nav: float | None = None
    validated_at: datetime | None = None
    quality_status: str = QualityStatus.NORMAL


def with_quality(record, status: str):
    """返回带指定质量状态的副本，不修改原记录。"""
    return replace(record, quality_status=status)


def is_ohlc_asset_type(asset_type: str) -> bool:
    return asset_type in (AssetType.STOCK, AssetType.INDEX, AssetType.ETF)
