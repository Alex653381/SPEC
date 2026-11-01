"""任务元数据存储，与行情、净值业务表分离。"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class JobRecord:
    id: str
    job_type: str
    status: str
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    processed_records: int = 0
    succeeded_records: int = 0
    error_code: str | None = None
    error_summary: str | None = None
    execution_summary: str | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_job(conn: sqlite3.Connection, job_id: str, job_type: str) -> JobRecord:
    created_at = _now_iso()
    conn.execute(
        """
        INSERT INTO jobs (id, job_type, status, created_at)
        VALUES (?, ?, 'pending', ?)
        """,
        (job_id, job_type, created_at),
    )
    return get_job(conn, job_id)


def get_job(conn: sqlite3.Connection, job_id: str) -> JobRecord | None:
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _job_from_row(row) if row else None


def start_job(conn: sqlite3.Connection, job_id: str) -> JobRecord:
    """pending -> running，使用条件更新保证并发与终态保护。"""
    started_at = _now_iso()
    cursor = conn.execute(
        "UPDATE jobs SET status = 'running', started_at = ? WHERE id = ? AND status = 'pending'",
        (started_at, job_id),
    )
    if cursor.rowcount != 1:
        raise JobStateError(f"任务 {job_id} 不能从当前状态启动")
    return get_job(conn, job_id)


def finish_job(
    conn: sqlite3.Connection,
    job_id: str,
    status: str,
    processed_records: int = 0,
    succeeded_records: int = 0,
    error_code: str | None = None,
    error_summary: str | None = None,
    execution_summary: str | None = None,
) -> JobRecord:
    if status not in ("success", "failed"):
        raise ValueError("终态只能是 success 或 failed")
    finished_at = _now_iso()
    cursor = conn.execute(
        """
        UPDATE jobs
        SET status = ?, finished_at = ?, processed_records = ?, succeeded_records = ?,
            error_code = ?, error_summary = ?, execution_summary = ?
        WHERE id = ? AND status = 'running'
        """,
        (status, finished_at, processed_records, succeeded_records, error_code, error_summary, execution_summary, job_id),
    )
    if cursor.rowcount != 1:
        raise JobStateError(f"任务 {job_id} 不能完成，当前不是 running")
    return get_job(conn, job_id)


def _job_from_row(row) -> JobRecord:
    return JobRecord(
        id=row["id"],
        job_type=row["job_type"],
        status=row["status"],
        created_at=row["created_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        processed_records=row["processed_records"],
        succeeded_records=row["succeeded_records"],
        error_code=row["error_code"],
        error_summary=row["error_summary"],
        execution_summary=row["execution_summary"],
    )


class JobStateError(RuntimeError):
    pass
