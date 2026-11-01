"""外部数据字段标准化为统一键名。"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Mapping


DAILY_BAR_FIELDS = ("trade_date", "open", "high", "low", "close", "volume", "turnover")
FUND_NAV_FIELDS = ("nav_date", "unit_nav", "accumulated_nav")

_ALIASES = {
    "trade_date": ("trade_date", "日期", "date", "交易日期", "时间"),
    "nav_date": ("nav_date", "净值日期", "date"),
    "open": ("open", "开盘"),
    "high": ("high", "最高"),
    "low": ("low", "最低"),
    "close": ("close", "收盘"),
    "volume": ("volume", "成交量"),
    "turnover": ("amount", "成交额", "turnover"),
    "unit_nav": ("unit_nav", "单位净值"),
    "accumulated_nav": ("accumulated_nav", "累计净值"),
}


def _pick(raw: Mapping[str, Any], field: str) -> Any:
    for alias in _ALIASES.get(field, (field,)):
        if alias in raw:
            return raw[alias]
    return None


def normalize_daily_bar(raw: Mapping[str, Any]) -> dict[str, Any]:
    """把日线原始行标准化为统一键名，数值先做宽松转换。"""
    return {
        "trade_date": _pick(raw, "trade_date"),
        "open": _as_float(_pick(raw, "open")),
        "high": _as_float(_pick(raw, "high")),
        "low": _as_float(_pick(raw, "low")),
        "close": _as_float(_pick(raw, "close")),
        "volume": _as_float(_pick(raw, "volume")),
        "turnover": _as_float(_pick(raw, "turnover")),
    }


def normalize_fund_nav(raw: Mapping[str, Any]) -> dict[str, Any]:
    """把基金净值原始行标准化为统一键名。"""
    return {
        "nav_date": _pick(raw, "nav_date"),
        "unit_nav": _as_float(_pick(raw, "unit_nav")),
        "accumulated_nav": _as_float(_pick(raw, "accumulated_nav")),
    }


def parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if text in ("", "-", "--", "None", "nan"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
