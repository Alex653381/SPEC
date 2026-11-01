"""天天基金通道适配器。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.app.providers.base import MarketDataAdapter, build_daily_record
from backend.app.schemas.records import FundNavRecord
from backend.app.services.normalization import normalize_daily_bar, normalize_fund_nav, parse_date
from backend.app.services.quality import quality_from_issues
from backend.app.services.validation import validate_daily_bar, validate_fund_nav


class EastmoneyETFAdapter(MarketDataAdapter):
    name = "eastmoney_push2his"
    asset_type = "etf"
    supports_date_range = True

    def _map(self, raw: dict[str, Any]) -> dict[str, Any]:
        # fund_etf_hist_em 的精确字段与单位待真实响应确认。
        return normalize_daily_bar(raw)

    def _validate(self, canonical):
        return validate_daily_bar(canonical)

    def _build(self, asset_id, canonical, issues, fetched_at: datetime):
        return build_daily_record(
            asset_id, canonical, issues, fetched_at, provider=self.name, adjustment_mode="none"
        )


class EastmoneyFundAdapter(MarketDataAdapter):
    name = "eastmoney_fund"
    asset_type = "open_fund"
    supports_date_range = False

    def _map(self, raw: dict[str, Any]) -> dict[str, Any]:
        return normalize_fund_nav(raw)

    def _validate(self, canonical):
        return validate_fund_nav(canonical)

    def _build(self, asset_id, canonical, issues, fetched_at: datetime):
        return FundNavRecord(
            asset_id=asset_id,
            nav_date=parse_date(canonical["nav_date"]),
            unit_nav=float(canonical["unit_nav"]),
            accumulated_nav=(
                float(canonical["accumulated_nav"])
                if canonical.get("accumulated_nav") is not None
                else None
            ),
            provider=self.name,
            fetched_at=fetched_at,
            quality_status=quality_from_issues(issues),
        )
