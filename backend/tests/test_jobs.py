"""后台任务生命周期测试。"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from backend.app.db import jobs_repository
from backend.app.db.database import init_db
from backend.app.workers.jobs import TaskResult, run_job_once
from backend.app.workers.quality_task import quality_check_handler
from backend.tests import fixtures


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class JobLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.path = os.path.join(self.tmp.name, "jobs.db")
        self.conn = init_db(self.path)
        fixtures.seed_database(self.conn)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_quality_check_job_reaches_success(self):
        record = run_job_once(self.conn, "quality_check-1", quality_check_handler)
        self.assertEqual("success", record.status)
        self.assertIsNotNone(record.started_at)
        self.assertIsNotNone(record.finished_at)
        self.assertEqual(record.processed_records, record.succeeded_records)

    def test_handler_failure_is_recorded(self):
        def failing_handler(conn, job_id):
            raise ValueError("boom")

        record = run_job_once(self.conn, "failing-1", failing_handler)
        self.assertEqual("failed", record.status)
        self.assertEqual("ValueError", record.error_code)
        self.assertIn("boom", record.error_summary)
        self.assertIsNotNone(record.finished_at)

    def test_terminal_job_cannot_run_twice(self):
        run_job_once(self.conn, "quality_check-1", quality_check_handler)
        with self.assertRaises(jobs_repository.JobStateError):
            run_job_once(self.conn, "quality_check-1", quality_check_handler)

    def test_start_job_guards_concurrent_start(self):
        jobs_repository.create_job(self.conn, "quality_check-2", "quality_check")
        with self.conn:
            jobs_repository.start_job(self.conn, "quality_check-2")
        with self.assertRaises(jobs_repository.JobStateError):
            with self.conn:
                jobs_repository.start_job(self.conn, "quality_check-2")

    def test_retry_keeps_original_failure(self):
        def failing_handler(conn, job_id):
            raise RuntimeError("first")

        run_job_once(self.conn, "failing-1", failing_handler)
        run_job_once(self.conn, "quality_check-1", quality_check_handler)
        original = jobs_repository.get_job(self.conn, "failing-1")
        self.assertEqual("failed", original.status)
        self.assertIn("first", original.error_summary)

    def test_quality_issues_do_not_fail_task(self):
        record = run_job_once(self.conn, "quality_check-3", quality_check_handler)
        self.assertEqual("success", record.status)
        self.assertIn("issue_count", record.execution_summary or "")

    def test_finish_write_failure_is_not_fake_success(self):
        with mock.patch(
            "backend.app.workers.jobs.jobs_repository.finish_job",
            side_effect=sqlite3.OperationalError("write failed"),
        ):
            with self.assertRaises(sqlite3.OperationalError):
                run_job_once(self.conn, "quality_check-4", quality_check_handler)


class WorkerCliTest(unittest.TestCase):
    def test_cli_success_exit_zero(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = os.path.join(tmp, "cli.db")
            conn = init_db(path)
            fixtures.seed_database(conn)
            conn.close()
            result = subprocess.run(
                [
                    sys.executable,
                    os.path.join(ROOT, "scripts", "run_worker.py"),
                    "--db",
                    path,
                    "--task",
                    "quality_check",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn('"status": "success"', result.stdout)

    def test_cli_missing_db_exit_two(self):
        result = subprocess.run(
            [sys.executable, os.path.join(ROOT, "scripts", "run_worker.py"), "--db", "missing.db", "--task", "quality_check"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(2, result.returncode)


if __name__ == "__main__":
    unittest.main()
