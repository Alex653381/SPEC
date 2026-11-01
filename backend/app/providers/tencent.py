"""腾讯通道适配器。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.app.providers.base import MarketDataAdapter, build_daily_record
from backend.app.services.normalization import normalize_daily_bar
from backend.app.services.validation import validate_daily_bar


class TencentIndexAdapter(MarketDataAdapter):
    name = "tencent"
    asset_type = "index"
    supports_date_range = True

    def _map(self, raw: dict[str, Any]) -> dict[str, Any]:
        # 腾讯指数日线的 amount 列实为成交量（手），不是成交额。
        canonical = normalize_daily_bar(raw)
        canonical["volume"] = canonical["turnover"]
        canonical["turnover"] = None
        return canonical

    def _validate(self, canonical):
        return validate_daily_bar(canonical)

    def _build(self, asset_id, canonical, issues, fetched_at: datetime):
        return build_daily_record(
            asset_id, canonical, issues, fetched_at, provider=self.name, adjustment_mode="none"
        )
