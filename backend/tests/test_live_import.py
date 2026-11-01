"""真实股票日线受控试点入库的离线测试。全部使用临时 SQLite，不联网。"""

from __future__ import annotations

import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, timedelta
from types import SimpleNamespace
from unittest import mock

import scripts.pilot_import_stock as pilot_cli
from backend.app.db import repository
from backend.app.db.database import init_db
from backend.app.quality.rules import QualityIssue
from backend.app.workers.jobs import TaskExecutionError, run_job_once
from backend.app.workers.live_import import (
    import_live_stock,
    import_live_stock_incremental,
    live_stock_import_handler,
    revise_live_stock,
    validate_live_stock_records,
)
from backend.tests.support import make_asset, make_bar


def build_pilot_bars(asset_id: str = "stock-000001") -> list:
    days = []
    current = date(2026, 10, 19)
    while current <= date(2026, 10, 30):
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)

    rows = []
    for i, day in enumerate(days):
        open_ = 11.0 + i * 0.01
        close = open_ + 0.05 * (1 if i % 2 == 0 else -1)
        high = max(open_, close) + 0.03
        low = min(open_, close) - 0.03
        rows.append(
            make_bar(
                asset_id=asset_id,
                trade_date=day,
                open_=open_,
                high=high,
                low=low,
                close=close,
                volume=1000 + i,
                turnover=(1000 + i) * close,
                adjustment_mode="qfq",
                provider="sina",
            )
        )
    return rows


class LiveImportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.path = os.path.join(self.tmp.name, "pilot.db")
        self.conn = init_db(self.path)
        with self.conn:
            repository.insert_asset(self.conn, make_asset("stock-000001", "stock", "000001"))

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_first_import_inserts_all_valid_rows(self):
        bars = build_pilot_bars()
        result = import_live_stock(self.conn, "stock-000001", bars)
        self.assertEqual(10, result["input_count"])
        self.assertEqual(10, result["inserted"])
        self.assertEqual(0, result["skipped"])
        self.assertEqual(0, result["conflicts"])
        self.assertTrue(result["committed"])
        self.assertEqual(10, len(repository.query_daily_bars(self.conn, "stock-000001")))

    def test_repeat_import_is_idempotent(self):
        bars = build_pilot_bars()
        import_live_stock(self.conn, "stock-000001", bars)
        second = import_live_stock(self.conn, "stock-000001", bars)
        self.assertEqual(0, second["inserted"])
        self.assertEqual(10, second["skipped"])
        self.assertTrue(second["committed"])
        self.assertEqual(10, len(repository.query_daily_bars(self.conn, "stock-000001")))

    def test_conflicting_key_is_reported_and_not_overwritten(self):
        original = build_pilot_bars()[:1]
        import_live_stock(self.conn, "stock-000001", original)
        changed = [
            make_bar(
                asset_id="stock-000001",
                trade_date=original[0].trade_date,
                open_=999.0,
                high=1000.0,
                low=998.0,
                close=999.5,
                volume=1,
            )
        ]
        outcome = import_live_stock(self.conn, "stock-000001", changed)
        self.assertEqual(0, outcome["inserted"])
        self.assertEqual(1, outcome["conflicts"])
        self.assertNotEqual(999.5, repository.query_daily_bars(self.conn, "stock-000001")[0].close)

    def test_input_quality_error_rejects_before_write(self):
        bad = [
            make_bar(
                asset_id="stock-000001",
                trade_date=date(2026, 10, 19),
                open_=0,
                high=0,
                low=0,
                close=0,
                volume=100,
            )
        ]
        with self.assertRaises(TaskExecutionError) as ctx:
            import_live_stock(self.conn, "stock-000001", bad)
        self.assertEqual("INPUT_QUALITY_FAILED", ctx.exception.error_code)
        self.assertFalse(ctx.exception.summary["committed"])
        self.assertEqual([], repository.query_daily_bars(self.conn, "stock-000001"))

    def test_mid_batch_write_failure_rolls_back(self):
        bars = build_pilot_bars()[:3]
        with mock.patch(
            "backend.app.workers.synthetic_import.repository.insert_daily_bars",
            side_effect=sqlite3.OperationalError("boom"),
        ):
            with self.assertRaises(sqlite3.OperationalError):
                import_live_stock(self.conn, "stock-000001", bars)
        self.assertEqual([], repository.query_daily_bars(self.conn, "stock-000001"))

    def test_post_check_failure_records_committed_state(self):
        bars = build_pilot_bars()[:2]

        def handler(conn, job_id):
            return live_stock_import_handler(conn, job_id, "stock-000001", bars)

        with mock.patch(
            "backend.app.workers.synthetic_import._post_check",
            return_value=[QualityIssue("DQ_TEST", "error", "stock-000001", "daily_bar", None, None, "post")],
        ):
            record = run_job_once(self.conn, "live_stock_import-test", handler)

        self.assertEqual("failed", record.status)
        summary = json.loads(record.execution_summary)
        self.assertTrue(summary["committed"])
        self.assertEqual(2, summary["inserted"])
        self.assertEqual(2, len(repository.query_daily_bars(self.conn, "stock-000001")))

    def test_asset_association_is_correct(self):
        bars = build_pilot_bars()
        import_live_stock(self.conn, "stock-000001", bars)
        rows = repository.query_daily_bars(self.conn, "stock-000001")
        self.assertTrue(all(row.asset_id == "stock-000001" for row in rows))
        self.assertEqual([], repository.query_daily_bars(self.conn, "stock-999999"))

    def test_validate_live_stock_records_is_read_only(self):
        bars = build_pilot_bars()
        validate_live_stock_records(bars, "stock-000001")
        self.assertEqual([], repository.query_daily_bars(self.conn, "stock-000001"))

    def test_incremental_import_adds_only_new_dates(self):
        first = build_pilot_bars()[:3]
        import_live_stock_incremental(self.conn, "stock-000001", first)
        result = import_live_stock_incremental(self.conn, "stock-000001", build_pilot_bars()[:5])
        self.assertEqual(2, result["new_count"])
        self.assertEqual(3, result["unchanged_count"])
        self.assertEqual(0, result["changed_count"])
        self.assertEqual(2, result["inserted"])
        self.assertEqual(5, len(repository.query_daily_bars(self.conn, "stock-000001")))

    def test_incremental_identical_batch_is_idempotent(self):
        bars = build_pilot_bars()[:4]
        import_live_stock_incremental(self.conn, "stock-000001", bars)
        result = import_live_stock_incremental(self.conn, "stock-000001", bars)
        self.assertEqual(0, result["new_count"])
        self.assertEqual(4, result["unchanged_count"])
        self.assertEqual(0, result["inserted"])
        self.assertEqual(4, len(repository.query_daily_bars(self.conn, "stock-000001")))

    def test_incremental_change_detected_not_overwritten(self):
        original = build_pilot_bars()[:2]
        import_live_stock_incremental(self.conn, "stock-000001", original)
        changed = [
            make_bar(
                asset_id="stock-000001",
                trade_date=original[0].trade_date,
                open_=99.0,
                high=100.0,
                low=98.0,
                close=99.5,
                volume=123,
            ),
            original[1],
        ]
        result = import_live_stock_incremental(self.conn, "stock-000001", changed)
        self.assertEqual(1, result["changed_count"])
        self.assertEqual(0, result["inserted"])
        self.assertEqual(1, result["conflicts"])
        self.assertNotEqual(99.5, repository.query_daily_bars(self.conn, "stock-000001")[0].close)

    def test_revise_updates_and_records_audit(self):
        original = build_pilot_bars()[:2]
        import_live_stock_incremental(self.conn, "stock-000001", original)
        updated = [
            make_bar(
                asset_id="stock-000001",
                trade_date=original[0].trade_date,
                open_=12.0,
                high=12.5,
                low=11.8,
                close=12.3,
                volume=2000,
                turnover=24600,
            ),
            original[1],
        ]
        result = revise_live_stock(self.conn, "stock-000001", updated)
        self.assertEqual(1, result["revised"])
        self.assertEqual([original[0].trade_date.isoformat()], result["changed_dates"])
        self.assertTrue(result["committed"])
        self.assertEqual(12.3, repository.query_daily_bars(self.conn, "stock-000001")[0].close)

        audits = repository.query_daily_bar_revisions(self.conn, "stock-000001")
        self.assertEqual(6, len(audits))
        close_audit = next(a for a in audits if a["field_name"] == "close")
        self.assertEqual(11.05, json.loads(close_audit["old_value"]))
        self.assertEqual(12.3, json.loads(close_audit["new_value"]))

    def test_revise_quality_failure_rejects_before_write(self):
        original = build_pilot_bars()[:1]
        import_live_stock_incremental(self.conn, "stock-000001", original)
        bad = [
            make_bar(
                asset_id="stock-000001",
                trade_date=original[0].trade_date,
                open_=0,
                high=0,
                low=0,
                close=0,
                volume=100,
            )
        ]
        with self.assertRaises(TaskExecutionError) as ctx:
            revise_live_stock(self.conn, "stock-000001", bad)
        self.assertEqual("INPUT_QUALITY_FAILED", ctx.exception.error_code)
        self.assertNotEqual(0, repository.query_daily_bars(self.conn, "stock-000001")[0].close)
        self.assertEqual([], repository.query_daily_bar_revisions(self.conn, "stock-000001"))

    def test_revise_missing_target_rejected(self):
        bars = build_pilot_bars()[:1]
        with self.assertRaises(TaskExecutionError) as ctx:
            revise_live_stock(self.conn, "stock-000001", bars)
        self.assertEqual("REVISION_TARGET_MISSING", ctx.exception.error_code)
        self.assertEqual([], repository.query_daily_bars(self.conn, "stock-000001"))

    def test_revise_transaction_failure_rolls_back(self):
        original = build_pilot_bars()[:1]
        import_live_stock_incremental(self.conn, "stock-000001", original)
        updated = [
            make_bar(
                asset_id="stock-000001",
                trade_date=original[0].trade_date,
                open_=11.2,
                high=11.5,
                low=11.0,
                close=11.4,
                volume=1500,
                turnover=17100,
            )
        ]
        with mock.patch(
            "backend.app.workers.live_import.repository.insert_daily_bars",
            side_effect=sqlite3.OperationalError("boom"),
        ):
            with self.assertRaises(sqlite3.OperationalError):
                revise_live_stock(self.conn, "stock-000001", updated)
        self.assertEqual(11.05, repository.query_daily_bars(self.conn, "stock-000001")[0].close)
        self.assertEqual([], repository.query_daily_bar_revisions(self.conn, "stock-000001"))

    def test_revise_post_check_failure_reports_committed(self):
        original = build_pilot_bars()[:1]
        import_live_stock_incremental(self.conn, "stock-000001", original)
        updated = [
            make_bar(
                asset_id="stock-000001",
                trade_date=original[0].trade_date,
                open_=11.2,
                high=11.5,
                low=11.0,
                close=11.4,
                volume=1500,
                turnover=17100,
            )
        ]
        clean = SimpleNamespace(issue_count=0, by_severity={})
        bad = SimpleNamespace(issue_count=1, by_severity={"error": 1})
        with mock.patch(
            "backend.app.workers.live_import.check_records",
            side_effect=[clean, bad],
        ):
            with self.assertRaises(TaskExecutionError) as ctx:
                revise_live_stock(self.conn, "stock-000001", updated)
        self.assertEqual("POST_CHECK_FAILED", ctx.exception.error_code)
        self.assertTrue(ctx.exception.summary["committed"])
        self.assertEqual(11.4, repository.query_daily_bars(self.conn, "stock-000001")[0].close)


