"""真实接口小规模验证的纯函数逻辑，可离线测试。"""

from __future__ import annotations

import math
import re
import time
from datetime import date, timedelta
from typing import Iterable

from backend.app.services.normalization import parse_date


def recent_window(days: int = 20, today: date | None = None) -> tuple[date, date]:
    end = today or date.today()
    return end - timedelta(days=days), end


def _null_ratio(values: Iterable) -> float:
    items = list(values)
    if not items:
        return 0.0
    nulls = sum(1 for v in items if v is None)
    return round(nulls / len(items), 4)


def _non_finite_count(values: Iterable) -> int:
    count = 0
    for value in values:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(numeric):
            count += 1
    return count


def summarize_daily_rows(rows: list[dict]) -> dict:
    dates = [parse_date(row.get("date")) for row in rows]
    valid_dates = [d for d in dates if d is not None]
    open_ = [row.get("open") for row in rows]
    high = [row.get("high") for row in rows]
    low = [row.get("low") for row in rows]
    close = [row.get("close") for row in rows]
    volume = [row.get("volume") for row in rows]

    ohlc_violations = 0
    for o, h, l, c in zip(open_, high, low, close):
        try:
            o, h, l, c = float(o), float(h), float(l), float(c)
        except (TypeError, ValueError):
            continue
        if not all(math.isfinite(x) for x in (o, h, l, c)):
            continue
        if h < l or h < o or h < c or l > o or l > c:
            ohlc_violations += 1

    return {
        "rows": len(rows),
        "date_min": min(valid_dates).isoformat() if valid_dates else None,
        "date_max": max(valid_dates).isoformat() if valid_dates else None,
        "invalid_dates": len(dates) - len(valid_dates),
        "duplicate_dates": len(valid_dates) - len(set(valid_dates)),
        "null_ratio": {
            "open": _null_ratio(open_),
            "high": _null_ratio(high),
            "low": _null_ratio(low),
            "close": _null_ratio(close),
            "volume": _null_ratio(volume),
        },
        "non_finite_values": _non_finite_count(open_ + high + low + close + volume),
        "ohlc_violations": ohlc_violations,
    }


def summarize_fund_rows(rows: list[dict], calendar: set[date] | None = None) -> dict:
    dates = [parse_date(row.get("净值日期")) for row in rows]
    valid_dates = [d for d in dates if d is not None]
    weekend_dates = [d for d in valid_dates if d.weekday() >= 5]
    unit_nav = [row.get("单位净值") for row in rows]
    accumulated = [row.get("累计净值") for row in rows]
    non_positive = sum(
        1 for v in unit_nav if v is not None and isinstance(v, (int, float)) and v <= 0
    )

    report = {
        "rows": len(rows),
        "date_min": min(valid_dates).isoformat() if valid_dates else None,
        "date_max": max(valid_dates).isoformat() if valid_dates else None,
        "invalid_dates": len(dates) - len(valid_dates),
        "duplicate_dates": len(valid_dates) - len(set(valid_dates)),
        "weekend_dates_reported": [d.isoformat() for d in weekend_dates],
        "null_ratio": {"unit_nav": _null_ratio(unit_nav), "accumulated_nav": _null_ratio(accumulated)},
        "non_finite_values": _non_finite_count(unit_nav + accumulated),
        "non_positive_unit_nav": non_positive,
    }
    if calendar is not None:
        report["calendar_mismatches_reported"] = [
            d.isoformat() for d in valid_dates if d not in calendar
        ]
    return report


_SECRET_PATTERN = re.compile(
    r"(?i)\b(cookie|set-cookie|authorization|token|password|secret)\b\s*[=:]\s*\S+"
)


def classify_error(exc: BaseException) -> str:
    """把验证过程中的异常归入稳定类别，便于离线测试和摘要输出。"""
    name = type(exc).__name__.lower()
    lowered = str(exc).lower()
    if isinstance(exc, TimeoutError) or "timeout" in lowered or "timed out" in lowered:
        return "timeout"
    if isinstance(exc, ConnectionError) or name == "connectionerror" or "connection" in lowered:
        return "network"
    if any(token in lowered for token in ("429", "rate limit", "限流", "too many requests")):
        return "rate_limit"
    if any(token in lowered for token in ("http", "404", "500", "502", "503")):
        return "http_error"
    return "unknown"


def is_retryable_error(category: str) -> bool:
    return category in {"timeout", "network"}


def redact_error_detail(exc: BaseException) -> str:
    """去掉常见凭据字段并截断，避免把敏感信息写入摘要。"""
    text = _SECRET_PATTERN.sub(r"\1=[redacted]", str(exc))
    if len(text) > 500:
        text = text[:500] + "..."
    return text


def fetch_with_retry(fn, retries: int = 2, backoff: float = 1.0):
    """对可重试的网络/超时错误做有限次数指数退避，不重试限流等永久错误。"""
    retries = max(0, retries)
    last_error = None
    for attempt in range(retries + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - 统一分类后决定是否重试
            last_error = exc
            if not is_retryable_error(classify_error(exc)) or attempt >= retries:
                raise
            time.sleep(backoff * (2**attempt))
    raise last_error
