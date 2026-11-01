"""合成数据安全入库管线。"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date

from backend.app.db import repository
from backend.app.quality.checker import check_records
from backend.app.quality.rules import QualityIssue, check_daily_bar, check_fund_nav
from backend.app.schemas.records import DailyBarRecord, FundNavRecord
from backend.app.workers.jobs import TaskExecutionError, TaskResult


@dataclass(frozen=True)
class ImportOutcome:
    input_count: int
    inserted: int
    skipped: int
    conflicts: int
    post_check_issue_count: int
    issues: list[QualityIssue]


def _validate(records, data_class: str) -> list[QualityIssue]:
    if data_class == "daily_bar":
        return [issue for record in records for issue in check_daily_bar(record)]
    return [issue for record in records for issue in check_fund_nav(record)]


def import_batch(
    conn: sqlite3.Connection,
    asset_id: str,
    records,
    data_class: str,
) -> ImportOutcome:
    issues = _validate(records, data_class)
    if issues:
        raise TaskExecutionError(
            "输入数据校验失败",
            error_code="INPUT_VALIDATION_FAILED",
            summary={"data_class": data_class, "input_count": len(records), "issues": [issue.rule_id for issue in issues]},
        )

    existing = _existing_keys(conn, data_class)
    incoming_keys = [_key(record, data_class) for record in records]
    duplicate_input = len(incoming_keys) - len(set(incoming_keys))

    with conn:
        before = conn.total_changes
        if data_class == "daily_bar":
            repository.insert_daily_bars(conn, records)
        else:
            repository.insert_fund_navs(conn, records)
        inserted = conn.total_changes - before

    inserted_keys = set(existing)
    conflicts = 0
    for record in records:
        key = _key(record, data_class)
        if key in existing and existing[key] != _content(record):
            conflicts += 1
        inserted_keys.add(key)

    skipped = len(records) - inserted
    post_issues = _post_check(conn, asset_id, data_class)

    if post_issues:
        raise TaskExecutionError(
            "写入后检查发现问题",
            error_code="POST_CHECK_FAILED",
            summary={
                "data_class": data_class,
                "input_count": len(records),
                "inserted": inserted,
                "skipped": skipped,
                "conflicts": conflicts,
                "post_check_issue_count": len(post_issues),
                "issues": [issue.rule_id for issue in post_issues],
            },
        )

    return ImportOutcome(
        input_count=len(records),
        inserted=inserted,
        skipped=skipped,
        conflicts=conflicts,
        post_check_issue_count=0,
        issues=[],
    )


def _key(record, data_class: str):
    if data_class == "daily_bar":
        return (record.asset_id, record.trade_date.isoformat(), record.adjustment_mode)
    return (record.asset_id, record.nav_date.isoformat())


def _content(record) -> tuple:
    if isinstance(record, DailyBarRecord):
        return (record.open, record.high, record.low, record.close, record.volume, record.turnover)
    return (record.unit_nav, record.accumulated_nav)


def _existing_keys(conn: sqlite3.Connection, data_class: str) -> dict:
    if data_class == "daily_bar":
        return {_key(record, "daily_bar"): _content(record) for record in repository.query_all_daily_bars(conn)}
    return {_key(record, "fund_nav"): _content(record) for record in repository.query_all_fund_navs(conn)}


def _post_check(conn: sqlite3.Connection, asset_id: str, data_class: str) -> list[QualityIssue]:
    if data_class == "daily_bar":
        records = repository.query_daily_bars(conn, asset_id)
        return check_records(records, [], {asset_id: "stock"}).issues
    records = repository.query_fund_navs(conn, asset_id)
    return check_records([], records, {asset_id: "open_fund"}).issues


def synthetic_import_handler(
    conn: sqlite3.Connection,
    job_id: str,
    asset_id: str,
    records,
    data_class: str,
) -> TaskResult:
    del job_id
    outcome = import_batch(conn, asset_id, records, data_class)
    return TaskResult(
        processed_records=outcome.input_count,
        succeeded_records=outcome.inserted,
        summary={
            "data_class": data_class,
            "input_count": outcome.input_count,
            "inserted": outcome.inserted,
            "skipped": outcome.skipped,
            "conflicts": outcome.conflicts,
        },
    )
