"""受控真实基金净值增量导入，复用现有质量检查与事务导入逻辑。"""

from __future__ import annotations

import sqlite3
from datetime import date

from backend.app.db import repository
from backend.app.quality.checker import check_records
from backend.app.workers.jobs import TaskExecutionError, TaskResult
from backend.app.workers.synthetic_import import import_batch


NAV_CONTENT_FIELDS = ("unit_nav", "accumulated_nav")


def validate_live_fund_records(records, asset_id: str) -> None:
    quality = check_records([], records, {asset_id: "open_fund"})
    errors = quality.by_severity.get("error", 0)
    if errors:
        raise TaskExecutionError(
            "输入质量检查失败，整批拒绝写入",
            error_code="INPUT_QUALITY_FAILED",
            summary={
                "input_count": len(records),
                "issue_count": quality.issue_count,
                "by_severity": quality.by_severity,
                "issues": [issue.rule_id for issue in quality.issues],
                "committed": False,
            },
        )


def _nav_key(record) -> tuple:
    nav_date = record.nav_date
    if isinstance(nav_date, date):
        nav_date = nav_date.isoformat()
    return (record.asset_id, nav_date)


def classify_live_fund_changes(conn: sqlite3.Connection, asset_id: str, records) -> dict:
    existing = {_nav_key(record): record for record in repository.query_fund_navs(conn, asset_id)}
    new = []
    unchanged = []
    changed = []

    for record in records:
        key = _nav_key(record)
        old = existing.get(key)
        if old is None:
            new.append(record)
            continue
        diffs = [
            field
            for field in NAV_CONTENT_FIELDS
            if getattr(old, field) != getattr(record, field)
        ]
        if not diffs:
            unchanged.append(record)
            continue
        changed.append(
            {
                "nav_date": key[1],
                "fields": diffs,
                "old": {field: getattr(old, field) for field in diffs},
                "new": {field: getattr(record, field) for field in diffs},
            }
        )

    return {"new": new, "unchanged": unchanged, "changed": changed}


def import_live_fund_incremental(conn: sqlite3.Connection, asset_id: str, records) -> dict:
    validate_live_fund_records(records, asset_id)
    diff = classify_live_fund_changes(conn, asset_id, records)

    outcome = None
    if diff["new"]:
        try:
            outcome = import_batch(conn, asset_id, diff["new"], "fund_nav")
        except TaskExecutionError as exc:
            committed = exc.error_code == "POST_CHECK_FAILED"
            raise TaskExecutionError(
                exc.args[0],
                error_code=exc.error_code,
                summary={**exc.summary, "committed": committed},
            ) from exc

    inserted = outcome.inserted if outcome else 0
    post_check_issue_count = outcome.post_check_issue_count if outcome else 0
    return {
        "input_count": len(records),
        "new_count": len(diff["new"]),
        "unchanged_count": len(diff["unchanged"]),
        "changed_count": len(diff["changed"]),
        "changed": diff["changed"],
        "inserted": inserted,
        "skipped": len(diff["unchanged"]) + len(diff["changed"]),
        "conflicts": len(diff["changed"]),
        "failed": 0,
        "post_check_issue_count": post_check_issue_count,
        "committed": True,
    }


def live_fund_import_handler(conn, job_id: str, asset_id: str, records) -> TaskResult:
    del job_id
    result = import_live_fund_incremental(conn, asset_id, records)
    return TaskResult(
        processed_records=result["input_count"],
        succeeded_records=result["inserted"],
        summary=result,
    )
