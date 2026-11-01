"""根据校验结果确定数据质量状态。"""

from __future__ import annotations

from backend.app.core.quality import QualityStatus
from backend.app.services.validation import ValidationIssue, has_blocking_issue


def quality_from_issues(issues: list[ValidationIssue]) -> str:
    if not issues:
        return QualityStatus.NORMAL
    return QualityStatus.SOURCE_ANOMALY


def should_persist(issues: list[ValidationIssue]) -> bool:
    """只有不存在阻断性问题时才允许写入数据表。"""
    return not has_blocking_issue(issues)
