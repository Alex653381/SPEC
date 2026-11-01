"""组合各规则，生成质量报告。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from backend.app.quality.rules import (
    SEVERITY_ERROR,
    SEVERITY_INFO,
    SEVERITY_ORDER,
    SEVERITY_WARNING,
    QualityIssue,
    check_daily_bar,
    check_duplicate_dates,
    check_fund_nav,
    check_large_daily_moves,
    check_large_nav_moves,
)
from backend.app.schemas.records import DailyBarRecord, FundNavRecord


@dataclass
class QualityReport:
    completed: bool
    total_records: int
    passed_records: int
    issue_count: int
    by_severity: dict = field(default_factory=dict)
    issues: list[QualityIssue] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "completed": self.completed,
            "total_records": self.total_records,
            "passed_records": self.passed_records,
            "issue_count": self.issue_count,
            "by_severity": self.by_severity,
            "issues": [
                {
                    "rule_id": issue.rule_id,
                    "severity": issue.severity,
                    "asset_id": issue.asset_id,
                    "data_class": issue.data_class,
                    "business_date": issue.business_date,
                    "field": issue.field,
                    "message": issue.message,
                }
                for issue in self.issues
            ],
        }


def check_records(
    daily_bars: list[DailyBarRecord],
    fund_navs: list[FundNavRecord],
    asset_types: dict[str, str] | None = None,
) -> QualityReport:
    asset_types = asset_types or {}
    issues: list[QualityIssue] = []

    for record in daily_bars:
        issues.extend(check_daily_bar(record))
        if asset_types.get(record.asset_id) == "open_fund":
            issues.append(
                QualityIssue("DQ_TYPE_001", SEVERITY_ERROR, record.asset_id, "daily_bar",
                             record.trade_date.isoformat(), None, "开放式基金不应有日线记录")
            )
    for record in fund_navs:
        issues.extend(check_fund_nav(record))
        if record.asset_id in asset_types and asset_types[record.asset_id] != "open_fund":
            issues.append(
                QualityIssue("DQ_TYPE_002", SEVERITY_ERROR, record.asset_id, "fund_nav",
                             record.nav_date.isoformat(), None, "非开放式基金不应有净值记录")
            )

    issues.extend(
        check_duplicate_dates(
            daily_bars,
            lambda record: (
                record.asset_id,
                record.trade_date.isoformat() if isinstance(record.trade_date, date) else None,
                record.adjustment_mode,
            ),
            "DQ_DAILY_008",
            SEVERITY_ERROR,
            "daily_bar",
        )
    )
    issues.extend(
        check_duplicate_dates(
            fund_navs,
            lambda record: (
                record.asset_id,
                record.nav_date.isoformat() if isinstance(record.nav_date, date) else None,
            ),
            "DQ_NAV_005",
            SEVERITY_ERROR,
            "fund_nav",
        )
    )
    issues.extend(check_large_daily_moves(daily_bars))
    issues.extend(check_large_nav_moves(fund_navs))

    issues.sort(
        key=lambda issue: (
            SEVERITY_ORDER.get(issue.severity, 3),
            issue.asset_id,
            issue.data_class,
            issue.business_date or "",
            issue.rule_id,
        )
    )

    total_records = len(daily_bars) + len(fund_navs)
    affected = {
        (issue.asset_id, issue.data_class, issue.business_date)
        for issue in issues
    }
    by_severity = {
        SEVERITY_ERROR: sum(1 for issue in issues if issue.severity == SEVERITY_ERROR),
        SEVERITY_WARNING: sum(1 for issue in issues if issue.severity == SEVERITY_WARNING),
        SEVERITY_INFO: sum(1 for issue in issues if issue.severity == SEVERITY_INFO),
    }

    return QualityReport(
        completed=True,
        total_records=total_records,
        passed_records=max(0, total_records - len(affected)),
        issue_count=len(issues),
        by_severity=by_severity,
        issues=issues,
    )
