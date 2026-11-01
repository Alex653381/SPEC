"""基础数据校验。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Mapping

from backend.app.services.normalization import parse_date


@dataclass(frozen=True)
class ValidationIssue:
    field: str
    code: str
    message: str
    blocking: bool = True


def _finite(value) -> bool:
    return value is not None and math.isfinite(value)


def validate_daily_bar(row: Mapping) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    trade_date = parse_date(row.get("trade_date"))
    if trade_date is None:
        issues.append(ValidationIssue("trade_date", "INVALID_DATE", "交易日期无效或缺失", blocking=True))

    for field in ("open", "high", "low", "close"):
        value = row.get(field)
        if value is None or not _finite(value):
            issues.append(ValidationIssue(field, "MISSING_OR_NON_FINITE", f"{field} 缺失或非有限数值", blocking=True))
        elif value < 0:
            issues.append(ValidationIssue(field, "NEGATIVE_PRICE", f"{field} 为负值", blocking=True))

    volume = row.get("volume")
    if volume is None or not _finite(volume):
        issues.append(ValidationIssue("volume", "MISSING_OR_NON_FINITE", "volume 缺失或非有限数值", blocking=True))
    elif volume < 0:
        issues.append(ValidationIssue("volume", "NEGATIVE_VOLUME", "volume 为负值", blocking=True))

    turnover = row.get("turnover")
    if turnover is not None:
        if not _finite(turnover):
            issues.append(ValidationIssue("turnover", "NON_FINITE_TURNOVER", "turnover 非有限数值", blocking=False))
        elif turnover < 0:
            issues.append(ValidationIssue("turnover", "NEGATIVE_TURNOVER", "turnover 为负值", blocking=True))

    open_, high, low, close = (row.get(f) for f in ("open", "high", "low", "close"))
    if all(_finite(v) for v in (open_, high, low, close)):
        if high < open_:
            issues.append(ValidationIssue("high", "OHLC_RELATION", "high 低于 open", blocking=False))
        if high < close:
            issues.append(ValidationIssue("high", "OHLC_RELATION", "high 低于 close", blocking=False))
        if low > open_:
            issues.append(ValidationIssue("low", "OHLC_RELATION", "low 高于 open", blocking=False))
        if low > close:
            issues.append(ValidationIssue("low", "OHLC_RELATION", "low 高于 close", blocking=False))
        if high < low:
            issues.append(ValidationIssue("high", "OHLC_RELATION", "high 低于 low", blocking=False))

    return issues


def validate_fund_nav(row: Mapping) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    nav_date = parse_date(row.get("nav_date"))
    if nav_date is None:
        issues.append(ValidationIssue("nav_date", "INVALID_DATE", "净值日期无效或缺失", blocking=True))

    unit_nav = row.get("unit_nav")
    if unit_nav is None or not _finite(unit_nav):
        issues.append(ValidationIssue("unit_nav", "MISSING_OR_NON_FINITE", "单位净值缺失或非有限数值", blocking=True))
    elif unit_nav <= 0:
        issues.append(ValidationIssue("unit_nav", "NON_POSITIVE_NAV", "单位净值必须为正数", blocking=True))

    accumulated = row.get("accumulated_nav")
    if accumulated is not None:
        if not _finite(accumulated):
            issues.append(ValidationIssue("accumulated_nav", "NON_FINITE_ACC_NAV", "累计净值非有限数值", blocking=False))
        elif accumulated < 0:
            issues.append(ValidationIssue("accumulated_nav", "NEGATIVE_ACC_NAV", "累计净值为负值", blocking=True))

    return issues


def has_blocking_issue(issues: list[ValidationIssue]) -> bool:
    return any(issue.blocking for issue in issues)