class PilotPathGuardTest(unittest.TestCase):
    def test_demo_database_is_rejected(self):
        with self.assertRaises(ValueError):
            pilot_cli.resolve_pilot_path(os.path.join(pilot_cli.ROOT, "data", "demo-synthetic.db"))

    def test_expected_pilot_database_is_accepted(self):
        self.assertEqual(
            os.path.normcase(pilot_cli.expected_pilot_path()),
            os.path.normcase(
                pilot_cli.resolve_pilot_path(os.path.join(pilot_cli.ROOT, "data", "live-pilot.db"))
            ),
        )


class PilotCliOfflineTest(unittest.TestCase):
    def test_update_mode_without_live_does_not_open_db_or_network(self):
        out = io.StringIO()
        argv = [
            "pilot_import_stock.py",
            "--db",
            os.path.join(pilot_cli.ROOT, "data", "live-pilot.db"),
            "--mode",
            "update",
        ]
        with mock.patch.object(sys, "argv", argv), mock.patch.object(sys, "stdout", out), mock.patch.object(
            pilot_cli, "init_db"
        ) as init_mock, mock.patch.object(pilot_cli, "read_latest_trade_date") as read_mock:
            self.assertEqual(2, pilot_cli.main())
        init_mock.assert_not_called()
        read_mock.assert_not_called()
        self.assertIn('"database_written": false', out.getvalue())


if __name__ == "__main__":
    unittest.main()
