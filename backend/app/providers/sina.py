"""新浪通道适配器。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.app.providers.base import MarketDataAdapter, build_daily_record
from backend.app.services.normalization import normalize_daily_bar, parse_date
from backend.app.services.validation import validate_daily_bar


class SinaStockAdapter(MarketDataAdapter):
    name = "sina"
    asset_type = "stock"
    supports_date_range = True
    adjustment_mode = "qfq"

    def _map(self, raw: dict[str, Any]) -> dict[str, Any]:
        return normalize_daily_bar(raw)

    def _validate(self, canonical):
        return validate_daily_bar(canonical)

    def _build(self, asset_id, canonical, issues, fetched_at: datetime):
        return build_daily_record(
            asset_id, canonical, issues, fetched_at, provider=self.name, adjustment_mode=self.adjustment_mode
        )


class SinaIndexAdapter(MarketDataAdapter):
    name = "sina"
    asset_type = "index"
    supports_date_range = False

    def _map(self, raw: dict[str, Any]) -> dict[str, Any]:
        canonical = normalize_daily_bar(raw)
        canonical["turnover"] = None  # 新浪指数日线没有成交额
        return canonical

    def _validate(self, canonical):
        return validate_daily_bar(canonical)

    def _build(self, asset_id, canonical, issues, fetched_at: datetime):
        return build_daily_record(
            asset_id, canonical, issues, fetched_at, provider=self.name, adjustment_mode="none"
        )


class SinaETFAdapter(MarketDataAdapter):
    name = "sina"
    asset_type = "etf"
    supports_date_range = False

    def _map(self, raw: dict[str, Any]) -> dict[str, Any]:
        return normalize_daily_bar(raw)

    def _validate(self, canonical):
        return validate_daily_bar(canonical)

    def _build(self, asset_id, canonical, issues, fetched_at: datetime):
        return build_daily_record(
            asset_id, canonical, issues, fetched_at, provider=self.name, adjustment_mode="none"
        )
