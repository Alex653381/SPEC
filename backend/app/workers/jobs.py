"""任务生命周期服务。"""

from __future__ import annotations

import json
import sqlite3
import traceback
from dataclasses import dataclass
from typing import Callable

from backend.app.db import jobs_repository


@dataclass(frozen=True)
class TaskResult:
    processed_records: int
    succeeded_records: int
    summary: dict


TaskHandler = Callable[[sqlite3.Connection, str], TaskResult]


class TaskExecutionError(Exception):
    """任务执行失败，可携带结构化摘要。"""

    def __init__(self, message: str, error_code: str | None = None, summary: dict | None = None):
        super().__init__(message)
        self.error_code = error_code
        self.summary = summary or {}


def run_job_once(
    conn: sqlite3.Connection,
    job_id: str,
    handler: TaskHandler,
) -> jobs_repository.JobRecord:
    """创建并执行一个任务，返回终态记录。调用方负责 job_id 唯一性。"""
    if jobs_repository.get_job(conn, job_id) is not None:
        raise jobs_repository.JobStateError(f"任务 {job_id} 已存在，不允许重复执行")
    jobs_repository.create_job(conn, job_id, job_id.split("-", 1)[0])
    with conn:
        jobs_repository.start_job(conn, job_id)
    try:
        result = handler(conn, job_id)
        with conn:
            return jobs_repository.finish_job(
                conn,
                job_id,
                "success",
                processed_records=result.processed_records,
                succeeded_records=result.succeeded_records,
                execution_summary=json.dumps(result.summary, ensure_ascii=False),
            )
    except TaskExecutionError as exc:
        with conn:
            return jobs_repository.finish_job(
                conn,
                job_id,
                "failed",
                error_code=exc.error_code or type(exc).__name__,
                error_summary=str(exc)[:500],
                execution_summary=json.dumps(exc.summary, ensure_ascii=False),
            )
    except Exception as exc:  # noqa: BLE001 - 捕获后记录失败，不永久停在 running
        with conn:
            return jobs_repository.finish_job(
                conn,
                job_id,
                "failed",
                error_code=type(exc).__name__,
                error_summary=str(exc)[:500],
                execution_summary=json.dumps({"traceback": traceback.format_exc(limit=1)}, ensure_ascii=False),
            )
