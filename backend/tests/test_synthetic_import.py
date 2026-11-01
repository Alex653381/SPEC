"""合成数据安全入库管线测试。"""

from __future__ import annotations

import sqlite3
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from unittest import mock

from backend.app.db import repository
from backend.app.db.database import init_db
from backend.app.workers import synthetic_import
from backend.app.workers.jobs import TaskExecutionError, run_job_once
from backend.tests import fixtures
from backend.tests.support import make_asset, make_bar, make_nav


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class SyntheticImportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.path = f"{self.tmp.name}/import.db"
        self.conn = init_db(self.path)
        for asset in fixtures.ASSETS:
            with self.conn:
                repository.insert_asset(self.conn, asset)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_stock_import_success_and_counts(self):
        bars = fixtures.build_stock_bars()[:5]
        outcome = synthetic_import.import_batch(self.conn, "stock-000001", bars, "daily_bar")
        self.assertEqual(5, outcome.input_count)
        self.assertEqual(5, outcome.inserted)
        self.assertEqual(0, outcome.skipped)
        self.assertEqual(0, outcome.conflicts)
        self.assertEqual(5, len(repository.query_daily_bars(self.conn, "stock-000001")))

    def test_fund_import_success(self):
        navs = fixtures.build_fund_navs()[:5]
        outcome = synthetic_import.import_batch(self.conn, "fund-110022", navs, "fund_nav")
        self.assertEqual(5, outcome.inserted)
        self.assertEqual(5, len(repository.query_fund_navs(self.conn, "fund-110022")))

    def test_repeat_batch_is_idempotent(self):
        bars = fixtures.build_stock_bars()[:5]
        synthetic_import.import_batch(self.conn, "stock-000001", bars, "daily_bar")
        second = synthetic_import.import_batch(self.conn, "stock-000001", bars, "daily_bar")
        self.assertEqual(0, second.inserted)
        self.assertEqual(5, second.skipped)
        self.assertEqual(5, len(repository.query_daily_bars(self.conn, "stock-000001")))

    def test_conflicting_key_is_skipped_not_overwritten(self):
        original = fixtures.build_stock_bars()[:1]
        synthetic_import.import_batch(self.conn, "stock-000001", original, "daily_bar")
        changed = [
            make_bar(
                asset_id="stock-000001",
                trade_date=original[0].trade_date,
                open_=10.0,
                high=11.0,
                low=9.0,
                close=10.8,
            )
        ]
        outcome = synthetic_import.import_batch(self.conn, "stock-000001", changed, "daily_bar")
        self.assertEqual(0, outcome.inserted)
        self.assertEqual(1, outcome.conflicts)
        self.assertNotEqual(10.8, repository.query_daily_bars(self.conn, "stock-000001")[0].close)

    def test_input_validation_failure_writes_nothing(self):
        bad = [make_bar(asset_id="stock-000001", volume=-1)]
        with self.assertRaises(TaskExecutionError):
            synthetic_import.import_batch(self.conn, "stock-000001", bad, "daily_bar")
        self.assertEqual([], repository.query_daily_bars(self.conn, "stock-000001"))

    def test_mid_batch_write_failure_rolls_back(self):
        bars = fixtures.build_stock_bars()[:3]
        with mock.patch(
            "backend.app.workers.synthetic_import.repository.insert_daily_bars",
            side_effect=sqlite3.OperationalError("boom"),
        ):
            with self.assertRaises(sqlite3.OperationalError):
                synthetic_import.import_batch(self.conn, "stock-000001", bars, "daily_bar")
        self.assertEqual([], repository.query_daily_bars(self.conn, "stock-000001"))

    def test_post_check_failure_keeps_committed_data_and_fails(self):
        bars = fixtures.build_stock_bars()[:2]
        with mock.patch(
            "backend.app.workers.synthetic_import._post_check",
            return_value=[synthetic_import.QualityIssue("DQ_TEST", "error", "stock-000001", "daily_bar", None, None, "post")],
        ):
            with self.assertRaises(TaskExecutionError) as ctx:
                synthetic_import.import_batch(self.conn, "stock-000001", bars, "daily_bar")
        self.assertEqual("POST_CHECK_FAILED", ctx.exception.error_code)
        self.assertEqual(2, len(repository.query_daily_bars(self.conn, "stock-000001")))

    def test_empty_batch_is_stable(self):
        outcome = synthetic_import.import_batch(self.conn, "stock-000001", [], "daily_bar")
        self.assertEqual(0, outcome.input_count)
        self.assertEqual(0, outcome.inserted)

    def test_worker_job_success_and_failure(self):
        bars = fixtures.build_stock_bars()[:3]
        success = run_job_once(
            self.conn,
            "synthetic_import-1",
            lambda conn, job_id: synthetic_import.synthetic_import_handler(conn, job_id, "stock-000001", bars, "daily_bar"),
        )
        self.assertEqual("success", success.status)
        self.assertEqual(3, success.processed_records)
        self.assertEqual(3, success.succeeded_records)

        bad = [make_bar(asset_id="stock-000001", trade_date=date(2024, 1, 5), volume=-1)]
        failure = run_job_once(
            self.conn,
            "synthetic_import-2",
            lambda conn, job_id: synthetic_import.synthetic_import_handler(conn, job_id, "stock-000001", bad, "daily_bar"),
        )
        self.assertEqual("failed", failure.status)
        self.assertEqual("INPUT_VALIDATION_FAILED", failure.error_code)

    def test_sql_unique_constraint_rejects_duplicate(self):
        bars = fixtures.build_stock_bars()[:1]
        synthetic_import.import_batch(self.conn, "stock-000001", bars, "daily_bar")
        record = bars[0]
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                """
                INSERT INTO daily_bars (
                    asset_id, trade_date, open, high, low, close, volume, turnover,
                    adjustment_mode, provider, fetched_at, validated_at, quality_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.asset_id,
                    record.trade_date.isoformat(),
                    record.open,
                    record.high,
                    record.low,
                    record.close,
                    record.volume,
                    record.turnover,
                    record.adjustment_mode,
                    record.provider,
                    record.fetched_at.isoformat(),
                    None,
                    record.quality_status,
                ),
            )


class SyntheticImportCliTest(unittest.TestCase):
    def test_cli_import_and_idempotency(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = os.path.join(tmp, "cli.db")
            conn = init_db(path)
            for asset in fixtures.ASSETS:
                with conn:
                    repository.insert_asset(conn, asset)
            conn.close()

            first = subprocess.run(
                [
                    sys.executable,
                    os.path.join(ROOT, "scripts", "run_worker.py"),
                    "--db", path,
                    "--task", "synthetic_import_stock",
                    "--batch", "small",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(0, first.returncode, first.stderr)
            body = json.loads(first.stdout)
            self.assertEqual("success", body["status"])
            self.assertEqual(5, body["processed_records"])
            self.assertEqual(5, body["succeeded_records"])

            second = subprocess.run(
                [
                    sys.executable,
                    os.path.join(ROOT, "scripts", "run_worker.py"),
                    "--db", path,
                    "--task", "synthetic_import_stock",
                    "--batch", "small",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(0, second.returncode, second.stderr)
            body2 = json.loads(second.stdout)
            self.assertEqual("success", body2["status"])
            self.assertEqual(0, body2["succeeded_records"])

    def test_cli_missing_db_exit_two(self):
        result = subprocess.run(
            [
                sys.executable,
                os.path.join(ROOT, "scripts", "run_worker.py"),
                "--db", "missing.db",
                "--task", "synthetic_import_stock",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(2, result.returncode)


if __name__ == "__main__":
    unittest.main()
