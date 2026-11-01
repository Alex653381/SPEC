"""统一数据源适配器协议与异常。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime
import math
from typing import Any, Callable

from backend.app.core.quality import QualityStatus
from backend.app.schemas.records import DailyBarRecord, FundNavRecord
from backend.app.services.normalization import parse_date, utc_now
from backend.app.services.quality import quality_from_issues, should_persist


class AdapterError(Exception):
    """适配器可识别错误的基类。"""


class NetworkError(AdapterError):
    """网络或接口错误。"""


class InvalidResponseError(AdapterError):
    """数据源响应结构或字段不符合预期。"""


@dataclass(frozen=True)
class AdapterIssue:
    row_index: int
    code: str
    message: str


@dataclass(frozen=True)
class HistoryResult:
    asset_id: str
    adapter: str
    adapter_version: str
    supports_date_range: bool
    fetched_at: datetime
    fetched_rows: int
    records: list[DailyBarRecord | FundNavRecord]
    errors: list[AdapterIssue]
    empty: bool


Fetcher = Callable[[str, date | None, date | None], list[dict[str, Any]]]


class MarketDataAdapter(ABC):
    name: str
    asset_type: str
    version: str = "1.0"
    supports_date_range: bool = False

    def __init__(self, fetcher: Fetcher):
        self._fetcher = fetcher

    @abstractmethod
    def _map(self, raw: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def _validate(self, canonical: dict[str, Any]):
        raise NotImplementedError

    @abstractmethod
    def _build(self, asset_id: str, canonical: dict[str, Any], issues, fetched_at: datetime):
        raise NotImplementedError

    def fetch_history(
        self,
        asset_id: str,
        start: date | None = None,
        end: date | None = None,
    ) -> HistoryResult:
        fetched_at = utc_now()
        request_start = start if self.supports_date_range else None
        request_end = end if self.supports_date_range else None
        try:
            raw_rows = self._fetcher(asset_id, request_start, request_end)
        except AdapterError:
            raise
        except Exception as exc:  # noqa: BLE001 - 统一转成可识别网络异常
            raise NetworkError(f"{self.name} 请求失败: {type(exc).__name__}: {exc}") from exc

        if raw_rows is None:
            raw_rows = []
        if not isinstance(raw_rows, list):
            raise InvalidResponseError(f"{self.name} 响应不是列表")

        records = []
        errors = []
        seen_dates = set()

        for index, raw in enumerate(raw_rows):
            if not isinstance(raw, dict):
                errors.append(AdapterIssue(index, "INVALID_ROW", "数据行不是对象"))
                continue
            try:
                canonical = self._map(raw)
            except Exception as exc:  # noqa: BLE001
                errors.append(AdapterIssue(index, "FIELD_MAPPING", f"{type(exc).__name__}: {exc}"))
                continue

            issues = self._validate(canonical)
            if not should_persist(issues):
                errors.append(
                    AdapterIssue(index, "VALIDATION_BLOCKING", "; ".join(i.message for i in issues if i.blocking))
                )
                continue

            record = self._build(asset_id, canonical, issues, fetched_at)
            business_date = getattr(record, "trade_date", getattr(record, "nav_date", None))

            if self.supports_date_range:
                if start is not None and business_date < start:
                    errors.append(AdapterIssue(index, "OUT_OF_RANGE", f"{business_date} 早于请求范围"))
                    continue
                if end is not None and business_date > end:
                    errors.append(AdapterIssue(index, "OUT_OF_RANGE", f"{business_date} 晚于请求范围"))
                    continue

            if business_date in seen_dates:
                errors.append(AdapterIssue(index, "DUPLICATE_DATE", f"{business_date} 在同批数据中重复"))
                continue
            seen_dates.add(business_date)
            records.append(record)

        return HistoryResult(
            asset_id=asset_id,
            adapter=self.name,
            adapter_version=self.version,
            supports_date_range=self.supports_date_range,
            fetched_at=fetched_at,
            fetched_rows=len(raw_rows),
            records=records,
            errors=errors,
            empty=len(raw_rows) == 0,
        )


def build_daily_record(
    asset_id: str,
    canonical: dict[str, Any],
    issues,
    fetched_at: datetime,
    provider: str,
    adjustment_mode: str,
) -> DailyBarRecord:
    quality = quality_from_issues(issues)
    turnover = canonical.get("turnover")
    turnover_value = None
    if turnover is not None:
        try:
            numeric = float(turnover)
            if math.isfinite(numeric):
                turnover_value = numeric
        except (TypeError, ValueError):
            turnover_value = None
    return DailyBarRecord(
        asset_id=asset_id,
        trade_date=parse_date(canonical["trade_date"]),
        open=float(canonical["open"]),
        high=float(canonical["high"]),
        low=float(canonical["low"]),
        close=float(canonical["close"]),
        volume=float(canonical["volume"]),
        turnover=turnover_value,
        adjustment_mode=adjustment_mode,
        provider=provider,
        fetched_at=fetched_at,
        quality_status=quality,
    )
