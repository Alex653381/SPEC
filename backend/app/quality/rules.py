"""质量规则与问题结构。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

from backend.app.schemas.records import DailyBarRecord, FundNavRecord


SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"

SEVERITY_ORDER = {SEVERITY_ERROR: 0, SEVERITY_WARNING: 1, SEVERITY_INFO: 2}


@dataclass(frozen=True)
class QualityIssue:
    rule_id: str
    severity: str
    asset_id: str
    data_class: str
    business_date: str | None
    field: str | None
    message: str


def _finite(value) -> bool:
    return value is not None and math.isfinite(value)


def _issue(
    rule_id: str,
    severity: str,
    asset_id: str,
    data_class: str,
    business_date: str | None,
    field: str | None,
    message: str,
) -> QualityIssue:
    return QualityIssue(rule_id, severity, asset_id, data_class, business_date, field, message)


def check_daily_bar(record: DailyBarRecord) -> list[QualityIssue]:
    issues: list[QualityIssue] = []
    business_date = record.trade_date.isoformat() if isinstance(record.trade_date, date) else None

    if not record.asset_id:
        issues.append(_issue("DQ_DAILY_001", SEVERITY_ERROR, record.asset_id, "daily_bar", business_date, "asset_id", "资产标识为空"))
    if not isinstance(record.trade_date, date):
        issues.append(_issue("DQ_DAILY_002", SEVERITY_ERROR, record.asset_id, "daily_bar", business_date, "trade_date", "交易日期无效"))

    for field in ("open", "high", "low", "close"):
        value = getattr(record, field)
        if not _finite(value):
            issues.append(_issue("DQ_DAILY_003", SEVERITY_ERROR, record.asset_id, "daily_bar", business_date, field, f"{field} 不是有限数值"))
        elif value <= 0:
            issues.append(_issue("DQ_DAILY_007", SEVERITY_ERROR, record.asset_id, "daily_bar", business_date, field, f"{field} 必须大于 0"))

    if not _finite(record.volume):
        issues.append(_issue("DQ_DAILY_003", SEVERITY_ERROR, record.asset_id, "daily_bar", business_date, "volume", "volume 不是有限数值"))
    elif record.volume < 0:
        issues.append(_issue("DQ_DAILY_004", SEVERITY_ERROR, record.asset_id, "daily_bar", business_date, "volume", "volume 为负值"))

    if record.turnover is not None and not _finite(record.turnover):
        issues.append(_issue("DQ_DAILY_003", SEVERITY_WARNING, record.asset_id, "daily_bar", business_date, "turnover", "turnover 不是有限数值"))

    if all(_finite(getattr(record, field)) for field in ("open", "high", "low", "close")):
        if record.high < record.low:
            issues.append(_issue("DQ_DAILY_005", SEVERITY_ERROR, record.asset_id, "daily_bar", business_date, "high/low", "high 低于 low"))
        if record.high < record.open or record.high < record.close:
            issues.append(_issue("DQ_DAILY_005", SEVERITY_ERROR, record.asset_id, "daily_bar", business_date, "high", "high 低于 open 或 close"))
        if record.low > record.open or record.low > record.close:
            issues.append(_issue("DQ_DAILY_005", SEVERITY_ERROR, record.asset_id, "daily_bar", business_date, "low", "low 高于 open 或 close"))

    return issues


def check_fund_nav(record: FundNavRecord) -> list[QualityIssue]:
    issues: list[QualityIssue] = []
    business_date = record.nav_date.isoformat() if isinstance(record.nav_date, date) else None

    if not record.asset_id:
        issues.append(_issue("DQ_NAV_001", SEVERITY_ERROR, record.asset_id, "fund_nav", business_date, "asset_id", "资产标识为空"))
    if not isinstance(record.nav_date, date):
        issues.append(_issue("DQ_NAV_002", SEVERITY_ERROR, record.asset_id, "fund_nav", business_date, "nav_date", "净值日期无效"))
    if not _finite(record.unit_nav):
        issues.append(_issue("DQ_NAV_003", SEVERITY_ERROR, record.asset_id, "fund_nav", business_date, "unit_nav", "单位净值不是有限数值"))
    elif record.unit_nav <= 0:
        issues.append(_issue("DQ_NAV_004", SEVERITY_ERROR, record.asset_id, "fund_nav", business_date, "unit_nav", "单位净值必须大于 0"))
    if record.accumulated_nav is not None and not _finite(record.accumulated_nav):
        issues.append(_issue("DQ_NAV_003", SEVERITY_WARNING, record.asset_id, "fund_nav", business_date, "accumulated_nav", "累计净值不是有限数值"))

    return issues


def check_duplicate_dates(
    records,
    key_fn,
    rule_id: str,
    severity: str,
    data_class: str,
) -> list[QualityIssue]:
    seen: dict = {}
    issues: list[QualityIssue] = []
    for record in records:
        key = key_fn(record)
        if key in seen:
            business_date = key[1] if isinstance(key, tuple) and len(key) > 1 else None
            issues.append(
                _issue(rule_id, severity, key[0], data_class, business_date, None, "同一资产同一业务日期存在重复记录")
            )
        else:
            seen[key] = record
    return issues


def check_large_daily_moves(records: list[DailyBarRecord], threshold: float = 0.20) -> list[QualityIssue]:
    """相邻交易日收盘价变化超过阈值时给出警告，不判错。"""
    issues: list[QualityIssue] = []
    ordered = sorted(
        (record for record in records if isinstance(record.trade_date, date) and _finite(record.close)),
        key=lambda record: (record.asset_id, record.adjustment_mode, record.trade_date),
    )
    for previous, current in zip(ordered, ordered[1:]):
        if previous.asset_id != current.asset_id or previous.adjustment_mode != current.adjustment_mode:
            continue
        if previous.close <= 0:
            continue
        move = abs(current.close / previous.close - 1.0)
        if move > threshold:
            issues.append(
                _issue(
                    "DQ_DAILY_009",
                    SEVERITY_WARNING,
                    current.asset_id,
                    "daily_bar",
                    current.trade_date.isoformat(),
                    "close",
                    f"收盘价相对上一交易日变动 {move:.2%}，超过 {threshold:.0%} 阈值",
                )
            )
    return issues


def check_large_nav_moves(records: list[FundNavRecord], threshold: float = 0.10) -> list[QualityIssue]:
    """相邻净值披露日单位净值变化超过阈值时给出警告，不判错。"""
    issues: list[QualityIssue] = []
    ordered = sorted(
        (record for record in records if isinstance(record.nav_date, date) and _finite(record.unit_nav)),
        key=lambda record: (record.asset_id, record.nav_date),
    )
    for previous, current in zip(ordered, ordered[1:]):
        if previous.asset_id != current.asset_id:
            continue
        if previous.unit_nav <= 0:
            continue
        move = abs(current.unit_nav / previous.unit_nav - 1.0)
        if move > threshold:
            issues.append(
                _issue(
                    "DQ_NAV_006",
                    SEVERITY_WARNING,
                    current.asset_id,
                    "fund_nav",
                    current.nav_date.isoformat(),
                    "unit_nav",
                    f"单位净值相对上一披露日变动 {move:.2%}，超过 {threshold:.0%} 阈值",
                )
            )
    return issues
