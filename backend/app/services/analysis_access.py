"""只读分析数据访问层：按资产类型从正确来源读取，不写任何数据库。"""

from __future__ import annotations

import math
import os
import sqlite3
from dataclasses import dataclass
from datetime import date

from backend.app.db import repository
from backend.app.schemas.records import AssetRecord, is_ohlc_asset_type
from backend.app.services.analysis import AnalysisPoint


MAX_HISTORY_LIMIT = 2000


@dataclass(frozen=True)
class SourceDb:
    path: str
    label: str


@dataclass(frozen=True)
class AnalysisSeries:
    asset_id: str
    asset_type: str
    metric: str
    provider: str
    price_semantics: str
    adjustment_mode: str | None
    source_label: str
    points: list[AnalysisPoint]


class AnalysisAccess:
    def __init__(self, sources: dict[str, list[SourceDb]]):
        self.sources = sources

    def find_asset(self, asset_id: str) -> tuple[AssetRecord, str] | None:
        for asset_type in self.sources:
            for source in self.sources[asset_type]:
                if not os.path.exists(source.path):
                    continue
                conn = sqlite3.connect(f"file:{source.path}?mode=ro", uri=True)
                conn.row_factory = sqlite3.Row
                try:
                    asset = repository.get_asset(conn, asset_id)
                    if asset is not None and asset.asset_type == asset_type:
                        return asset, source.path
                finally:
                    conn.close()
        return None

    def all_assets(self) -> list[AssetRecord]:
        seen: dict[str, AssetRecord] = {}
        for asset_type in self.sources:
            for source in self.sources[asset_type]:
                if not os.path.exists(source.path):
                    continue
                conn = sqlite3.connect(f"file:{source.path}?mode=ro", uri=True)
                conn.row_factory = sqlite3.Row
                try:
                    for asset in repository.query_all_assets(conn):
                        if asset.asset_type == asset_type and asset.id not in seen:
                            seen[asset.id] = asset
                finally:
                    conn.close()
        return list(seen.values())

    def load_series(
        self,
        asset_type: str,
        asset_id: str,
        start: date | None,
        end: date | None,
    ) -> AnalysisSeries | None:
        for source in self.sources.get(asset_type, []):
            if not os.path.exists(source.path):
                continue
            conn = sqlite3.connect(f"file:{source.path}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            try:
                asset = repository.get_asset(conn, asset_id)
                if asset is None or asset.asset_type != asset_type:
                    continue
                if is_ohlc_asset_type(asset_type):
                    records = repository.query_daily_bars(conn, asset_id, start, end, MAX_HISTORY_LIMIT)
                    points = [
                        AnalysisPoint(record.trade_date, record.close)
                        for record in records
                        if math.isfinite(record.close) and record.close > 0
                    ]
                    metric = "close"
                else:
                    records = repository.query_fund_navs(conn, asset_id, start, end, MAX_HISTORY_LIMIT)
                    points = [
                        AnalysisPoint(record.nav_date, record.unit_nav)
                        for record in records
                        if math.isfinite(record.unit_nav) and record.unit_nav > 0
                    ]
                    metric = "unit_nav"
                return AnalysisSeries(
                    asset_id=asset_id,
                    asset_type=asset_type,
                    metric=metric,
                    provider=asset.provider,
                    price_semantics=asset.price_semantics,
                    adjustment_mode=asset.adjustment_mode,
                    source_label=source.label,
                    points=points,
                )
            finally:
                conn.close()
        return None
