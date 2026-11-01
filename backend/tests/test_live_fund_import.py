"""真实基金净值端到端接入的离线测试。全部使用 mock 响应或临时 SQLite，不联网。"""

from __future__ import annotations

import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, timedelta
from unittest import mock

import scripts.pilot_import_fund as fund_cli
from backend.app.db import repository
from backend.app.db.database import init_db
from backend.app.providers.base import NetworkError
from backend.app.providers.fund_lsjz import LsjzFundAdapter, map_lsjz_item
from backend.app.quality.rules import QualityIssue
from backend.app.workers.jobs import TaskExecutionError, run_job_once
from backend.app.workers.live_fund_import import (
    classify_live_fund_changes,
    import_live_fund_incremental,
    live_fund_import_handler,
    validate_live_fund_records,
)
from backend.tests.support import make_asset, make_nav


def build_fund_navs(asset_id: str = "fund-110022") -> list:
    rows = []
    current = date(2026, 10, 1)
    i = 0
    while current <= date(2026, 10, 30):
        if current.weekday() < 5:
            rows.append(
                make_nav(
                    asset_id=asset_id,
                    nav_date=current,
                    unit_nav=round(1.5 + i * 0.01, 4),
                    accumulated_nav=round(1.8 + i * 0.01, 4),
                    provider="eastmoney_fund_lsjz",
                )
            )
            i += 1
        current += timedelta(days=1)
    return rows


class LsjzAdapterTest(unittest.TestCase):
    def test_maps_unit_and_accumulated_nav_without_ohlc(self):
        adapter = LsjzFundAdapter(
            lambda *_: [{"FSRQ": "2026-10-01", "DWJZ": "1.5", "LJJZ": "1.8"}]
        )
        result = adapter.fetch_history("fund-110022")
        record = result.records[0]
        self.assertEqual(1.5, record.unit_nav)
        self.assertEqual(1.8, record.accumulated_nav)
        self.assertFalse(hasattr(record, "open"))
        self.assertFalse(hasattr(record, "volume"))

    def test_missing_unit_nav_is_blocking(self):
        adapter = LsjzFundAdapter(lambda *_: [{"FSRQ": "2026-10-01", "LJJZ": "1.8"}])
        result = adapter.fetch_history("fund-110022")
        self.assertEqual([], result.records)
        self.assertTrue(any(e.code == "VALIDATION_BLOCKING" for e in result.errors))

    def test_network_error_is_wrapped(self):
        def fail(*_):
            raise ConnectionError("boom")

        adapter = LsjzFundAdapter(fail)
        with self.assertRaises(NetworkError):
            adapter.fetch_history("fund-110022")

    def test_empty_response(self):
        adapter = LsjzFundAdapter(lambda *_: [])
        result = adapter.fetch_history("fund-110022")
        self.assertTrue(result.empty)
        self.assertEqual([], result.records)

    def test_map_does_not_swap_columns(self):
        mapped = map_lsjz_item({"FSRQ": "2026-10-01", "DWJZ": 1.5, "LJJZ": 1.8})
        self.assertEqual(1.5, mapped["unit_nav"])
        self.assertEqual(1.8, mapped["accumulated_nav"])


class LiveFundImportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.path = os.path.join(self.tmp.name, "fund-pilot.db")
        self.conn = init_db(self.path)
        with self.conn:
            repository.insert_asset(self.conn, make_asset("fund-110022", "open_fund", "110022"))

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_first_import_inserts_all_rows(self):
        navs = build_fund_navs()
        result = import_live_fund_incremental(self.conn, "fund-110022", navs)
        self.assertEqual(len(navs), result["inserted"])
        self.assertEqual(0, result["skipped"])
        self.assertEqual(0, result["conflicts"])
        self.assertTrue(result["committed"])
        self.assertEqual(len(navs), len(repository.query_fund_navs(self.conn, "fund-110022")))

    def test_repeat_import_is_idempotent(self):
        navs = build_fund_navs()
        import_live_fund_incremental(self.conn, "fund-110022", navs)
        second = import_live_fund_incremental(self.conn, "fund-110022", navs)
        self.assertEqual(0, second["inserted"])
        self.assertEqual(len(navs), second["skipped"])
        self.assertEqual(len(navs), len(repository.query_fund_navs(self.conn, "fund-110022")))

    def test_same_date_different_content_reported_not_overwritten(self):
        navs = build_fund_navs()[:1]
        import_live_fund_incremental(self.conn, "fund-110022", navs)
        changed = [make_nav(asset_id="fund-110022", nav_date=navs[0].nav_date, unit_nav=9.9)]
        result = import_live_fund_incremental(self.conn, "fund-110022", changed)
        self.assertEqual(0, result["inserted"])
        self.assertEqual(1, result["changed_count"])
        self.assertEqual(1, result["conflicts"])
        self.assertNotEqual(9.9, repository.query_fund_navs(self.conn, "fund-110022")[0].unit_nav)

    def test_quality_failure_rejects_before_write(self):
        bad = [make_nav(asset_id="fund-110022", nav_date=date(2026, 10, 1), unit_nav=0)]
        with self.assertRaises(TaskExecutionError) as ctx:
            import_live_fund_incremental(self.conn, "fund-110022", bad)
        self.assertEqual("INPUT_QUALITY_FAILED", ctx.exception.error_code)
        self.assertFalse(ctx.exception.summary["committed"])
        self.assertEqual([], repository.query_fund_navs(self.conn, "fund-110022"))

    def test_transaction_failure_rolls_back(self):
        navs = build_fund_navs()[:3]
        with mock.patch(
            "backend.app.workers.synthetic_import.repository.insert_fund_navs",
            side_effect=sqlite3.OperationalError("boom"),
        ):
            with self.assertRaises(sqlite3.OperationalError):
                import_live_fund_incremental(self.conn, "fund-110022", navs)
        self.assertEqual([], repository.query_fund_navs(self.conn, "fund-110022"))

    def test_post_check_failure_reports_committed(self):
        navs = build_fund_navs()[:2]

        def handler(conn, job_id):
            return live_fund_import_handler(conn, job_id, "fund-110022", navs)

        with mock.patch(
            "backend.app.workers.synthetic_import._post_check",
            return_value=[QualityIssue("DQ_TEST", "error", "fund-110022", "fund_nav", None, None, "post")],
        ):
            record = run_job_once(self.conn, "live_fund_update-test", handler)
        self.assertEqual("failed", record.status)
        summary = json.loads(record.execution_summary)
        self.assertTrue(summary["committed"])
        self.assertEqual(2, summary["inserted"])
        self.assertEqual(2, len(repository.query_fund_navs(self.conn, "fund-110022")))

    def test_classify_fund_changes_is_read_only(self):
        navs = build_fund_navs()[:2]
        classify_live_fund_changes(self.conn, "fund-110022", navs)
        self.assertEqual([], repository.query_fund_navs(self.conn, "fund-110022"))


class FundWindowTest(unittest.TestCase):
    def test_window_from_latest(self):
        self.assertEqual(
            (date(2026, 10, 31), date(2026, 11, 2)),
            fund_cli.compute_fund_window_from_latest(date(2026, 10, 30), date(2026, 11, 2), 60),
        )

    def test_up_to_date_returns_none(self):
        self.assertIsNone(
            fund_cli.compute_fund_window_from_latest(date(2026, 11, 2), date(2026, 11, 2), 60)
        )

    def test_empty_database_requires_explicit_range(self):
        with self.assertRaises(ValueError):
            fund_cli.compute_fund_window_from_latest(None, date(2026, 11, 2), 60)

    def test_too_long_window_is_rejected(self):
        with self.assertRaises(ValueError):
            fund_cli.compute_fund_window_from_latest(date(2025, 1, 1), date(2026, 11, 2), 60)


class FundPathGuardTest(unittest.TestCase):
    def test_stock_and_demo_databases_are_rejected(self):
        for name in ("live-pilot.db", "demo-synthetic.db"):
            with self.assertRaises(ValueError):
                fund_cli.resolve_fund_pilot_path(os.path.join(fund_cli.ROOT, "data", name))

    def test_fund_pilot_database_is_accepted(self):
        self.assertEqual(
            os.path.normcase(fund_cli.expected_fund_pilot_path()),
            os.path.normcase(
                fund_cli.resolve_fund_pilot_path(
                    os.path.join(fund_cli.ROOT, "data", "live-fund-pilot.db")
                )
            ),
        )

    def test_offline_cli_does_not_open_db_or_network(self):
        out = io.StringIO()
        argv = [
            "pilot_import_fund.py",
            "--db",
            os.path.join(fund_cli.ROOT, "data", "live-fund-pilot.db"),
        ]
        with mock.patch.object(sys, "argv", argv), mock.patch.object(sys, "stdout", out), mock.patch.object(
            fund_cli, "init_db"
        ) as init_mock, mock.patch.object(fund_cli, "read_latest_fund_nav_date") as read_mock:
            self.assertEqual(2, fund_cli.main())
        init_mock.assert_not_called()
        read_mock.assert_not_called()
        self.assertIn('"database_written": false', out.getvalue())


if __name__ == "__main__":
    unittest.main()
