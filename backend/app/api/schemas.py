"""API 响应模型。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class AssetOut(BaseModel):
    id: str
    symbol: str
    name: str
    asset_type: str
    market: str
    currency: str
    provider: str
    price_semantics: str
    volume_unit: str | None = None
    adjustment_mode: str | None = None
    is_active: bool


class AssetListOut(BaseModel):
    items: list[AssetOut]
    total: int
    limit: int
    offset: int


class HistoryOut(BaseModel):
    asset_id: str
    asset_type: str
    data_class: str
    start_date: str | None = None
    end_date: str | None = None
    latest_business_date: str | None = None
    count: int
    records: list[dict[str, Any]]


class DashboardOut(BaseModel):
    configured: bool
    assets: list[dict[str, Any]] = []
